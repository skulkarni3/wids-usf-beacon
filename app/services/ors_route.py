"""
Open Route Service (ORS) Evacuation Route
────────────────────────────────────────────────────────────
Inputs:

- bounding box (focus area currently: Colorado)
- dates (hardcoded for now July 15th - July 22nd 2025)
- list of evacuation_polygons (obtain from BQ watch duty data)
- ORS API key 

Output:

-evacuation_map.html (interactive start and end points, re-routes around evacuation polygons)
────────────────────────────────────────────────────────────
"""
import re
import os
import json
import math
from typing import Optional

from shapely.geometry import shape, mapping
from shapely.ops import unary_union

from dotenv import load_dotenv
from google.cloud import bigquery
import anthropic
import openrouteservice
import pandas as pd

from .facilities_search import *
from .widlfire_potential import return_hwp_records

load_dotenv()

# Languages natively supported by ORS for turn-by-turn instructions
_ORS_SUPPORTED_LANGUAGES = {
    "ca", "cs", "de", "en", "eo", "es", "fi", "fr", "he", "hu",
    "id", "it", "ja", "ko", "nb", "nl", "pl", "pt", "ro", "ru",
    "sv", "tr", "uk", "vi", "zh",
}


def _translate_instructions(steps: list[dict], target_language: str) -> list[dict]:
    """Translate all 'instruction' values in steps to target_language using Claude."""
    if not steps:
        return steps
    instructions = [s["instruction"] for s in steps]
    numbered = "\n".join(f"{i+1}. {txt}" for i, txt in enumerate(instructions))
    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        resp = client.messages.create(
            model=os.getenv("ANTHROPIC_LLM_MODEL"),
            max_tokens=1024,
            messages=[{"role": "user", "content":
                f"Translate each navigation instruction below to ISO 639-1 language '{target_language}'. "
                f"Return only the translated lines, numbered the same way, no extra text:\n\n{numbered}"}]
        )
        lines = resp.content[0].text.strip().split("\n")
        for i, line in enumerate(lines):
            if i < len(steps):
                # Strip leading "1. " numbering if present
                translated = re.sub(r"^\d+\.\s*", "", line).strip()
                if translated:
                    steps[i]["instruction"] = translated
    except Exception as e:
        print(f"[translate_instructions] failed: {e}")
    return steps


# ──────────────────────────────────────────
#  GET LIST OF EVACUATION POLYGONS FROM BIGQUERY
# ──────────────────────────────────────────
def get_fire_polygons(bbox, start_date, end_date):
    client = bigquery.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT"))
    sw_lon, sw_lat, ne_lon, ne_lat = bbox

    query = f"""
    SELECT ST_ASTEXT(geo_json) AS wkt
    FROM `watch_duty.left_join_evac_zones_gis_evaczone_evaczonechangelog_flat_geojson`
    WHERE DATE(date_created) BETWEEN {start_date} AND {end_date}
    AND ST_INTERSECTSBOX(
        geo_json,
        {sw_lon}, {sw_lat},
        {ne_lon}, {ne_lat}
    )
    """

    df = client.query(query).to_dataframe()

    return df["wkt"].tolist()


# ──────────────────────────────────────────
#  WKT PARSER
# ──────────────────────────────────────────

def parse_wkt_polygon(wkt) -> dict:
    """
    Convert a WKT POLYGON string → GeoJSON Polygon dict.

    Accepts:
        POLYGON((-108.94 38.70, -108.93 38.69, ...))
        POLYGON ((-108.94 38.70, ...))          ← space before paren is fine
        SRID=4326;POLYGON(...)                  ← SRID prefix is stripped
        A row list from DataFrame.to_numpy().tolist() — the first str containing POLYGON is used
    """
    if isinstance(wkt, list):
        matches = [v for v in wkt if isinstance(v, str) and re.search(r"POLYGON", v, re.IGNORECASE)]
        if not matches:
            raise ValueError(f"No POLYGON string found in row: {wkt}")
        wkt = matches[0]
    wkt = wkt.strip()
    # Strip optional SRID prefix (e.g. "SRID=4326;POLYGON(...)")
    wkt = re.sub(r"^SRID\s*=\s*\d+\s*;\s*", "", wkt, flags=re.IGNORECASE)
    inner = re.search(r"POLYGON\s*\(\s*\((.+)\)\s*\)", wkt, re.IGNORECASE)
    if not inner:
        raise ValueError(f"Could not parse WKT: {wkt[:80]}")

    pairs = inner.group(1).strip().split(",")
    coords = []
    for pair in pairs:
        parts = [p.strip("() \t\r\n") for p in pair.strip().split()]
        parts = [p for p in parts if p]
        if len(parts) >= 2:
            coords.append([float(parts[0]), float(parts[1])])

    # GeoJSON rings must close; add first point at end if missing
    if coords[0] != coords[-1]:
        coords.append(coords[0])

    return {"type": "Polygon", "coordinates": [coords]}


def parse_multipolygon_wkt(wkt: str) -> list[dict]:
    """
    Convert a WKT MULTIPOLYGON string into a list of GeoJSON Polygon dicts.
    e.g. MULTIPOLYGON(((...), (...)), ((...)))  →  [Polygon, Polygon, ...]
    """
    inner = re.search(r"MULTIPOLYGON\s*\(\s*\((.+)\)\s*\)", wkt, re.IGNORECASE | re.DOTALL)
    if not inner:
        raise ValueError(f"Could not parse MULTIPOLYGON WKT: {wkt[:80]}")

    polygons = []
    # Split on "), (" to separate individual polygon rings
    rings_str = inner.group(1)
    # Each ring is wrapped in "(...)"
    for ring_match in re.finditer(r"\(([^()]+)\)", rings_str):
        pairs = ring_match.group(1).strip().split(",")
        coords = []
        for pair in pairs:
            parts = [p.strip("() \t\r\n") for p in pair.strip().split()]
            parts = [p for p in parts if p]
            if len(parts) >= 2:
                coords.append([float(parts[0]), float(parts[1])])
        if coords:
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            polygons.append({"type": "Polygon", "coordinates": [coords]})
    return polygons


def parse_all_polygons(wkt_list: list[str]) -> list[dict]:
    """Parse a list of WKT strings (POLYGON or MULTIPOLYGON) into GeoJSON Polygon dicts."""
    result = []
    for w in wkt_list:
        wkt_str = w[0] if isinstance(w, list) else w
        if not isinstance(wkt_str, str):
            continue
        wkt_clean = re.sub(r"^SRID\s*=\s*\d+\s*;\s*", "", wkt_str.strip(), flags=re.IGNORECASE)
        try:
            if re.match(r"MULTIPOLYGON", wkt_clean, re.IGNORECASE):
                result.extend(parse_multipolygon_wkt(wkt_clean))
            else:
                result.append(parse_wkt_polygon(wkt_str))
        except Exception as e:
            print(f"⚠️  Skipping unparseable polygon: {e}")
    return result


def union_overlapping_polygons(geojson_polygons: list[dict]) -> list[dict]:
    """
    Merge overlapping GeoJSON Polygon dicts into a minimal set of non-overlapping
    polygons using shapely unary_union. Useful for clean visualization — overlapping
    evacuation zones collapse into a single combined red area.

    Returns a list of GeoJSON Polygon dicts (fewer entries than input if zones overlap).
    """
    if not geojson_polygons:
        return []
    merged = unary_union([shape(p) for p in geojson_polygons])
    if merged.geom_type == "Polygon":
        return [mapping(merged)]
    # MultiPolygon — split back into individual Polygon dicts
    return [mapping(geom) for geom in merged.geoms]


# ──────────────────────────────────────────
#  ROUTING
# ──────────────────────────────────────────

def get_route(
    api_key: str,
    start: list,
    end: list,
    geojson_polygons: list[dict],
    language: str = "en",
    via: Optional[list] = None,
) -> tuple[dict, str]:
    """
    Request a driving route from ORS that avoids all supplied polygons.

    Parameters
    ----------
    start / end         : [lon, lat]
    geojson_polygons    : list of GeoJSON Polygon dicts
    via                 : optional [lon, lat] intermediate waypoint (e.g. drop-by stop)
    """
    client = openrouteservice.Client(key=api_key)

    avoid_opts: dict = {}
    if geojson_polygons:
        avoid_polygon = (
            {"type": "Polygon", "coordinates": geojson_polygons[0]["coordinates"]}
            if len(geojson_polygons) == 1
            else {
                "type": "MultiPolygon",
                "coordinates": [p["coordinates"] for p in geojson_polygons],
            }
        )
        avoid_opts = {"avoid_polygons": avoid_polygon}

    coordinates = [start, via, end] if via else [start, end]
    # radiuses: -1 = unlimited snap distance; one per coordinate
    radiuses = [-1] * len(coordinates)

    # Prefer ORS-native language if we believe it's supported, else fall back to English.
    # If ORS rejects the language at runtime (e.g., a code mismatch like "ko" vs "ko_KR"),
    # retry in English so we still get a route, then translate instructions with Claude.
    requested = (language or "en").strip().lower()
    ors_lang = requested if requested in _ORS_SUPPORTED_LANGUAGES else "en"

    def _directions(lang: str) -> dict:
        return client.directions(
            coordinates=coordinates,
            profile="driving-car",
            format="geojson",
            options=avoid_opts if avoid_opts else {},
            radiuses=radiuses,
            language=lang,
        )

    try:
        route = _directions(ors_lang)
        return route, ors_lang
    except Exception as e:
        # If the request wasn't already English, retry in English and let the caller
        # translate the resulting instructions into the requested language.
        msg = str(e)
        should_retry_en = ors_lang != "en" and (
            "parameter 'language'" in msg.lower()
            or "incorrect value" in msg.lower()
            or "language" in msg.lower()
        )
        if should_retry_en:
            route = _directions("en")
            return route, "en"
        raise


def _closest_dropby_to_midpoint(route_coords: list, dropbys: list) -> Optional[dict]:
    """
    Pick the dropby closest to the midpoint of the route.
    This is a good heuristic for where to insert a waypoint — not too early, not too late.
    """
    if not dropbys or not route_coords:
        return None
    mid_idx = len(route_coords) // 2
    mid_lon, mid_lat = route_coords[mid_idx]
    return min(
        dropbys,
        key=lambda d: _haversine_km(mid_lon, mid_lat, d["lng"], d["lat"]),
    )


# ──────────────────────────────────────────
#  DIRECTIONS EXTRACTION
# ──────────────────────────────────────────

def extract_directions(route: dict) -> tuple[list[dict], float, float]:
    """
    Pull step-by-step instructions out of an ORS GeoJSON response.

    Returns
    -------
    steps           : list of dicts — instruction / distance_m / duration_s / name
    total_distance  : metres
    total_duration  : seconds
    """
    steps = []
    for segment in route["features"][0]["properties"]["segments"]:
        for step in segment["steps"]:
            steps.append(
                {
                    "instruction": step["instruction"],
                    "distance_m":  step["distance"],
                    "duration_s":  step["duration"],
                    "name":        step.get("name", ""),
                }
            )

    summary = route["features"][0]["properties"]["summary"]
    return steps, summary["distance"], summary["duration"]


# ──────────────────────────────────────────
#  MAP  (pure Leaflet — no Folium needed)
# ──────────────────────────────────────────
def build_map(
    geojson_polygons: list[dict],
    start: list,
    end: list,
    api_key: str,
    out_html: str = "evacuation_map.html",
    bbox: Optional[tuple] = None,
    facilities_df=None,
) -> str:
    import json

    center_lat = (start[1] + end[1]) / 2
    center_lon = (start[0] + end[0]) / 2

    polygons_js = json.dumps(geojson_polygons)

    avoid_geom = (
        {"type": "Polygon", "coordinates": geojson_polygons[0]["coordinates"]}
        if len(geojson_polygons) == 1
        else {"type": "MultiPolygon", "coordinates": [p["coordinates"] for p in geojson_polygons]}
    )
    avoid_js = json.dumps(avoid_geom)

    bbox_js = "null"
    if bbox:
        sw_lon, sw_lat, ne_lon, ne_lat = bbox
        bbox_geojson = {
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [sw_lon, sw_lat], [ne_lon, sw_lat],
                    [ne_lon, ne_lat], [sw_lon, ne_lat],
                    [sw_lon, sw_lat],
                ]]
            }
        }
        bbox_js = json.dumps(bbox_geojson)

    facilities_js = "[]"
    if facilities_df is not None and not facilities_df.empty:
        keep = facilities_df[["lat", "lng", "facility_type"]].dropna()
        facilities_js = keep.to_json(orient="records")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Evacuation Route</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"/>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; display: flex; height: 100vh; overflow: hidden; }}

  #sidebar {{
    width: 340px; min-width: 280px; height: 100vh;
    background: #1a1a2e; color: #eee;
    display: flex; flex-direction: column;
    box-shadow: 4px 0 20px rgba(0,0,0,0.4); z-index: 1000;
  }}
  #sidebar-header {{
    background: #c0392b; padding: 16px 18px;
    font-size: 17px; font-weight: 700; letter-spacing: 0.5px;
  }}
  #sidebar-header span {{ font-size: 13px; font-weight: 400; opacity: 0.85; display: block; margin-top: 2px; }}
  #sidebar-body {{ flex: 1; overflow-y: auto; padding: 16px; }}

  .section-title {{
    font-size: 11px; font-weight: 700; letter-spacing: 1px;
    text-transform: uppercase; color: #aaa; margin: 14px 0 6px;
  }}
  .coord-row {{ display: flex; gap: 8px; margin-bottom: 8px; }}
  .coord-row input {{
    flex: 1; padding: 8px 10px; border-radius: 6px; border: 1px solid #333;
    background: #0f0f1e; color: #eee; font-size: 13px;
  }}
  .coord-row input:focus {{ outline: none; border-color: #4a90d9; }}
  .coord-label {{ font-size: 11px; color: #aaa; margin-bottom: 3px; }}

  #reroute-btn {{
    width: 100%; padding: 11px; border-radius: 7px; border: none; cursor: pointer;
    background: #c0392b; color: white; font-size: 14px; font-weight: 700;
    margin-top: 10px; transition: background 0.2s;
  }}
  #reroute-btn:hover {{ background: #e74c3c; }}
  #reroute-btn:disabled {{ background: #555; cursor: not-allowed; }}

  #download-btn {{
    width: 100%; padding: 10px; border-radius: 7px; border: none; cursor: pointer;
    background: #27ae60; color: white; font-size: 13px; font-weight: 600;
    margin-top: 8px; transition: background 0.2s; display: none;
  }}
  #download-btn:hover {{ background: #2ecc71; }}

  #status {{
    font-size: 12px; color: #f39c12; margin-top: 8px; min-height: 18px; text-align: center;
  }}
  #summary {{
    background: #0f0f1e; border-radius: 8px; padding: 12px;
    margin-top: 10px; font-size: 13px; display: none;
  }}
  #summary b {{ color: #4a90d9; font-size: 15px; }}

  #fac-legend {{
    background: #0f0f1e; border-radius: 8px; padding: 10px 12px;
    margin-top: 10px; font-size: 12px; display: none;
  }}
  #fac-legend .leg-title {{ color: #aaa; font-size: 11px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }}
  #fac-legend .leg-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }}
  #fac-legend .dot {{ width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }}

  #steps-list {{ list-style: none; margin-top: 12px; padding: 0; }}
  #steps-list li {{
    padding: 7px 0; border-bottom: 1px solid #2a2a3e;
    font-size: 12px; line-height: 1.5; color: #ccc;
  }}
  #steps-list li:last-child {{ border-bottom: none; }}
  #steps-list li .step-num {{ color: #4a90d9; font-weight: 700; margin-right: 5px; }}
  #steps-list li .step-dist {{ color: #777; font-size: 11px; }}

  #map {{ flex: 1; height: 100vh; }}
  .drag-hint {{
    background: rgba(0,0,0,0.75); color: white; border: none;
    font-size: 11px; padding: 4px 8px; border-radius: 4px; white-space: nowrap;
  }}
</style>
</head>
<body>

<div id="sidebar">
  <div id="sidebar-header">
    🔥 Evacuation Router
    <span>Drag markers or type coordinates, then reroute</span>
  </div>
  <div id="sidebar-body">

    <div class="section-title">Start Location</div>
    <div class="coord-label">Latitude &nbsp;/&nbsp; Longitude</div>
    <div class="coord-row">
      <input id="start-lat" type="number" step="0.0001" placeholder="Lat" value="{start[1]}"/>
      <input id="start-lon" type="number" step="0.0001" placeholder="Lon" value="{start[0]}"/>
    </div>

    <div class="section-title">End Location</div>
    <div class="coord-label">Latitude &nbsp;/&nbsp; Longitude</div>
    <div class="coord-row">
      <input id="end-lat" type="number" step="0.0001" placeholder="Lat" value="{end[1]}"/>
      <input id="end-lon" type="number" step="0.0001" placeholder="Lon" value="{end[0]}"/>
    </div>

    <button id="reroute-btn" onclick="fetchRoute()">🔄 Reroute</button>
    <button id="download-btn" onclick="downloadGeoJSON()">⬇ Download GeoJSON</button>
    <div id="status"></div>

    <div id="summary"></div>

    <div id="fac-legend">
      <div class="leg-title">Nearby Facilities On Route</div>
      <div class="leg-row"><div class="dot" style="background:#2980b9"></div>Pharmacy</div>
      <div class="leg-row"><div class="dot" style="background:#27ae60"></div>Supermarket</div>
      <div class="leg-row"><div class="dot" style="background:#f39c12"></div>Convenience Store</div>
      <div class="leg-row"><div class="dot" style="background:#8e44ad"></div>Supercenter</div>
      <div id="fac-count" style="color:#aaa; font-size:11px; margin-top:6px;"></div>
    </div>

    <ul id="steps-list"></ul>
  </div>
</div>

<div id="map"></div>

<script>
const ORS_KEY        = "{api_key}";
const HAZARD_ZONES   = {polygons_js};
const AVOID_GEOM     = {avoid_js};
const BBOX_GEOJSON   = {bbox_js};
const ALL_FACILITIES = {facilities_js};

const FAC_STYLE = {{
  pharmacy:          {{ color: '#2980b9', label: 'Pharmacy'       }},
  supermarket:       {{ color: '#27ae60', label: 'Supermarket'    }},
  convenience_store: {{ color: '#f39c12', label: 'Convenience'    }},
  supercenter:       {{ color: '#8e44ad', label: 'Supercenter'    }},
  other:             {{ color: '#7f8c8d', label: 'Other'          }},
}};

// Colour map for GeoJSON export (Mapbox marker-color standard)
const FAC_COLOURS = {{
  pharmacy:          '#2980b9',
  supermarket:       '#27ae60',
  convenience_store: '#f39c12',
  supercenter:       '#8e44ad',
  other:             '#7f8c8d',
}};

const BUFFER_KM = 2.0;

const map = L.map('map').setView([{center_lat}, {center_lon}], 10);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  attribution: '© OpenStreetMap contributors'
}}).addTo(map);

if (BBOX_GEOJSON) {{
  L.geoJSON(BBOX_GEOJSON, {{
    style: {{ color:'#a0785a', fillColor:'#c4a882', fillOpacity:0.08, weight:2.5, dashArray:'8 6' }}
  }}).bindTooltip('Focus Area', {{ className:'drag-hint', permanent:false }}).addTo(map);
}}

HAZARD_ZONES.forEach((polygon, i) => {{
  L.geoJSON(polygon, {{
    style: {{ color:'#cc0000', fillColor:'#cc0000', fillOpacity:0.35, weight:2 }},
  }}).bindTooltip(`Hazard Zone ${{i+1}}`, {{ className:'drag-hint' }}).addTo(map);
}});

const greenIcon = new L.Icon({{
  iconUrl:'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-green.png',
  shadowUrl:'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
  iconSize:[25,41], iconAnchor:[12,41], popupAnchor:[1,-34], shadowSize:[41,41]
}});
const blueIcon = new L.Icon({{
  iconUrl:'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-blue.png',
  shadowUrl:'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
  iconSize:[25,41], iconAnchor:[12,41], popupAnchor:[1,-34], shadowSize:[41,41]
}});

let startMarker = L.marker([{start[1]}, {start[0]}], {{ draggable:true, icon:greenIcon }})
  .bindPopup('<b>START</b> — drag to move').addTo(map);
let endMarker   = L.marker([{end[1]},   {end[0]}],   {{ draggable:true, icon:blueIcon  }})
  .bindPopup('<b>END</b> — drag to move').addTo(map);

startMarker.on('dragend', e => {{
  const ll = e.target.getLatLng();
  document.getElementById('start-lat').value = ll.lat.toFixed(5);
  document.getElementById('start-lon').value = ll.lng.toFixed(5);
  fetchRoute();
}});
endMarker.on('dragend', e => {{
  const ll = e.target.getLatLng();
  document.getElementById('end-lat').value = ll.lat.toFixed(5);
  document.getElementById('end-lon').value = ll.lng.toFixed(5);
  fetchRoute();
}});

let routeLayer       = null;
let facilityLayer    = null;
let lastRouteGeoJSON = null;
let shownFacilities  = [];   // tracks filtered facilities for GeoJSON export

function haversineKm(lat1, lon1, lat2, lon2) {{
  const R  = 6371;
  const dL = (lat2 - lat1) * Math.PI / 180;
  const dO = (lon2 - lon1) * Math.PI / 180;
  const a  = Math.sin(dL/2)**2 +
             Math.cos(lat1*Math.PI/180) * Math.cos(lat2*Math.PI/180) * Math.sin(dO/2)**2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}}

function minDistToRoute(lat, lon, routeCoords) {{
  let minD = Infinity;
  for (let i = 0; i < routeCoords.length - 1; i++) {{
    const [x1,y1] = routeCoords[i];
    const [x2,y2] = routeCoords[i+1];
    const dx = x2-x1, dy = y2-y1;
    const t  = dx||dy ? Math.max(0, Math.min(1, ((lon-x1)*dx + (lat-y1)*dy) / (dx*dx+dy*dy))) : 0;
    const px = x1 + t*dx, py = y1 + t*dy;
    const d  = haversineKm(lat, lon, py, px);
    if (d < minD) minD = d;
  }}
  return minD;
}}

function drawFacilities(routeCoords) {{
  if (facilityLayer) map.removeLayer(facilityLayer);
  facilityLayer   = L.layerGroup().addTo(map);
  shownFacilities = [];   // reset so download always reflects current route

  if (!ALL_FACILITIES.length) return;

  ALL_FACILITIES.forEach(f => {{
    const d = minDistToRoute(f.lat, f.lng, routeCoords);
    if (d > BUFFER_KM) return;

    shownFacilities.push(f);   // save for GeoJSON export

    const style  = FAC_STYLE[f.facility_type] || FAC_STYLE.other;
    const circle = L.circleMarker([f.lat, f.lng], {{
      radius: 7, color: '#fff', weight: 1.5,
      fillColor: style.color, fillOpacity: 0.9,
    }}).bindPopup(`<b>${{style.label}}</b><br><small>${{d.toFixed(2)}} km from route</small>`);

    facilityLayer.addLayer(circle);
  }});

  const shown = shownFacilities.length;
  document.getElementById('fac-legend').style.display = shown ? 'block' : 'none';
  document.getElementById('fac-count').textContent =
    `${{shown}} facilit${{shown===1?'y':'ies'}} within ${{BUFFER_KM}} km of route`;
}}

async function fetchRoute() {{
  const startLat = parseFloat(document.getElementById('start-lat').value);
  const startLon = parseFloat(document.getElementById('start-lon').value);
  const endLat   = parseFloat(document.getElementById('end-lat').value);
  const endLon   = parseFloat(document.getElementById('end-lon').value);

  if ([startLat, startLon, endLat, endLon].some(isNaN)) {{
    setStatus('⚠️ Please enter valid coordinates.', '#f39c12'); return;
  }}

  startMarker.setLatLng([startLat, startLon]);
  endMarker.setLatLng([endLat, endLon]);

  setStatus('⏳ Fetching route…', '#4a90d9');
  document.getElementById('reroute-btn').disabled = true;
  document.getElementById('download-btn').style.display = 'none';
  document.getElementById('fac-legend').style.display   = 'none';

  try {{
    const body = {{
      coordinates: [[startLon, startLat], [endLon, endLat]],
      options: {{ avoid_polygons: AVOID_GEOM }},
    }};

    const res = await fetch('https://api.openrouteservice.org/v2/directions/driving-car/geojson', {{
      method: 'POST',
      headers: {{ 'Content-Type':'application/json', 'Authorization': ORS_KEY }},
      body: JSON.stringify(body),
    }});

    if (!res.ok) {{
      const err = await res.json();
      throw new Error(err.error?.message || `HTTP ${{res.status}}`);
    }}

    const data = await res.json();
    lastRouteGeoJSON = data;

    if (routeLayer) map.removeLayer(routeLayer);
    routeLayer = L.geoJSON(data, {{
      style: {{ color:'#0057FF', weight:5, opacity:0.85 }}
    }}).addTo(map);
    map.fitBounds(routeLayer.getBounds(), {{ padding:[40,40] }});

    const routeCoords = data.features[0].geometry.coordinates;
    drawFacilities(routeCoords);

    const summary = data.features[0].properties.summary;
    const distKm  = (summary.distance / 1000).toFixed(1);
    const durMin  = Math.round(summary.duration / 60);
    document.getElementById('summary').style.display = 'block';
    document.getElementById('summary').innerHTML =
      `<b>${{distKm}} km</b> &nbsp;·&nbsp; <b>~${{durMin}} min</b>
       &nbsp;·&nbsp; ${{HAZARD_ZONES.length}} hazard zone(s) avoided`;

    const steps    = data.features[0].properties.segments.flatMap(s => s.steps);
    const stepList = document.getElementById('steps-list');
    stepList.innerHTML = steps.map((s, i) =>
      `<li><span class="step-num">${{i+1}}.</span>${{s.instruction}}
       <span class="step-dist">(${{Math.round(s.distance)}}m)</span></li>`
    ).join('');

    document.getElementById('download-btn').style.display = 'block';
    setStatus('✅ Route updated.', '#2ecc71');

  }} catch(err) {{
    setStatus(`❌ ${{err.message}}`, '#e74c3c');
  }} finally {{
    document.getElementById('reroute-btn').disabled = false;
  }}
}}

function downloadGeoJSON() {{
  if (!lastRouteGeoJSON) return;

  const features = [...lastRouteGeoJSON.features];

  // Hazard zones
  HAZARD_ZONES.forEach((polygon, i) => {{
    features.push({{
      type: 'Feature',
      properties: {{ name: `Hazard Zone ${{i+1}}`, fill: '#cc0000', 'fill-opacity': 0.35 }},
      geometry: polygon,
    }});
  }});

  // On-route facilities as GeoJSON Points (Mapbox marker-color compatible)
  shownFacilities.forEach(f => {{
    const colour = FAC_COLOURS[f.facility_type] || FAC_COLOURS.other;
    const label  = f.facility_type.replace(/_/g, ' ').replace(/\b\\w/g, c => c.toUpperCase());
    features.push({{
      type: 'Feature',
      properties: {{
        name:            label,
        facility_type:   f.facility_type,
        'marker-color':  colour,
        'marker-size':   'small',
        'marker-symbol': 'circle',
      }},
      geometry: {{
        type:        'Point',
        coordinates: [f.lng, f.lat],
      }},
    }});
  }});

  const blob = new Blob(
    [JSON.stringify({{ type: 'FeatureCollection', features }}, null, 2)],
    {{ type: 'application/json' }}
  );
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'evacuation_route.geojson';
  a.click();
}}

function setStatus(msg, color) {{
  const el = document.getElementById('status');
  el.textContent = msg; el.style.color = color;
}}

fetchRoute();
</script>
</body>
</html>"""

    with open(out_html, "w") as f:
        f.write(html)
    return out_html


# ──────────────────────────────────────────
#  GEOJSON EXPORT
# ──────────────────────────────────────────

def export_geojson(
    route: dict,
    geojson_polygons: list[dict],
    out_path: str = "evacuation_route.geojson",
    facilities=None,          # ← NEW: list of dicts with lat/lng/facility_type
                              #        (pass the rows that passed the buffer test)
) -> str:
    """
    Save a FeatureCollection containing:
      - The ORS route line  (blue)
      - All hazard polygons (red)
      - On-route facilities as Point features  ← NEW

    The file can be opened in QGIS, ArcGIS, Mapbox, geojson.io,
    or loaded into any navigation tool that accepts GeoJSON.

    Returns the saved file path.
    """
    import json

    # Colour map matches the Leaflet UI
    FAC_COLOURS = {
        "pharmacy":          "#2980b9",
        "supermarket":       "#27ae60",
        "convenience_store": "#f39c12",
        "supercenter":       "#8e44ad",
        "other":             "#7f8c8d",
    }

    features = []

    # ── Route line ────────────────────────────────────────────────────────────
    route_feature = route["features"][0]
    route_feature["properties"]["stroke"]       = "#0057FF"
    route_feature["properties"]["stroke-width"] = 4
    route_feature["properties"]["name"]         = "Evacuation Route"
    features.append(route_feature)

    # ── Hazard polygons (merged so overlapping zones show as one area) ────────
    display_polygons = union_overlapping_polygons(geojson_polygons)
    for idx, polygon in enumerate(display_polygons):
        features.append({
            "type": "Feature",
            "properties": {
                "name":         f"Hazard Zone {idx + 1}",
                "fill":         "#cc0000",
                "fill-opacity": 0.35,
                "stroke":       "#cc0000",
                "stroke-width": 2,
            },
            "geometry": polygon,
        })

    # ── On-route facilities (Points) ──────────────────────────────────────────
    if facilities:
        for fac in facilities:
            ftype  = fac.get("facility_type", "other")
            colour = FAC_COLOURS.get(ftype, FAC_COLOURS["other"])
            label  = ftype.replace("_", " ").title()
            features.append({
                "type": "Feature",
                "properties": {
                    "name":         label,
                    "facility_type": ftype,
                    # Mapbox / geojson.io style hints
                    "marker-color":  colour,
                    "marker-size":   "small",
                    "marker-symbol": "circle",
                },
                "geometry": {
                    "type":        "Point",
                    "coordinates": [fac["lng"], fac["lat"]],   # GeoJSON = [lon, lat]
                },
            })

    collection = {"type": "FeatureCollection", "features": features}

    n_fac = len(facilities) if facilities else 0
    if out_path is None:
        # Caller wants the dict in memory (e.g. API response), not a file.
        print(f"✅ GeoJSON built in memory  "
              f"({len(geojson_polygons)} hazard zones, {n_fac} facilities)")
        return collection

    with open(out_path, "w") as f:
        json.dump(collection, f, indent=2)

    print(f"💾 GeoJSON saved → {out_path}  "
          f"({len(geojson_polygons)} hazard zones, {n_fac} facilities)")
    return out_path


# ──────────────────────────────────────────
#  CONSOLE PRINTER
# ──────────────────────────────────────────

def print_directions(steps: list[dict], total_distance: float, total_duration: float) -> None:
    print("\n" + "=" * 58)
    print("  EVACUATION ROUTE — Turn-by-Turn")
    print("=" * 58)
    for i, s in enumerate(steps, 1):
        print(f"  {i:>2}. {s['instruction']:<46} [{round(s['distance_m'])}m]")
    print("-" * 58)
    print(f"  Total : {round(total_distance / 1000, 1)} km  |  ~{round(total_duration / 60)} min")
    print("=" * 58 + "\n")


# ──────────────────────────────────────────
#  PUBLIC ENTRY POINT
# ──────────────────────────────────────────

def run_evacuation_route(
    api_key:        str,
    polygons:       list[str],
    start:          list,
    end:            list,
    out_html:       str = "evacuation_map.html",
    out_geojson:    str = "evacuation_route.geojson",
    bbox:           Optional[tuple] = None,
    verbose:        bool = True,
    facilities_df:  Optional[pd.DataFrame] = None,   # ← NEW
) -> dict:
    if not polygons:
        raise ValueError("Supply at least one WKT polygon.")

    print(f"📐 Parsing {len(polygons)} hazard polygon(s)...")
    geojson_polygons = parse_all_polygons(polygons)

    print("🗺  Building interactive map...")
    map_file = build_map(
        geojson_polygons=geojson_polygons,
        start=start,
        end=end,
        api_key=api_key,
        out_html=out_html,
        bbox=bbox,
        facilities_df=facilities_df,              # ← passed through
    )
    print(f"✅  Saved → {map_file}")
    return {"map_file": map_file}

# ──────────────────────────────────────────
#  TRY TWEAKING VALUES
# ──────────────────────────────────────────

if __name__ == "__main__":
    BBOX = (-109.052784, 38.135615, -107.388355, 38.733711)

    FIRE_POLYGONS = get_fire_polygons(BBOX, '2025-07-10', '2025-09-18')

    # Query facilities for the same bounding box
    co_bbox   = state_to_bbox("CO")          # full state; filter to BBOX after if preferred
    fac_data  = query_facilities(co_bbox)
    fac_df    = facs_to_df(fac_data)

    # Optional: pre-filter to the BBOX so the JSON payload isn't huge
    fac_df = fac_df[
        (fac_df["lat"].between(BBOX[1], BBOX[3])) &
        (fac_df["lng"].between(BBOX[0], BBOX[2]))
    ]

    run_evacuation_route(
        api_key        = os.getenv("ORS_API"),
        polygons       = FIRE_POLYGONS,
        start          = [-108.55, 38.50],
        end            = [-107.87, 37.95],
        out_html       = "evacuation_map.html",
        bbox           = BBOX,
        facilities_df  = fac_df             
    )

  
def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Straight-line distance in km between two (lon, lat) points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _get_dropbys_on_route(
    route_coords: list,
    dropby_candidates,
    buffer_km: float = 2.0,
    n_samples: int = 10,
) -> list:
    """
    Return the subset of *dropby_candidates* that lie within *buffer_km*
    of any sampled point along the route, as a list of dicts with
    keys: lat, lng, and any other columns present.

    Returns an empty list if none are found, or if dropby_candidates is None
    (meaning no requirement — callers should treat None as "no filter").

    Parameters
    ----------
    route_coords       : list of [lon, lat] pairs from ORS GeoJSON geometry
    dropby_candidates  : DataFrame with 'lat' and 'lng' columns, or list of
                         dicts with the same keys
    buffer_km          : proximity threshold in km (default 2.0)
    n_samples          : number of route points to sample for the proximity check
    """
    if dropby_candidates is None:
        return []

    total = len(route_coords)
    if total == 0:
        return []

    if total <= n_samples:
        indices = list(range(total))
    else:
        indices = [round(i * (total - 1) / (n_samples - 1)) for i in range(n_samples)]

    # Normalise dropby_candidates to list of dicts
    if hasattr(dropby_candidates, "to_dict"):
        records = dropby_candidates.to_dict(orient="records")
    else:
        records = list(dropby_candidates)

    matched, seen = [], set()
    for i in indices:
        rlon, rlat = route_coords[i]
        for rec in records:
            key = (rec["lat"], rec["lng"])
            if key in seen:
                continue
            if _haversine_km(rlon, rlat, rec["lng"], rec["lat"]) <= buffer_km:
                matched.append(rec)
                seen.add(key)

    return matched


def _hwp_fraction_along_route(
    route_coords: list,
    hwp_dt,
    hwp_threshold: float,
    n_samples: int = 10,
    cache: dict = None,
) -> float:
    """
    Sample HWP at evenly-spaced points along the route and return the
    fraction of sampled points whose HWP exceeds *hwp_threshold*.

    HWP has a ~3 km grid resolution, so points are snapped to the nearest
    grid cell (~0.03°) before querying. Results are stored in *cache* so
    repeated calls across multiple candidates reuse BQ results for the
    same grid cell instead of re-querying.

    Parameters
    ----------
    route_coords   : list of [lon, lat] pairs from ORS GeoJSON geometry
    hwp_dt         : datetime (UTC) to pass to return_hwp_records
    hwp_threshold  : HWP value above which a point is considered high-risk
    n_samples      : number of points to sample along the route
    cache          : dict shared across calls to avoid duplicate BQ queries
    """
    if cache is None:
        cache = {}

    total = len(route_coords)
    if total == 0:
        return 0.0

    # Pick evenly-spaced indices; always include first and last
    if total <= n_samples:
        indices = list(range(total))
    else:
        indices = [round(i * (total - 1) / (n_samples - 1)) for i in range(n_samples)]

    high, sampled = 0, 0
    for i in indices:
        lon, lat = route_coords[i]
        # Snap to ~3 km HRRR grid cell so nearby points share one BQ query
        cell_key = (round(lat, 2), round(lon, 2))
        if cell_key not in cache:
            try:
                df = return_hwp_records(lon, lat, hwp_dt)
                if df.empty:
                    cache[cell_key] = None
                else:
                    # Return_hwp_records gives all hours for the grid point;
                    # pick the row whose datetime_utc is closest to hwp_dt.
                    closest_idx = (df["datetime_utc"] - pd.Timestamp(hwp_dt)).abs().idxmin()
                    cache[cell_key] = float(df.loc[closest_idx, "hwp"])
            except Exception:
                cache[cell_key] = None

        hwp_val = cache[cell_key]
        if hwp_val is not None:
            if hwp_val > hwp_threshold:
                high += 1
            sampled += 1

    return high / sampled if sampled > 0 else 0.0


def return_optimal_end_candidate(
    start: tuple,
    polygon_to_avoid_lists: list,
    end_candidates: list,
    api_key: str = None,
    max_candidates: int = None,
    max_distance_km: float = 500,
    hwp_datetime=None,
    hwp_threshold: float = 50,
    hwp_max_fraction: float = 0.2,
    dropby_candidates=None,
    dropby_buffer_km: float = 2.0,
    require_dropby: bool = True,
    language: str = "en",
) -> Optional[dict]:
    """
    Try routing from *start* to each candidate end point via ORS,
    avoiding all supplied polygons, and return the fastest reachable route
    whose HWP exposure is within acceptable limits.

    Candidates are sorted by straight-line distance from *start* before any
    ORS calls are made, so the nearest shelters are tried first and fewer
    API calls are wasted on far-away unreachable points.

    Parameters
    ----------
    start                 : (lon, lat) of the origin
    polygon_to_avoid_lists: list of WKT or GeoJSON polygon strings to avoid
    end_candidates        : list of (lon, lat) tuples to try as destinations
    api_key               : ORS API key (falls back to ORS_API env var)
    max_candidates        : if set, only try the N closest candidates (limits ORS calls)
    hwp_datetime          : datetime (UTC) for HWP lookup; if None, HWP check is skipped
    hwp_threshold         : HWP value above which a route point is considered high-risk
                            (default 50% — adjust to your risk tolerance)
    hwp_max_fraction      : maximum allowed fraction of route points with HWP above
                            hwp_threshold (default 0.2 = 20%)
    dropby_candidates     : DataFrame (lat/lng cols) or list of dicts — locations
                            that must appear within dropby_buffer_km of the route.
                            If None, no drop-by requirement is enforced.
    dropby_buffer_km      : proximity threshold for drop-by locations (default 2.0 km)

    Returns
    -------
    dict with keys:
        end          - (lon, lat) of the chosen destination
        end_index    - original index into end_candidates
        route        - raw ORS GeoJSON route dict
        steps        - turn-by-turn instruction list
        distance_m   - total route distance in metres
        duration_s   - total route duration in seconds
        hwp_fraction     - fraction of sampled points above hwp_threshold (0 if skipped)
        has_dropby       - True if a drop-by location is on the route
    Returns None if no candidate is reachable within the HWP limit and drop-by requirement.
    """
    api_key = api_key or os.getenv("ORS_API")
    if not api_key:
        raise ValueError("ORS API key required — pass api_key or set ORS_API env var.")

    # Normalise end_candidates: accept a DataFrame with lng/lat columns or a list
    if hasattr(end_candidates, "itertuples"):
        end_candidates = [[r.lng, r.lat] for r in end_candidates.itertuples()]

    # Parse avoidance polygons once
    geojson_polygons = parse_all_polygons(polygon_to_avoid_lists)

    start_ll = list(start)   # [lon, lat]

    # Sort candidates by straight-line distance to minimise ORS calls
    indexed = sorted(
        enumerate(end_candidates),
        key=lambda iv: _haversine_km(start_ll[0], start_ll[1], iv[1][0], iv[1][1]),
    )
    # Drop candidates farther than max_distance_km (ORS hard limit ~6000 km; practical evac << 500 km)
    indexed = [
        (i, end) for i, end in indexed
        if _haversine_km(start_ll[0], start_ll[1], end[0], end[1]) <= max_distance_km
    ]
    if max_candidates is not None:
        indexed = indexed[:max_candidates]

    best = None
    hwp_cache: dict = {}   # shared across all candidates — grid cells queried once
    total_candidates = len(indexed)
    print(f"🔍 Evaluating {total_candidates} candidate(s) within {max_distance_km} km of start {start_ll} ...")
  
    for loop_i, (idx, end) in enumerate(indexed, 1):
        end_ll = list(end)
        print(f"\n[{loop_i}/{total_candidates}] Candidate {idx} → {end}")
        try:
            print(f"  🗺  Requesting ORS route ...")
            route, ors_lang_used = get_route(api_key, start_ll, end_ll, geojson_polygons, language=language)
            steps, distance_m, duration_s = extract_directions(route)
            # Translate whenever ORS didn't produce instructions in the requested language,
            # including when ORS rejected the language and we retried in English.
            if language and language != "en" and ors_lang_used != (language.strip().lower()):
                try:
                    steps = _translate_instructions(steps, language.strip().lower())
                except Exception as e:
                    # Translation is best-effort: keep English instructions if it fails
                    # so routing still works in emergencies.
                    print(f"[translate_instructions] failed: {e}")
            print(f"  ✓  Route: {round(distance_m/1000, 1)} km, ~{round(duration_s/60)} min")

            # ── HWP check ────────────────────────────────────────────────────
            hwp_fraction = 0.0
            route_coords = route["features"][0]["geometry"]["coordinates"]
            if hwp_datetime is not None:
                print(f"  🔥 Checking HWP along {len(route_coords)}-point route "
                      f"(sampling 10 pts, {len(hwp_cache)} grid cells already cached) ...")
                hwp_fraction = _hwp_fraction_along_route(
                    route_coords, hwp_datetime, hwp_threshold, cache=hwp_cache
                )
                print(f"  🔥 HWP fraction: {hwp_fraction:.0%} (limit {hwp_max_fraction:.0%}, "
                      f"threshold {hwp_threshold})")
                if hwp_fraction > hwp_max_fraction:
                    print(f"  ⚠️  Skipped — too much fire risk on route")
                    continue

            # ── Drop-by check ─────────────────────────────────────────────────
            dropbys_on_route = _get_dropbys_on_route(
                route_coords, dropby_candidates, dropby_buffer_km
            )
            if require_dropby and dropby_candidates is not None and not dropbys_on_route:
                print(f"  ⚠️  Skipped — no drop-by location within {dropby_buffer_km} km of route (required)")
                continue
            print(f"  🏪 {len(dropbys_on_route)} drop-by location(s) found on route")

            # When the user confirmed a drop-by stop, re-route via the closest facility
            # so the ORS route actually passes through it rather than just annotating it.
            if require_dropby and dropbys_on_route:
                via_dropby = _closest_dropby_to_midpoint(route_coords, dropbys_on_route)
                if via_dropby:
                    via_ll = [via_dropby["lng"], via_dropby["lat"]]
                    print(f"  🔄 Re-routing via drop-by: {via_dropby.get('name', via_ll)}")
                    try:
                        route, ors_lang_used = get_route(
                            api_key, start_ll, end_ll, geojson_polygons,
                            language=language, via=via_ll,
                        )
                        steps, distance_m, duration_s = extract_directions(route)
                        if language and language != "en" and ors_lang_used != language.strip().lower():
                            try:
                                steps = _translate_instructions(steps, language.strip().lower())
                            except Exception:
                                pass
                        print(f"  ✓  Via-route: {round(distance_m/1000, 1)} km, ~{round(duration_s/60)} min")
                    except Exception as e:
                        # Via-routing failed (e.g. dropby is off-road) — keep the direct route,
                        # still flag the dropby as nearby.
                        print(f"  ⚠️  Via-route failed ({e}), keeping direct route with dropby annotation")

            # Candidates are sorted nearest-first, so the first one that
            # passes both HWP and drop-by checks is the optimal evacuation route.
            best = {
                "end":              end,
                "end_index":        idx,
                "route":            route,
                "steps":            steps,
                "distance_m":       distance_m,
                "duration_s":       duration_s,
                "hwp_fraction":     hwp_fraction,
                "dropbys_on_route": dropbys_on_route,
            }
            print(f"  ✅ Valid route found — stopping search")
            break
        except Exception as e:
            print(f"  ⚠️  Unreachable: {e}")
            continue

    if best:
        hwp_info = f", HWP {best['hwp_fraction']:.0%} on route" if hwp_datetime else ""
        print(
            f"✅ Optimal end: candidate {best['end_index']} {best['end']}  "
            f"— {round(best['distance_m']/1000, 1)} km, "
            f"~{round(best['duration_s']/60)} min{hwp_info}"
        )
    else:
        print("❌ No reachable end candidate found within HWP limit.")

    return best