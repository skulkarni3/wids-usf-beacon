"""
app/services/hwp_map.py
========================
Transforms HWP point data into a GeoJSON FeatureCollection of merged
colour-band polygons.

Each HWP colour band (e.g. 10-20, 20-30 ...) has all its grid cell
squares merged into a single unified Polygon/MultiPolygon via
shapely.unary_union before being returned. This eliminates the
overlap-darkening artefact that occurs when semi-transparent cells
stack on top of each other — each colour band is one flat shape
with no internal overlaps.

Public API
----------
    build_hwp_geojson(timestamp) -> dict
        Returns a GeoJSON FeatureCollection ready to be returned from
        the FastAPI endpoint or overlaid on any Leaflet / Mapbox map.
"""

from __future__ import annotations

import glob
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np

from shapely.geometry import box, mapping
from shapely.ops import unary_union

from ..services import bigquery as bq_service

# ── NOAA HWP colour bands ─────────────────────────────────────────────────────
_HWP_LEVELS = [10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100]
_HWP_COLORS = [
    "#0033ff",   # 10–20  deep blue
    "#0099ff",   # 20–30  sky blue
    "#00ccff",   # 30–40  cyan
    "#00ffdd",   # 40–50  aqua
    "#00cc00",   # 50–60  green
    "#99ee00",   # 60–70  yellow-green
    "#ffff00",   # 70–80  yellow
    "#ffaa00",   # 80–90  orange
    "#ff2200",   # 90–95  red-orange
    "#cc00cc",   # 95–100 magenta
]

# Half-width of each grid cell square in degrees.
# HRRR uses Lambert Conformal projection so degree-width varies across the
# domain — fixed half-widths always leave gaps at some latitudes.
# 0.02° slightly overlaps neighbouring cells at all latitudes, eliminating
# the striping effect while keeping individual cells visually distinct when
# zoomed in.
_CELL_HALF = 0.02

# <repo_root>/data/
_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


# ── Colour lookup ─────────────────────────────────────────────────────────────

def _hex_to_rgba(hex_color: str, alpha: float = 0.35) -> str:
    """Convert a #rrggbb hex string to an rgba() CSS string with the given alpha."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _hwp_color(value: float) -> str:
    """Return the NOAA-palette hex colour for a raw HWP value.
    Returns None for values below 10 — those cells are not displayed."""
    try:
        if value is None or pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    if value < _HWP_LEVELS[0]:   # below 10 — skip entirely
        return None
    for i in range(len(_HWP_LEVELS) - 1):
        if value < _HWP_LEVELS[i + 1]:
            return _HWP_COLORS[i]
    return _HWP_COLORS[-1]


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_hwp_for_hour(timestamp: datetime) -> tuple[pd.DataFrame, str]:
    """
    Return (df, source) where df has columns [latitude, longitude, hwp]
    for the 1-hour window:  timestamp < datetime_utc <= timestamp + 1h.

    Tries local CSV first, falls back to BigQuery.
    """
    ts_str       = timestamp.strftime("%Y-%m-%d %H:%M:%S")
    ts_plus1_str = (timestamp + pd.Timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

    # ── Local CSV (chunked to avoid loading 3 GB) ─────────────────────────────
    csv_files = sorted(glob.glob(str(_DATA_DIR / "hwp_colorado*.csv")))
    if csv_files:
        print(f"[hwp_map] Reading CSV in chunks: {csv_files[0]}")
        ts_lo = pd.Timestamp(ts_str)
        ts_hi = pd.Timestamp(ts_plus1_str)
        chunks = []

        for chunk in pd.read_csv(
            csv_files[0],
            usecols=["datetime_utc", "latitude", "longitude", "hwp"],
            parse_dates=["datetime_utc"],
            chunksize=100_000,
        ):
            if chunk["datetime_utc"].dt.tz is not None:
                chunk["datetime_utc"] = chunk["datetime_utc"].dt.tz_localize(None)

            mask = (chunk["datetime_utc"] > ts_lo) & (chunk["datetime_utc"] <= ts_hi)
            hit  = chunk.loc[mask, ["latitude", "longitude", "hwp"]].dropna(subset=["hwp"])
            if not hit.empty:
                chunks.append(hit)

            # CSV is sorted by time — stop once we've passed the window
            if chunk["datetime_utc"].max() > ts_hi:
                break

        result = pd.concat(chunks) if chunks else pd.DataFrame(
            columns=["latitude", "longitude", "hwp"]
        )
        print(f"[hwp_map] {len(result)} rows from CSV")
        return result, "csv"

    # ── BigQuery fallback ─────────────────────────────────────────────────────
    print("[hwp_map] No local CSV — querying BigQuery")
    client = bq_service.BigQueryClient()
    sql = f"""
        SELECT latitude, longitude, hwp
        FROM `{client.project}.watch_duty.hwp_colorado`
        WHERE datetime_utc >  TIMESTAMP('{ts_str}')
          AND datetime_utc <= TIMESTAMP('{ts_plus1_str}')
          AND hwp IS NOT NULL
    """
    return client.query(sql), "bigquery"


# ── Polygon builder ───────────────────────────────────────────────────────────

def _point_to_cell_polygon(lat: float, lon: float) -> list[list[float]]:
    """
    Return a closed GeoJSON ring (list of [lon, lat] pairs) for a square
    cell centred on (lat, lon) with half-width _CELL_HALF degrees.
    """
    h = _CELL_HALF
    return [
        [lon - h, lat - h],
        [lon + h, lat - h],
        [lon + h, lat + h],
        [lon - h, lat + h],
        [lon - h, lat - h],   # close the ring
    ]


# ── Public entry point ────────────────────────────────────────────────────────

def build_hwp_geojson(timestamp: datetime) -> dict:
    """
    Load HWP data for *timestamp* and return a GeoJSON FeatureCollection
    where each feature is a filled square polygon representing one HRRR
    grid cell, coloured according to the NOAA HWP palette.

    Features below the 10th-percentile colour band are omitted (transparent
    on the map — matches NOAA's display convention of not shading low values).

    Parameters
    ----------
    timestamp : datetime
        UTC hour to query, e.g. datetime(2025, 8, 15, 18).

    Returns
    -------
    dict  GeoJSON FeatureCollection with keys:
        type       – "FeatureCollection"
        features   – list of Polygon features
        metadata   – point_count, timestamp_utc, source
    """
    df, source = _load_hwp_for_hour(timestamp)

    if df.empty:
        return {
            "type":     "FeatureCollection",
            "features": [],
            "metadata": {
                "timestamp_utc": str(timestamp),
                "point_count":   0,
                "source":        source,
            },
        }

    # Assign each row to a colour band
    df["colour"] = df["hwp"].apply(_hwp_color)
    df = df[df["colour"].notna()]   # drop below-10 rows

    # Group cells by colour band and merge into one unified shape per band.
    # unary_union dissolves all overlapping squares in a band into a single
    # Polygon or MultiPolygon — no internal overlaps means no darkening.
    features = []
    for colour, group in df.groupby("colour", sort=False):
        cell_boxes = [
            box(row["longitude"] - _CELL_HALF,
                row["latitude"]  - _CELL_HALF,
                row["longitude"] + _CELL_HALF,
                row["latitude"]  + _CELL_HALF)
            for _, row in group.iterrows()
        ]
        merged   = unary_union(cell_boxes)
        geojson_geom = mapping(merged)   # Polygon or MultiPolygon

        rgba = _hex_to_rgba(colour, alpha=0.45)
        features.append({
            "type": "Feature",
            "properties": {
                "band":         next(
                    f"{_HWP_LEVELS[i]}-{_HWP_LEVELS[i+1]}"
                    for i in range(len(_HWP_LEVELS) - 1)
                    if _HWP_COLORS[i] == colour
                ),
                "fill":         rgba,
                "fill-opacity": 1.0,    # opacity baked into rgba — no stacking artefacts
                "stroke":       rgba,
                "stroke-width": 0,
            },
            "geometry": geojson_geom,
        })

    print(f"[hwp_map] Built {len(features)} merged band features from {len(df)} grid points")
    return {
        "type":     "FeatureCollection",
        "features": features,
        "metadata": {
            "timestamp_utc": str(timestamp),
            "point_count":   len(features),
            "source":        source,
        },
    }


# ── Colour scale metadata (for frontend legend) ───────────────────────────────

def hwp_color_scale() -> list[dict]:
    """
    Return the NOAA colour scale as a list of dicts for rendering a legend.

    Example return value:
        [{"min": 10, "max": 20, "color": "#0033ff", "label": "10–20"}, ...]
    """
    return [
        {
            "min":   _HWP_LEVELS[i],
            "max":   _HWP_LEVELS[i + 1],
            "color": _HWP_COLORS[i],
            "label": f"{_HWP_LEVELS[i]}–{_HWP_LEVELS[i + 1]}",
        }
        for i in range(len(_HWP_LEVELS) - 1)
    ]