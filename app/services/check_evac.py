import datetime
import math
from typing import Optional

import contextily as ctx
import folium
import pandas as pd
import geopandas as gpd
import matplotlib.lines as mlines
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from shapely.geometry import Point, Polygon

from .bigquery import *

def parse_ewkt_ring(polygon_str: str) -> list[tuple[float, float]]:
    """Parse SRID=4326;POLYGON((...)) or POLYGON((...)) into a coordinate ring."""
    wkt_str = polygon_str.split(";", 1)[-1].strip()
    coords_str = wkt_str[wkt_str.index("((") + 2 : wkt_str.rindex("))")]
    return [
        tuple(float(v) for v in pair.strip().split())
        for pair in coords_str.split(",")
    ]


def point_in_polygon(lon: float,
                     lat: float,
                     polygon_str: str) -> bool:
    """Ray-casting point-in-polygon test."""
    ring = parse_ewkt_ring(polygon_str)
    inside = False
    x, y = lon, lat
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside



def visualize_point_in_polygon(
    lon: float,
    lat: float,
    polygon_str: str,
    save_png: str = None,
) -> tuple[folium.Map, Optional[str]]:
    """
    Show a single point and polygon on a US map, auto-zoomed to the polygon bounds.

    Accepts standard WKT or EWKT with an SRID prefix, e.g.:
      "SRID=4326;POLYGON((-121.78 39.74, ...))"

    The point marker is colored:
      - GREEN  → point is inside the polygon
      - RED    → point is outside the polygon

    Parameters
    ----------
    lon         : longitude of the point
    lat         : latitude of the point
    polygon_str : WKT or EWKT string of the polygon
    save_png    : optional file path to save a static PNG (e.g. "map.png").
                  If None, no PNG is saved.

    Returns
    -------
    (folium.Map, png_path | None)
    """
    polygon = Polygon(parse_ewkt_ring(polygon_str))
    point = Point(lon, lat)
    inside = polygon.contains(point)

    color = "green" if inside else "red"
    status = "Inside polygon" if inside else "Outside polygon"

    # --- Folium interactive map ---
    m = folium.Map(location=[39.5, -98.35], zoom_start=4, tiles="OpenStreetMap")

    folium.GeoJson(
        polygon.__geo_interface__,
        style_function=lambda _: {
            "fillColor": "#3388ff",
            "color": "#0033cc",
            "weight": 2,
            "fillOpacity": 0.2,
        },
    ).add_to(m)

    folium.CircleMarker(
        location=[lat, lon],
        radius=8,
        color=color,
        fill=True,
        fill_color=color,
        fill_opacity=0.9,
        popup=folium.Popup(
            f"<b>lon:</b> {lon}<br><b>lat:</b> {lat}<br><b>Status:</b> {status}",
            max_width=250,
        ),
    ).add_to(m)

    min_lon, min_lat, max_lon, max_lat = polygon.bounds
    m.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])
    folium.LatLngPopup().add_to(m)

    # --- Static PNG ---
    png_path = None
    if save_png:
        polygon_gdf = gpd.GeoDataFrame(geometry=[polygon], crs="EPSG:4326").to_crs(epsg=3857)
        point_gdf = gpd.GeoDataFrame(geometry=[point], crs="EPSG:4326").to_crs(epsg=3857)

        fig, ax = plt.subplots(figsize=(10, 8))
        polygon_gdf.plot(ax=ax, facecolor="#3388ff", edgecolor="#0033cc", alpha=0.25, linewidth=2)
        point_gdf.plot(ax=ax, color=color, markersize=120, zorder=5)
        ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik)
        ax.set_axis_off()
        ax.set_title(f"Point in Polygon  |  {status}", fontsize=13, pad=12)

        polygon_handle = mpatches.Patch(facecolor="#3388ff", edgecolor="#0033cc", alpha=0.5, label="Polygon")
        point_handle = mlines.Line2D([], [], color=color, marker="o", linestyle="None", markersize=8, label=status)
        ax.legend(handles=[polygon_handle, point_handle], loc="lower right", fontsize=10)

        fig.tight_layout()
        fig.savefig(save_png, dpi=150, bbox_inches="tight")
        plt.close(fig)
        png_path = save_png
    
    html_path = png_path.replace('.png', '.html')
    m.save(html_path)
    return html_path, png_path


def return_evac_records(lon: float,
                        lat: float,
                        timestamp: datetime,
                        dist: int=50000, # meters
                       ) -> pd.DataFrame:
    """
    table_name: include a column named geo_json which is a geojson type.
    output: all the rows from table_name where polygon in geo_json includes (lon, lat)
    This uses BigQuery's geospatial search capability.
    """
    print(f"[Evac] Querying zones near lon={lon}, lat={lat}, ts={timestamp}, dist={dist}m")
    bigquery_client = BigQueryClient()
    query = f'''
            SELECT id, date_created, date_modified, geo_json, status, json_value
            FROM `wids-accenture-song.watch_duty.left_join_evac_zones_gis_evaczone_evaczonechangelog_flat_geojson`
            WHERE ST_DISTANCE(geo_json, ST_GEOGPOINT({lon}, {lat})) <= {dist}
              AND (date_created <= TIMESTAMP('{timestamp}') OR date_modified <= TIMESTAMP('{timestamp}'))
              AND (is_active = True OR (json_key = "is_active" AND json_value = "true"))
              AND (status IN ("advisories", "warnings", "orders")
                   OR (json_key = "status" AND json_value IN ("advisories", "warnings", "orders")))
            QUALIFY ROW_NUMBER() OVER (PARTITION BY id ORDER BY date_modified DESC) = 1
            '''
    return bigquery_client.query(query)


def return_evac_record_using_windspeed(lon: float,
                                       lat: float,
                                       windspeed: float=11426.3, # meter/hour
                                       dataset_name: str='watch_duty',
                                       table_name: str='left_join_evac_zones_gis_evaczone_evaczonechangelog_flat_geojson',
                                       geojson_col_name: str='geo_json'
                                       ) -> pd.DataFrame:
    # Return an evac records within the distance that can be 
    # on the evacuation route for a day which is
    # 10% of the windspeed  * 24 hours
    # fire can spread at approximately 10% of the wind speed in severe burning conditions.
    # https://www.battlbox.com/blogs/outdoors/how-far-can-a-wildfire-spread
    # wind_speed default value was set based on LA's average windspeed.
    # https://forecast.weather.gov/product.php?site=ARX&product=CLM&issuedby=LAX
    bigquery_client = BigQueryClient()
    print(math.ceil(windspeed * 0.1 * 24))
    condition = f'ST_DISTANCE(geo_json, ST_GEOGPOINT({lon}, {lat})) <= {math.ceil(windspeed * 0.1 * 24)}'
    return bigquery_client.select_single_table(dataset_name,
                                               table_name,
                                               condition=condition)


def return_evac_record_within_dist(lon: float,
                                   lat: float,
                                   dist: float=1000, # meters
                                   dataset_name: str='watch_duty',
                                   table_name: str='left_join_evac_zones_gis_evaczone_evaczonechangelog_flat_geojson',
                                   geojson_col_name: str='geo_json'
                                   ) -> pd.DataFrame:
    # Return an evac records within the distance (meters)
    bigquery_client = BigQueryClient()
    condition = f'ST_DISTANCE(geo_json, ST_GEOGPOINT({lon}, {lat})) <= {dist}'
    return bigquery_client.select_single_table(dataset_name,
                                               table_name,
                                               condition=condition)
