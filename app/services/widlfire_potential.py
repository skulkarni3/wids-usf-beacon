"""
wildfire_potential.py  —  Hourly Wildfire Potential (HWP) data pipeline
=============================================================
Provides clean, composable functions to:

  1. fetch_hwp_grid(dt)
        Fetch all required HRRR fields for a given UTC datetime,
        compute raw HWP over the full CONUS grid, apply 9×9 (~27 km)
        spatial smoothing, and return a HWPGrid named-tuple.

  2. get_hwp_at_point(lat, lon, dt=None)
        Return the smoothed HWP value at a single lat/lon.
        If dt is None, uses the most recent available UTC analysis hour.

  3. get_latest_utc_hour()
        Return the most recent UTC hour for which HRRR data is likely
        available (current UTC time rounded down to the hour, minus a
        1-hour lag buffer for ingestion delay).

HWP formula:
    HWP = 0.213 × G^1.50 × VPD^0.73 × (1 − M)^5.10 × S

    G    = surface wind gust [m/s], lower-bounded at 3 m/s
    VPD  = 2-m vapor pressure deficit [hPa]
    M    = soil moisture availability [fraction 0–1]  (MSTAV/100)
    S    = snow suppression term = exp(−WEASD/10)

source: https://journals.ametsoc.org/view/journals/wefo/40/9/WAF-D-24-0068.1.pdf (see paper for detailed discussion of physical rationale and parameter choices)

Spatial smoothing:
    HRRR native resolution ≈ 3 km.  A 9×9 uniform-box filter averages
    each grid point over a ~27 km × 27 km neighbourhood, matching the
    spatial averaging window described in the paper.

Usage example
-------------
    from hwp_api import get_hwp_at_point, get_latest_utc_hour

    # Latest available hour
    hwp = get_hwp_at_point(lat=34.05, lon=-118.25)   # Los Angeles
    print(f"HWP = {hwp:.3f}")

    # Specific historical datetime
    from datetime import datetime, timezone
    dt  = datetime(2024, 9, 7, 18, tzinfo=timezone.utc)
    hwp = get_hwp_at_point(lat=37.77, lon=-122.42, dt=dt)  # San Francisco
    print(f"HWP = {hwp:.3f}")
"""

from __future__ import annotations

from collections import namedtuple
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np
from scipy.ndimage import uniform_filter
import warnings

import cfgrib
from herbie import Herbie

from .bigquery import *

warnings.filterwarnings("ignore")

# ── Named tuple returned by fetch_hwp_grid ────────────────────────────────────
HWPGrid = namedtuple("HWPGrid", [
    "hwp",      # 2-D ndarray, smoothed HWP values (full CONUS grid)
    "lat",      # 2-D ndarray, latitude  of each grid point
    "lon",      # 2-D ndarray, longitude of each grid point (–180 to 180)
    "valid_dt",  # datetime (UTC) this grid is valid for
])


# ═══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _fetch_field(H: Herbie, search: str) -> np.ndarray:
    """
    Download one HRRR GRIB variable via Herbie and return its data as a
    2-D numpy array.  H.download() is called first so cfgrib always reads
    from a stable local file path.
    """
    local_path = H.download(search)
    datasets = cfgrib.open_datasets(str(local_path))
    if not datasets:
        raise RuntimeError(
            f"cfgrib found no datasets for search pattern: {search!r}")
    ds = datasets[0]
    var = list(ds.data_vars)[0]
    return ds[var]


def _sat_vp(T_K: np.ndarray) -> np.ndarray:
    """Saturation vapour pressure [hPa] — August-Roche-Magnus approximation."""
    T_C = T_K - 273.15
    return 6.1078 * np.exp(17.2694 * T_C / (T_C + 237.29))


def _compute_vpd(T_K: np.ndarray, Td_K: np.ndarray) -> np.ndarray:
    """2-m Vapour Pressure Deficit [hPa]; physically non-negative."""
    return np.maximum(_sat_vp(T_K) - _sat_vp(Td_K), 0.0)


def _compute_hwp_raw(G: np.ndarray,
                     VPD: np.ndarray,
                     M_pct: np.ndarray,
                     WEASD: np.ndarray) -> np.ndarray:
    """
    Raw (unsmoothed) HWP 

    Parameters
    ----------
    G      : surface wind gust [m/s]
    VPD    : 2-m vapour pressure deficit [hPa]
    M_pct  : soil moisture availability [%]  (MSTAV, 0–100)
    WEASD  : snow water equivalent [kg/m²]
    """
    G_c = np.maximum(G, 3.0)                        # lower bound 3 m/s
    M = np.clip(M_pct / 100.0, 0.0, 1.0)          # % → unitless fraction
    S = np.exp(-WEASD / 10.0)                     # snow suppression (1 = bare)
    return (0.213
            * np.power(G_c,                  1.50)
            * np.power(np.maximum(VPD, 1e-6), 0.73)
            * np.power(1.0 - M,              5.10)
            * S)


def _smooth_9x9(arr: np.ndarray) -> np.ndarray:
    """
    Apply a 9×9 uniform box filter (~27 km × 27 km at 3 km HRRR resolution).
    NaN values are handled by normalising with a weight array so that coastal
    / border NaNs do not bleed into valid land points.
    """
    nan_mask = np.isnan(arr)
    filled = np.where(nan_mask, 0.0, arr)
    weights = np.where(nan_mask, 0.0, 1.0)

    smooth_sum = uniform_filter(filled,  size=9, mode="nearest")
    smooth_wt = uniform_filter(weights, size=9, mode="nearest")

    with np.errstate(invalid="ignore", divide="ignore"):
        result = np.where(smooth_wt > 0, smooth_sum / smooth_wt, np.nan)

    return result


def _nearest_grid_point(lat_grid: np.ndarray,
                        lon_grid: np.ndarray,
                        query_lat: float,
                        query_lon: float) -> tuple[int, int]:
    """
    Return (row, col) indices of the grid point nearest to (query_lat, query_lon).
    Uses simple Euclidean distance in lat/lon space — accurate enough for
    point lookups at the HRRR ~3 km scale.
    """
    dist = (lat_grid - query_lat) ** 2 + (lon_grid - query_lon) ** 2
    idx = np.unravel_index(np.argmin(dist), dist.shape)
    return idx


# ═══════════════════════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════════════════════

def get_latest_utc_hour() -> datetime:
    """
    Return the most recent UTC hour for which HRRR analysis data is likely
    available.

    HRRR analysis (F00) files are typically available ~45–90 min after the
    cycle time.  We apply a conservative 1-hour lag buffer so that callers
    do not request a cycle that hasn't been ingested yet.

    Returns
    -------
    datetime (UTC, tzinfo=timezone.utc) truncated to the hour.
    """
    now_utc = datetime.now(tz=timezone.utc)
    lag = timedelta(hours=1)                    # ingestion lag buffer
    adjusted = now_utc - lag
    # Truncate to the hour
    latest = adjusted.replace(minute=0, second=0, microsecond=0)
    return latest


def fetch_hwp_grid(dt: datetime) -> HWPGrid:
    """
    Fetch all required HRRR fields for a given UTC datetime, compute HWP,
    apply 9×9 (~27 km) spatial smoothing, and return a HWPGrid.

    Parameters
    ----------
    dt : datetime
        Target UTC datetime.  If naive (no tzinfo), assumed UTC.
        Minutes/seconds are ignored — the cycle hour is used.

    Returns
    -------
    HWPGrid named-tuple with fields:
        .hwp       — smoothed HWP array  (HRRR native grid shape)
        .lat       — latitude array
        .lon       — longitude array (–180 to 180)
        .valid_dt  — UTC datetime this grid is valid for
    """
    # Normalise to UTC, truncate to hour
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_hour = dt.replace(minute=0, second=0, microsecond=0)

    date_str = dt_hour.strftime("%Y-%m-%d %H:%M")
    print(f"[fetch_hwp_grid] Fetching HRRR analysis for {date_str} UTC …")

    H = Herbie(date_str, model="hrrr", product="sfc", fxx=0)

    print("  → GUST:surface")
    gust_da = _fetch_field(H, ":GUST:surface:")

    print("  → TMP:2 m above ground")
    tmp_da = _fetch_field(H, ":TMP:2 m above ground:")

    print("  → DPT:2 m above ground")
    dpt_da = _fetch_field(H, ":DPT:2 m above ground:")

    print("  → MSTAV:0 m underground")
    mstav_da = _fetch_field(H, ":MSTAV:0 m underground:")

    print("  → WEASD:surface (analysis)")
    weasd_da = _fetch_field(H, ":WEASD:surface:0")

    # Extract lat/lon — normalise to –180/180
    lat = gust_da.coords["latitude"].values
    lon = gust_da.coords["longitude"].values
    if lon.max() > 180:
        lon = lon - 360.0

    # Compute intermediate fields
    VPD = _compute_vpd(tmp_da.values, dpt_da.values)
    HWP = _compute_hwp_raw(
        G=gust_da.values,
        VPD=VPD,
        M_pct=mstav_da.values,
        WEASD=weasd_da.values,
    )

    # Spatial smoothing: 9×9 box (~27 km × 27 km)
    print("  → Applying 9×9 spatial smoothing (~27 km) …")
    HWP_smooth = _smooth_9x9(HWP)

    print(f"  ✓ Done.  Grid shape: {HWP_smooth.shape}  "
          f"HWP range: [{np.nanmin(HWP_smooth):.3f}, {np.nanmax(HWP_smooth):.3f}]")

    return HWPGrid(hwp=HWP_smooth, lat=lat, lon=lon, valid_dt=dt_hour)


def get_hwp_at_point(lat: float,
                     lon: float,
                     dt: datetime | None = None) -> float:
    """
    Return the smoothed HWP value at a single geographic point.

    Parameters
    ----------
    lat : float
        Latitude in decimal degrees (positive = North).
    lon : float
        Longitude in decimal degrees (negative = West, e.g. –118.25 for LA).
    dt  : datetime or None
        UTC datetime to query.  If None, uses get_latest_utc_hour() to
        automatically find the most recent available analysis hour.

    Returns
    -------
    float
        Smoothed HWP value at the nearest HRRR grid point.

    Examples
    --------
    >>> hwp = get_hwp_at_point(34.05, -118.25)           # LA, latest hour
    >>> hwp = get_hwp_at_point(37.77, -122.42, dt=...)   # SF, specific time
    """
    if dt is None:
        dt = get_latest_utc_hour()
        print(f"[get_hwp_at_point] No datetime given — using latest UTC hour: "
              f"{dt.strftime('%Y-%m-%d %H:00 UTC')}")

    grid = fetch_hwp_grid(dt)

    row, col = _nearest_grid_point(grid.lat, grid.lon, lat, lon)
    hwp_val = float(grid.hwp[row, col])

    grid_lat = float(grid.lat[row, col])
    grid_lon = float(grid.lon[row, col])
    print(f"[get_hwp_at_point] Query ({lat:.4f}, {lon:.4f})  →  "
          f"nearest grid point ({grid_lat:.4f}, {grid_lon:.4f})  →  "
          f"HWP = {hwp_val:.4f}")

    return hwp_val

HWP_DATASET = "watch_duty"
HWP_TABLE   = "hwp_colorado"

CO_LAT_MIN, CO_LAT_MAX = 37.0,   41.0
CO_LON_MIN, CO_LON_MAX = -109.1, -102.0


def store_hwp_to_bigquery(dt: datetime | None = None) -> dict:
    """
    Fetch the HRRR HWP grid for *dt* (defaults to latest available hour),
    mask to Colorado, and stream into hwp_co.hwp_colorado.

    Parameters
    ----------
    dt : datetime or None
        UTC hour to fetch. If None, uses get_latest_utc_hour().

    Returns
    -------
    dict  { "rows_inserted": int, "valid_dt": str, "errors": list }
    """
    if dt is None:
        dt = get_latest_utc_hour()

    grid = fetch_hwp_grid(dt)   # already defined in wildfire_potential.py

    # Mask full CONUS grid down to Colorado
    co_mask            = (
        (grid.lat >= CO_LAT_MIN) & (grid.lat <= CO_LAT_MAX) &
        (grid.lon >= CO_LON_MIN) & (grid.lon <= CO_LON_MAX)
    )
    rows_idx, cols_idx = np.where(co_mask)
    dt_str             = grid.valid_dt.strftime("%Y-%m-%d %H:%M:%S") + " UTC"

    rows = [
        {
            "datetime_utc": dt_str,
            "latitude":     round(float(grid.lat[r, c]), 5),
            "longitude":    round(float(grid.lon[r, c]), 5),
            "hwp":          float(grid.hwp[r, c]) if np.isfinite(grid.hwp[r, c]) else None,
        }
        for r, c in zip(rows_idx, cols_idx)
    ]

    bq     = BigQueryClient()
    errors = bq.insert_rows(HWP_DATASET, HWP_TABLE, rows)

    return {
        "rows_inserted": len(rows) - len(errors),
        "valid_dt":      dt_str,
        "errors":        errors,
    }



# ═══════════════════════════════════════════════════════════════════════════════
#  Quick self-test  (python hwp_api.py)
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # Example: Los Angeles at the latest available HRRR hour
    print("=" * 60)
    print("hwp_api.py  —  quick self-test")
    print("=" * 60)

    latest = get_latest_utc_hour()
    print(
        f"\nLatest available UTC hour: {latest.strftime('%Y-%m-%d %H:00 UTC')}\n")

    # Point lookups
    locations = {
        "Los Angeles, CA": (34.05, -118.25),
        "San Francisco, CA": (37.77, -122.42),
        "Sacramento, CA": (38.58, -121.49),
        "San Diego, CA": (32.72, -117.16),
    }

    # Fetch grid once, reuse for all point lookups
    grid = fetch_hwp_grid(latest)
    print()
    print(f"{'Location':<25} {'Lat':>7} {'Lon':>9}   {'HWP':>8}")
    print("-" * 55)
    for name, (qlat, qlon) in locations.items():
        r, c = _nearest_grid_point(grid.lat, grid.lon, qlat, qlon)
        val = grid.hwp[r, c]
        print(f"{name:<25} {qlat:>7.2f} {qlon:>9.2f}   {val:>8.4f}")

def return_hwp_records(lon: float,
                       lat: float,
                       datetime: datetime, 
                       dataset_name: str='watch_duty',
                       table_name: str='hwp_colorado'
                       ) -> pd.DataFrame:
    """
    Takes the lon, lat and timestamp and 
    looks up bigquery table_name to
    return the datetime_utc and hwp (hourly wildfire potential).
    Exmple call : return_hwp_records(39.7392, -104.9903, '2025-08-15 18:00:00 UTC')
    """
    bigquery_client = BigQueryClient()
    sql_query = f"""
    WITH nearest AS (
        SELECT latitude, longitude
        FROM {dataset_name}.{table_name}
        WHERE datetime_utc > TIMESTAMP('{datetime}') AND datetime_utc <= TIMESTAMP_ADD(TIMESTAMP('{datetime}'), INTERVAL 1 HOUR)
        ORDER BY SQRT(POW(latitude - {lat}, 2) + POW(longitude - {lon}, 2)) ASC
        LIMIT 1
    )
    SELECT h.datetime_utc, h.hwp
    FROM {dataset_name}.{table_name} h
    JOIN nearest n ON h.latitude = n.latitude AND h.longitude = n.longitude
    ORDER BY h.datetime_utc; """
    return bigquery_client.query(sql_query)