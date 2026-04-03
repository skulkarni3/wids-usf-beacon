# inputs/location.py — Resolves lat/lon to a human-readable location via Nominatim

import requests


def get_address_from_lat_lon(lat: float, lon: float) -> dict:
    """
    Takes GPS coordinates from the mobile app and reverse-geocodes them
    using Nominatim (OpenStreetMap). No API key required.
    Falls back to raw coordinates if geocoding fails.
    """
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json"},
            headers={"User-Agent": "WildFireExitsApp/1.0"},
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        address = data.get("address", {})
        city = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("hamlet")
            or address.get("suburb")
            or address.get("county")
            or address.get("municipality")
            or "Unknown"
        )
        state = address.get("state", "")
        display = f"{city}, {state}" if state else city
    except Exception:
        city, state = "Unknown", ""
        display = f"{lat:.4f}, {lon:.4f}"

    return {
        "lat": lat,
        "lon": lon,
        "city": city,
        "state": state,
        "display": display
    }