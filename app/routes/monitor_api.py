# Routes in this file should be called regularly to trigger mobile app's push notification.
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks

from ..services import check_evac
from ..services import widlfire_potential
from ..services import fcm
from ..services.bigquery import BigQueryClient

router = APIRouter()


def _get_device_info(user_id: str) -> tuple[Optional[str], str]:
    """Fetch the FCM device token and language for a user from BigQuery.
    Returns (device_token, language), where language defaults to 'en'."""
    bq = BigQueryClient()
    df = bq.select_single_table(
        "watch_duty",
        "device_tokens",
        ["device_token", "language"],
        condition=f"user_id = '{user_id}'",
        num=1,
    )
    if df.empty:
        return None, "en"
    row = df.iloc[0]
    language = row.get("language") or "en"
    return row["device_token"], language


def _write_device_token(user_id: str, device_token: str, platform: str, language: str = "en") -> None:
    """BigQuery MERGE — runs in the background so the endpoint returns immediately.
    Requires the device_tokens table to have a STRING 'language' column."""
    from google.cloud import bigquery as bq_lib
    bq = BigQueryClient()
    now = datetime.now(timezone.utc).isoformat()
    sql = f"""
        MERGE `{bq.project}.watch_duty.device_tokens` T
        USING (SELECT @user_id AS user_id) S
        ON T.user_id = S.user_id
        WHEN MATCHED THEN
            UPDATE SET device_token = @device_token, platform = @platform,
                       language = @language, updated_at = @updated_at
        WHEN NOT MATCHED THEN
            INSERT (user_id, device_token, platform, language, updated_at)
            VALUES (@user_id, @device_token, @platform, @language, @updated_at)
    """
    bq.query(sql, params=[
        bq_lib.ScalarQueryParameter("user_id", "STRING", user_id),
        bq_lib.ScalarQueryParameter("device_token", "STRING", device_token),
        bq_lib.ScalarQueryParameter("platform", "STRING", platform),
        bq_lib.ScalarQueryParameter("language", "STRING", language),
        bq_lib.ScalarQueryParameter("updated_at", "STRING", now),
    ])


@router.post("/monitor/register_fcm_token")
def register_device_token(background_tasks: BackgroundTasks,
                          user_id: str,
                          device_token: str,
                          platform: str = "ios",
                          language: str = "en"):
    """Register or update a user's FCM device token and language preference.
    Returns immediately; DB write runs in the background."""
    background_tasks.add_task(_write_device_token, user_id, device_token, platform, language)
    return {"status": "ok"}


@router.get("/monitor/evac")
def monitor_evac_status(lat: float, lon: float, timestamp: datetime, user_id: str = None):
    # Using the user's lon, lat, return its evac zone status
    df = check_evac.return_evac_records(lon, lat, timestamp)
    records = df.to_dict(orient="records")
    alert_type = records[0]["status"] if records[0]["status"] else records[0]["json_value"]
   
    if records and user_id:
        token, language = _get_device_info(user_id)
        if token:
            fcm.send_evac_alert(token, alert_type.upper(), language=language)

    return records


# @router.get("/monitor/fire")
# def monitor_fire_dist(lon: float, lat: float, timestamp: datetime):
#     # Using the user's lon, lat, return the distance from the fire
#     # TODO : Would this be necessary
#     # given that we'd have houlry wildfire potentials(HWP)


@router.get("/monitor/hwp")
def monitor_hwp(lat: float, lon: float, timestamp: datetime,
                hwp_threshold: float = 50, user_id: str = None):
    # Using the user's lon, lat, return the HWP
    df = widlfire_potential.return_hwp_records(lon, lat, timestamp)
    records = df.to_dict(orient="records")

    if records and user_id:
        hwp_value = records[0].get("hwp", 0) if records else 0
        if hwp_value > hwp_threshold:
            token, language = _get_device_info(user_id)
            if token:
                fcm.send_fire_danger_alert(token, language=language)

    return records