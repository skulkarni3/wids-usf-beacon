import os
from dotenv import load_dotenv 
from datetime import datetime, date

load_dotenv()
MAP_KEY = os.getenv("NASA_FIRM_API")

def nasa_wildfire_detections(MAP_KEY: str, 
                            SOURCE: str = "VIIRS_NOAA21_NRT", 
                            AREA_COORDINATES: str = "-171.791111, 18.91619, -66.96466, 71.357764", 
                            DAY_RANGE :int = 1,
                            DATE: date = datetime.now().date()):
    """ 
    Parameters:
    - MAP_KEY: str, NASA FIRMS API key
    - SOURCE: str, one of ["VIIRS_NOAA21_NRT", "VIIRS_SNPP_NRT"] (default = VIIRS_NOAA21_NRT)
    - AREA_COORDINATES: str, bounding box "west,south,east,north" (default = US)
    - DAY_RANGE: int, number of days to query (1–10, default=1)
    - DATE: date, YYYY-MM-DD (default = today's date)
    """

    valid_sources = ["VIIRS_NOAA21_NRT", "VIIRS_SNPP_NRT"]

    if SOURCE not in valid_sources:
        raise ValueError(f"SOURCE must be from this list: {valid_sources}")
    
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/{AREA_COORDINATES}/{DAY_RANGE}/{DATE}"

    response = requests.get(url)
    response.raise_for_status() 
    return response.text
