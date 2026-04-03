# THIS FILE MIGHT BE NOT NECESSARY - OLD DATA
import json

import geopandas as gpd
from pathlib import Path
import pandas as pd 
from shapely import wkt

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data" /"watch-duty-data"

def parse_fire_data(data_str):
    """Helper function: Extracts metrics from JSON data field in geo_events."""

    if pd.isna(data_str):
        return {}
    try:
        data = json.loads(data_str) if isinstance(data_str, str) else data_str
        return {
            'acreage': data.get('acreage', None),
            'containment': data.get('containment', None),
            'is_fps': data.get('is_fps', False),  # Fire Perimeter System
            'is_prescribed': data.get('is_prescribed', False)
        }
    except:
        return {}

def get_wildfires():

    # Load data and filter out redundant columns
    columns = ['id', 'date_created', 'date_modified', 'geo_event_type', 'name', 'is_active', 'address', 'lat', 'lng', 'data', 'notification_type', 'external_id', 
    'external_source', 'reporter_managed', 'is_visible']

    geo_events = pd.read_csv(DATA_DIR / "geo_events_geoevent.csv", low_memory=False)
    geo_events = geo_events[columns]

    fire_metrics = geo_events['data'].apply(parse_fire_data)
    geo_events['acreage'] = fire_metrics.apply(lambda x: x.get('acreage', None))
    geo_events['containment'] = fire_metrics.apply(lambda x: x.get('containment', None))
    geo_events['is_fps'] = fire_metrics.apply(lambda x: x.get('is_fps', False))
    geo_events['is_prescribed'] = fire_metrics.apply(lambda x: x.get('is_prescribed', False))


    # Create copy of wildfires 
    wildfires = geo_events[
    (geo_events['geo_event_type'] == 'wildfire') & 
    (geo_events['is_active'] == True) &
    (geo_events['is_prescribed'] == False)].copy()

    return wildfires

def load_perimeters_zones_csv(data_dir):
    df = pd.read_csv(data_dir, low_memory=False)
    
    # Convert date columns
    if 'date_created' in df.columns:
        df['date_created'] = pd.to_datetime(df['date_created'])
    if 'date_modified' in df.columns:
        df['date_modified'] = pd.to_datetime(df['date_modified'])
    
    return df

def parse_wkt_geometry(wkt_string):
    """
    Parse WKT geometry string to Shapely geometry object.
    
    Parameters:
    -----------
    wkt_string : str
        WKT geometry string (may include SRID prefix)
        
    Returns:
    --------
    shapely.geometry object or None
    """
    if pd.isna(wkt_string) or not wkt_string:
        return None
    
    try:
        # Remove SRID prefix if present
        if 'SRID=' in str(wkt_string):
            geom_part = str(wkt_string).split(';', 1)[1].strip()
        else:
            geom_part = str(wkt_string)
        
        return wkt.loads(geom_part)
    except Exception as e:
        print(f"Error parsing geometry: {e}")
        return None

def convert_to_gdf(df):
    """
    Convert fire perimeters dataframe to GeoDataFrame.
    """
    # Parse geometries
    geometries = df['geom'].apply(parse_wkt_geometry)
    
    # Create GeoDataFrame
    gdf = gpd.GeoDataFrame(
        df.drop('geom', axis=1),
        geometry=geometries,
        crs='EPSG:4326'
    )
    
    # Remove rows with invalid geometries
    gdf = gdf[gdf.geometry.notna()].copy()
    
    return gdf
