import json
from datetime import datetime

import asyncio
import pandas as pd
from fastapi import APIRouter
from typing import Optional

from ..services import ors_route
from ..services import bigquery
from ..services import check_evac
from ..services import hwp_map as hwp_map_service
from ..services import fcm

router = APIRouter()


@router.get("/route/generate")
async def generate_route(
    lon: float,
    lat: float,
    timestamp: datetime,
    dropby_type: str = "store",
    prefer_dropby: bool = False,
    distance: float = 50000,
    hwp_threshold: float = 50,
    hwp_max_fraction: float = 0.1,
    max_candidates: int = 100,
    language: str = "en",
    user_id: Optional[str] = None,
):
    """
    Compute the optimal evacuation route from start to the nearest safe shelter.

    Drop-by behaviour (convenience stores / pharmacies near the route):
      - Candidates are ALWAYS fetched from BigQuery (CO_facilities).
      - prefer_dropby=False (default): finds the best route WITHOUT requiring a
        drop-by stop, but scans the route and returns any nearby facilities in
        `dropbys_on_route` so the agent can offer them as an option.
      - prefer_dropby=True: requires a drop-by stop on the route (adds a waypoint).
        Use this when the user has confirmed they want to include a stop.

    Returns
    -------
    {status: "success", geojson: "...", summary: {...}}
    or
    {status: "no_routes", max_candidates: N}
    """
    print(f"[route/generate] lon={lon} lat={lat} ts={timestamp} "
          f"distance={distance} hwp_threshold={hwp_threshold} "
          f"hwp_max_fraction={hwp_max_fraction} max_candidates={max_candidates} "
          f"prefer_dropby={prefer_dropby} dropby_type={dropby_type}")

    bq = bigquery.BigQueryClient()

    # Always fetch both shelter sources concurrently and merge them.
    evac_coro = asyncio.to_thread(
        lambda: check_evac.return_evac_records(lon, lat, timestamp, distance)
                          [["geo_json"]].to_numpy().tolist()
    )
    shelter_coro = asyncio.to_thread(
        bq.select_single_table, "watch_duty", "CO_shelter", ["id", "lng", "lat", "name"]
    )
    shelter_coro2 = asyncio.to_thread(
        bq.select_single_table, "watch_duty",
        "left_join_geo_events_geoevent_flat_geoeventchangelog_flat",
        ["name", "lng", "lat", "name"],
        "location_type = 'evac_shelter'"
    )

    # Always fetch facilities so we can surface nearby ones even without a required stop.
    # dropby_type="none" skips the facility scan entirely (backwards-compatible with
    # the Map tab which doesn't need the chip offer).
    fetch_facilities = prefer_dropby or dropby_type == "store"

    if fetch_facilities:
        polygon_to_avoid_list, shelters, shelters2, dropby_candidates = await asyncio.gather(
            evac_coro,
            shelter_coro,
            shelter_coro2,
            asyncio.to_thread(
                bq.select_single_table, "watch_duty", "CO_facilities", ["id", "lng", "lat", "name"]
            ),
        )
    else:
        polygon_to_avoid_list, shelters, shelters2 = await asyncio.gather(evac_coro, shelter_coro, shelter_coro2)
        dropby_candidates = None

    end_candidates = pd.concat([shelters, shelters2], ignore_index=True)

    # Pass empty polygon list to ORS: routing around evac zones forces paths
    # through high-HWP areas, defeating the purpose. The HWP check already
    # excludes fire-risk routes. Evac polygons are kept only for the GeoJSON overlay.
    result = await asyncio.to_thread(
        ors_route.return_optimal_end_candidate,
        (lon, lat),
        [],
        end_candidates,
        hwp_datetime=timestamp,
        hwp_threshold=hwp_threshold,
        hwp_max_fraction=hwp_max_fraction,
        max_candidates=max_candidates,
        dropby_candidates=dropby_candidates,
        require_dropby=prefer_dropby,
        language=language,
    )

    # If the drop-by requirement blocked every candidate, retry without it so
    # the user still gets a safe evacuation route (drop-by becomes best-effort).
    if not result and prefer_dropby:
        print("[route/generate] No route with required drop-by — retrying without drop-by requirement")
        result = await asyncio.to_thread(
            ors_route.return_optimal_end_candidate,
            (lon, lat),
            [],
            end_candidates,
            hwp_datetime=timestamp,
            hwp_threshold=hwp_threshold,
            hwp_max_fraction=hwp_max_fraction,
            max_candidates=max_candidates,
            dropby_candidates=dropby_candidates,
            require_dropby=False,
            language=language,
        )
        if result:
            result["dropby_fallback"] = True

    if not result:
        if user_id:
            df = bq.select_single_table(
                "watch_duty", "device_tokens", ["device_token", "language"],
                condition=f"user_id = '{user_id}'", num=1,
            )
            print(f"df - {df}")
            if not df.empty:
                token_row = df.iloc[0]
                token_lang = token_row.get("language") or language
                fcm.send_no_route_alert(token_row["device_token"], language=token_lang)
        return {"status": "no_routes", "max_candidates": max_candidates}

    # Destination name — look it up from end_candidates by original index.
    shelter_name = "nearest shelter"
    try:
        if hasattr(end_candidates, "iloc"):
            shelter_row = end_candidates.iloc[result["end_index"]]
            shelter_name = (shelter_row.get("name", shelter_name)
                            if hasattr(shelter_row, "get")
                            else getattr(shelter_row, "name", shelter_name))
    except Exception:
        pass

    geojson_dict = ors_route.export_geojson(
        route=result["route"],
        geojson_polygons=ors_route.parse_all_polygons(polygon_to_avoid_list),
        out_path=None,
        facilities=result["dropbys_on_route"],
    )

    dropby_names = [d.get("name", "store") for d in result["dropbys_on_route"]]
    summary = {
        "destination":      shelter_name,
        "distance_km":      round(result["distance_m"] / 1000, 1),
        "duration_min":     round(result["duration_s"] / 60),
        "dropbys_on_route": dropby_names,
        "dropby_fallback":  result.get("dropby_fallback", False),
    }

    return {
        "status":  "success",
        "geojson": json.dumps(geojson_dict),
        "summary": summary,
    }


@router.get("/map/hwp")
async def hwp_map(timestamp: datetime):
    """
    GeoJSON FeatureCollection of HWP grid cells for Colorado at the
    requested UTC hour.

    Each feature is a small square Polygon (~3 km × 3 km) coloured with
    the NOAA HWP discrete palette. Drop directly into any Leaflet or
    Mapbox map as a GeoJSON layer.

    Data source: data/hwp_colorado*.csv if present, otherwise BigQuery.

    Parameters
    ----------
    timestamp : datetime
        UTC hour, e.g. 2025-08-15T18:00:00
        Must fall within 2025-07-10 – 2025-09-18.
    """
    result = await asyncio.to_thread(hwp_map_service.build_hwp_geojson, timestamp)

    if result["metadata"]["point_count"] == 0:
        return {
            "status": "no_data",
            "detail": (
                f"No HWP data for {timestamp}. "
                "Check the timestamp is within 2025-07-10 – 2025-09-18 "
                "and the CSV or BigQuery table is populated."
            ),
        }

    return result


@router.get("/map/hwp/legend")
async def hwp_legend():
    """
    Return the NOAA HWP colour scale as a list for rendering a map legend.
    Each entry has: min, max, color, label.
    """
    return hwp_map_service.hwp_color_scale()
