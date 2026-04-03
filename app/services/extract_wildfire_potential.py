"""
extract_wildfire_potential.py
=======================
Extracts hourly HWP values for all HRRR grid points within the Colorado
bounding box and writes them to a CSV with columns:

    datetime_utc | latitude | longitude | hwp

Date range : 2025-07-10 00:00 UTC  →  2025-09-18 23:00 UTC
             (~1,800 hourly analysis files)

Output     : hwp_colorado_20250710_20250918.csv

Design notes
------------
- Imports fetch_hwp_grid() and helpers from hwp_api.py (must be in same dir).
- Grid is fetched once per hour; lat/lon arrays are constant so they are
  extracted on the first fetch and reused.
- Colorado mask is computed once from the first grid and reused.
- Rows are written incrementally (one hour at a time) so a crash mid-run
  does not lose completed hours.
- Resume support: if the output CSV already exists, hours already written
  are skipped automatically.
- Failed hours are logged to  hwp_colorado_errors.log  and skipped so one
  bad HRRR file does not abort the entire run.

Estimated runtime
-----------------
Each hour requires ~5 GRIB subset downloads (~1–3 MB each) + smoothing.
Allow ~2–4 minutes per hour on a typical broadband connection, so the
full run may take 60–120 hours.  Run inside a tmux / screen session or
use nohup:

    nohup python extract_wildfire_potential.py &> run.log &
"""

import csv
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np

from widlfire_potential import fetch_hwp_grid, _nearest_grid_point   # noqa: F401

# ════════════════════════════════════════════════════════════════════════════
#  SETTINGS
# ════════════════════════════════════════════════════════════════════════════
START_DT = datetime(2025, 7, 10,  0, tzinfo=timezone.utc)
END_DT   = datetime(2025, 9, 18, 23, tzinfo=timezone.utc)

# Colorado bounding box (degrees)
CO_LON_MIN, CO_LON_MAX = -109.1, -102.0
CO_LAT_MIN, CO_LAT_MAX =   37.0,   41.0

OUTPUT_CSV  = Path("hwp_colorado_20250710_20250918.csv")
ERROR_LOG   = Path("hwp_colorado_errors.log")

CSV_COLUMNS = ["datetime_utc", "latitude", "longitude", "hwp"]
# ════════════════════════════════════════════════════════════════════════════


# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(ERROR_LOG, mode="a"),
    ],
)
log = logging.getLogger(__name__)


def _all_hours(start: datetime, end: datetime):
    """Yield every UTC hour from start to end inclusive."""
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(hours=1)


def _already_done_hours(csv_path: Path) -> set[datetime]:
    """
    Read the existing CSV (if any) and return the set of UTC datetimes
    already written so we can skip them on resume.
    """
    done = set()
    if not csv_path.exists():
        return done
    with csv_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                dt = datetime.fromisoformat(row["datetime_utc"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                done.add(dt)
            except (KeyError, ValueError):
                pass
    return done


def main():
    total_hours = int((END_DT - START_DT).total_seconds() / 3600) + 1
    log.info(f"Colorado HWP extraction: {START_DT.date()} → {END_DT.date()}  "
             f"({total_hours} hours)")
    log.info(f"Bounding box: lon [{CO_LON_MIN}, {CO_LON_MAX}]  "
             f"lat [{CO_LAT_MIN}, {CO_LAT_MAX}]")
    log.info(f"Output → {OUTPUT_CSV}")

    # ── Resume: find already-completed hours ─────────────────────────────────
    done_hours = _already_done_hours(OUTPUT_CSV)
    if done_hours:
        log.info(f"Resuming: {len(done_hours)} hours already in CSV, skipping.")

    # ── Open CSV (append mode so resume works) ───────────────────────────────
    write_header = not OUTPUT_CSV.exists() or OUTPUT_CSV.stat().st_size == 0
    csv_file = OUTPUT_CSV.open("a", newline="")
    writer   = csv.writer(csv_file)
    if write_header:
        writer.writerow(CSV_COLUMNS)
        csv_file.flush()

    # ── Cache: lat/lon grid + Colorado mask (set on first successful fetch) ───
    co_lat_flat = None
    co_lon_flat = None
    co_row_idx  = None   # flat indices into the 2-D grid for CO points
    co_col_idx  = None

    # ── Main loop ─────────────────────────────────────────────────────────────
    completed = 0
    skipped   = 0
    errors    = 0

    for hour_num, dt in enumerate(_all_hours(START_DT, END_DT), start=1):
        # Skip hours already written
        if dt in done_hours:
            skipped += 1
            continue

        dt_str = dt.strftime("%Y-%m-%d %H:%M:%S+00:00")
        log.info(f"[{hour_num}/{total_hours}] {dt_str}")

        try:
            grid = fetch_hwp_grid(dt)

            # Build Colorado mask once from first grid
            if co_row_idx is None:
                lat2d = grid.lat
                lon2d = grid.lon
                mask  = (
                    (lat2d >= CO_LAT_MIN) & (lat2d <= CO_LAT_MAX) &
                    (lon2d >= CO_LON_MIN) & (lon2d <= CO_LON_MAX)
                )
                co_row_idx, co_col_idx = np.where(mask)
                co_lat_flat = lat2d[co_row_idx, co_col_idx]
                co_lon_flat = lon2d[co_row_idx, co_col_idx]
                n_points    = co_row_idx.size
                log.info(f"  Colorado grid points: {n_points:,}")

            # Extract HWP values for Colorado points
            hwp_vals = grid.hwp[co_row_idx, co_col_idx]

            # Write rows for this hour
            for i in range(co_row_idx.size):
                writer.writerow([
                    dt_str,
                    f"{co_lat_flat[i]:.5f}",
                    f"{co_lon_flat[i]:.5f}",
                    f"{hwp_vals[i]:.6f}" if np.isfinite(hwp_vals[i]) else "",
                ])
            csv_file.flush()   # ensure data is on disk after each hour
            completed += 1

        except Exception as exc:
            log.error(f"  FAILED {dt_str}: {exc}")
            errors += 1
            continue

    csv_file.close()

    log.info("=" * 60)
    log.info(f"Done.  Completed: {completed}  Skipped: {skipped}  Errors: {errors}")
    log.info(f"Output: {OUTPUT_CSV}  ({OUTPUT_CSV.stat().st_size / 1e6:.1f} MB)")
    if errors:
        log.info(f"Failed hours logged to: {ERROR_LOG}")


if __name__ == "__main__":
    main()