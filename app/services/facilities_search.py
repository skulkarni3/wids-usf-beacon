import requests
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np


def state_to_bbox(state):
    us_state_bbox = {
    "AL": (30.2, -88.5, 35.0, -84.9),
    "AK": (51.2, -179.2, 71.4, -130.0),
    "AZ": (31.3, -114.8, 37.0, -109.0),
    "AR": (33.0, -94.6, 36.5, -89.6),
    "CA": (32.5, -124.5, 42.0, -114.1),
    "CO": (37.0, -109.1, 41.0, -102.0),
    "CT": (41.0, -73.7, 42.1, -71.8),
    "DE": (38.5, -75.8, 39.8, -75.1),
    "FL": (24.5, -87.6, 31.0, -80.0),
    "GA": (30.4, -85.6, 35.0, -80.8),
    "HI": (18.9, -160.3, 22.2, -154.8),
    "ID": (42.0, -117.2, 49.0, -111.0),
    "IL": (37.0, -91.5, 42.5, -87.5),
    "IN": (37.8, -88.1, 41.8, -84.8),
    "IA": (40.4, -96.6, 43.5, -90.1),
    "KS": (37.0, -102.0, 40.0, -94.6),
    "KY": (36.5, -89.6, 39.1, -82.0),
    "LA": (28.9, -94.0, 33.0, -88.8),
    "ME": (43.0, -71.1, 47.5, -67.0),
    "MD": (37.9, -79.5, 39.7, -75.1),
    "MA": (41.2, -73.5, 42.9, -69.9),
    "MI": (41.7, -90.4, 48.3, -82.4),
    "MN": (43.5, -97.2, 49.4, -89.5),
    "MS": (30.2, -91.7, 35.0, -88.1),
    "MO": (36.0, -95.8, 40.6, -89.1),
    "MT": (44.4, -116.0, 49.0, -104.0),
    "NE": (40.0, -104.1, 43.0, -95.3),
    "NV": (35.0, -120.0, 42.0, -114.0),
    "NH": (42.7, -72.6, 45.3, -70.6),
    "NJ": (38.9, -75.6, 41.4, -73.9),
    "NM": (31.3, -109.1, 37.0, -103.0),
    "NY": (40.5, -79.8, 45.0, -71.9),
    "NC": (33.8, -84.3, 36.6, -75.5),
    "ND": (45.9, -104.0, 49.0, -96.6),
    "OH": (38.4, -84.8, 42.0, -80.5),
    "OK": (33.6, -103.0, 37.0, -94.4),
    "OR": (42.0, -124.7, 46.3, -116.5),
    "PA": (39.7, -80.5, 42.3, -74.7),
    "RI": (41.1, -71.9, 42.0, -71.1),
    "SC": (32.0, -83.4, 35.2, -78.5),
    "SD": (42.5, -104.1, 46.0, -96.4),
    "TN": (35.0, -90.3, 36.7, -81.7),
    "TX": (25.8, -106.7, 36.5, -93.5),
    "UT": (37.0, -114.1, 42.0, -109.0),
    "VT": (42.7, -73.4, 45.0, -71.5),
    "VA": (36.5, -83.7, 39.5, -75.2),
    "WA": (45.5, -124.9, 49.0, -116.9),
    "WV": (37.2, -82.6, 40.6, -77.7),
    "WI": (42.5, -92.9, 47.3, -86.2),
    "WY": (41.0, -111.1, 45.0, -104.0),}
    bbox = us_state_bbox[state]
    return bbox

def query_store(bbox):
    OVERPASS_URL = "https://overpass-api.de/api/interpreter"

    query = f"""
        [out:json][timeout:500];
        (
        node["amenity"="pharmacy"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        way["amenity"="pharmacy"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});

        node["healthcare"="pharmacy"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        way["healthcare"="pharmacy"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});

        node["shop"="grocery"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        way["shop"="grocery"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});

        node["shop"="convenience"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        way["shop"="convenience"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});

        node["shop"="supermarket"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        way["shop"="supermarket"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});

        node["shop"="health_food"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        way["shop"="health_food"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});

        node["shop"="hypermarket"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        way["shop"="hypermarket"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        );
        out center;
    """
    response = requests.post(
        OVERPASS_URL,
        data={"data": query},
        timeout=500
    )
    response.raise_for_status()
    data = response.json()
    if len(data["elements"]) > 0:
        return data
    else:
        print("Timeout Error")

def classify_store(tags):
    if tags.get("amenity") == "pharmacy":
        return "pharmacy"
    if tags.get("healthcare") == "pharmacy":
        return "pharmacy"
    if tags.get("shop") == "grocery":
        return "supermarket"
    if tags.get("shop") == "supermarket":
        return "supermarket"
    if tags.get("shop") == "health_food":
        return "supermarket"
    if tags.get("shop") == "hypermarket":
        return "supercenter"
    if tags.get("shop") == "convenience":
        return "convenience_store"
    return "other"

def facs_to_df(data, type):
    rows = []
    for el in data["elements"]:
        if el["type"] == "node":
            lat, lon = el["lat"], el["lon"]
        elif "center" in el:
            lat, lon = el["center"]["lat"], el["center"]["lon"]
        else:
            continue
        if type == "STORE":
            facility_type = classify_store(el.get("tags", {}))
        elif type == "SHELTER":
            facility_type = classify_shelter(el.get("tags", {}))
        rows.append({
            "id": el["id"],
            "lat": lat,
            "lng": lon,
            "facility_type": facility_type,
            "name": el.get("tags", {}).get("name"),
            "original": el
        })
    df = pd.DataFrame(rows) 
    return df 


def query_shelter(bbox):
    OVERPASS_URL = "https://overpass-api.de/api/interpreter"

    query = f"""
        [out:json][timeout:500];
        (
        node["landuse"="fairground"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        way["landuse"="fairground"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});

        node["amenity"="school"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        way["amenity"="school"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});

        node["building"="school"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        way["building"="school"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});

        node["education"="school"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        way["education"="school"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});

        node["landuse"="school"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        way["landuse"="school"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});

        node["amenity"="community_centre"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        way["amenity"="community_centre"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});

        node["amenity"="hotel"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        way["amenity"="hotel"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});

        node["tourism"="hotel"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        way["tourism"="hotel"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});

        node["tourism"="motel"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        way["tourism"="motel"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
        );
        out center;
    """
    response = requests.post(
        OVERPASS_URL,
        data={"data": query},
        timeout=500
    )
    response.raise_for_status()
    data = response.json()
    if len(data["elements"]) > 0:
        return data
    else:
        print("Error")

def classify_shelter(tags):
    if tags.get("landuse") == "fairground":
        return "temp_shelter"
    if tags.get("amenity") == "school":
        return "temp_shelter"
    if tags.get("building") == "school":
        return "temp_shelter"
    if tags.get("education") == "school":
        return "temp_shelter"
    if tags.get("landuse") == "school":
        return "temp_shelter"
    if tags.get("amenity") == "community_centre":
        return "temp_shelter"
    if tags.get("amenity") == "hotel":
        return "lodging"
    if tags.get("tourism") == "hotel":
        return "lodging"
    if tags.get("tourism") == "motel":
        return "lodging"
    if tags.get("amenity") == "pharmacy":
        return "pharmacy"
    if tags.get("healthcare") == "pharmacy":
        return "pharmacy"
    if tags.get("shop") == "grocery":
        return "supermarket"
    if tags.get("shop") == "supermarket":
        return "supermarket"
    if tags.get("shop") == "health_food":
        return "supermarket"
    if tags.get("shop") == "hypermarket":
        return "supercenter"
    if tags.get("shop") == "convenience":
        return "convenience_store"
    return "other"


def return_facs_by_state(state: str="CO",
                         type: str="SHETLER") -> pd.DataFrame:
    """
    Takes the state abbreviation in upper case, 
    and return all the facilities.
    type : "STORE", "SHETLER"
    """
    bbox = state_to_bbox(state)
    if type == "STORE":
        data = query_store(bbox)
    elif type == "SHELTER":
        data = query_shelter(bbox)
    return facs_to_df(data, type)
