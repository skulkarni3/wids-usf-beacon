# HWP Colorado — BigQuery Dataset

Hourly Wildfire Potential for Colorado, July 10 – September 18 2025, derived from HRRR.

## Schema

| Column | Type | Description |
|--------|------|-------------|
| `datetime_utc` | TIMESTAMP | Analysis hour (UTC) |
| `latitude` | FLOAT64 | 37.0 – 41.0 °N |
| `longitude` | FLOAT64 | −109.1 – −102.0 °W |
| `hwp` | FLOAT64 | Smoothed wildfire potential (raw value, higher = more dangerous) |

## HWP Formula

```
HWP = 0.213 × G^1.50 × VPD^0.73 × (1 − M)^5.10 × S
```

- **G** — wind gust [m/s], min 3 m/s
- **VPD** — vapour pressure deficit [hPa] from 2-m temp + dew point
- **M** — soil moisture fraction (MSTAV ÷ 100)
- **S** — snow suppression `exp(−WEASD/10)`, 1 = no snow

Each value is averaged over a 9×9 box (~27 km × 27 km) before storage.

## Querying a Point

The grid is ~3 km resolution. To get HWP for any lat/lon, find the **nearest grid point** and return its value.

```sql
-- HWP at Denver (39.7392, -104.9903) on 2025-08-15 18:00 UTC
SELECT
    latitude, longitude, hwp
FROM
    `YOUR_PROJECT.YOUR_DATASET.hwp_colorado`
WHERE
    datetime_utc = TIMESTAMP('2025-08-15 18:00:00 UTC')
ORDER BY
    SQRT(POW(latitude - 39.7392, 2) + POW(longitude - (-104.9903), 2)) ASC
LIMIT 1;
```

### Time series for one location

```sql
WITH nearest AS (
    SELECT latitude, longitude
    FROM `YOUR_PROJECT.YOUR_DATASET.hwp_colorado`
    WHERE datetime_utc = TIMESTAMP('2025-07-10 00:00:00 UTC')
    ORDER BY SQRT(POW(latitude - 39.7392, 2) + POW(longitude - (-104.9903), 2)) ASC
    LIMIT 1
)
SELECT h.datetime_utc, h.hwp
FROM `YOUR_PROJECT.YOUR_DATASET.hwp_colorado` h
JOIN nearest n ON h.latitude = n.latitude AND h.longitude = n.longitude
ORDER BY h.datetime_utc;
```

## BigQuery Setup

```bash
bq load --source_format=CSV --skip_leading_rows=1 --autodetect \
  YOUR_PROJECT:YOUR_DATASET.hwp_colorado \
  hwp_colorado_20250710_20250918.csv
```

Partition on `DATE(datetime_utc)` to keep query costs low.