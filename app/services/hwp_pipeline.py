import time
from datetime import datetime
from google.cloud import bigquery
from .bigquery import BigQueryClient

def run_ml_scheduler_update(sim_start: datetime = None):
    """
    Runs the ML.PREDICT pipeline to update all users' next_refresh_utc.
    If sim_start is provided, it acts as a backtesting simulator.
    If sim_start is None, it acts as the production script using CURRENT_TIMESTAMP().
    """
    # Assuming your BigQueryClient has the project property available,
    # otherwise initialize a standard client: client = bigquery.Client()
    bq = BigQueryClient() 
    client = bigquery.Client(project=bq.project) 

    dataset = "watch_duty" # Adjust to match your dataset
    STATE_TABLE = f"{bq.project}.{dataset}.user_app_state"
    MODEL_ID = f"{bq.project}.{dataset}.hwp_refresh_model"
    FEATURE_VIEW = f"{bq.project}.{dataset}.v_hwp_features"

    # Decide if we are time-traveling (simulation) or running in real-time (production)
    if sim_start:
        current_time_sql = f"TIMESTAMP('{sim_start.isoformat()}')"
        print(f"Running SIMULATED pipeline for {sim_start.isoformat()}...")
    else:
        current_time_sql = "CURRENT_TIMESTAMP()"
        print("Running PRODUCTION real-time pipeline...")

    query = f"""
    UPDATE `{STATE_TABLE}` us
    SET 
        us.latest_hwp = new_data.hwp,
        us.last_refreshed_utc = {current_time_sql},
        us.next_refresh_utc = TIMESTAMP_ADD({current_time_sql}, INTERVAL new_data.hours_until_next_refresh HOUR)
    FROM (
        SELECT 
            p.latitude, p.longitude, p.hwp,
            CASE 
                WHEN p.predicted_target_class = 'Extreme' THEN 1
                WHEN p.predicted_target_class = 'High' THEN 1
                WHEN p.predicted_target_class = 'Elevated' THEN 1
                ELSE 3
            END AS hours_until_next_refresh
        FROM ML.PREDICT(MODEL `{MODEL_ID}`, (
            SELECT * FROM `{FEATURE_VIEW}`
            -- The model looks up to the specified time
            WHERE datetime_utc <= {current_time_sql}
            -- Optional: optimize by only looking at recent hours
            AND datetime_utc >= TIMESTAMP_SUB({current_time_sql}, INTERVAL 24 HOUR)
        )) p
    ) new_data
    WHERE 
        CAST(us.latitude AS STRING) = CAST(new_data.latitude AS STRING)
        AND CAST(us.longitude AS STRING) = CAST(new_data.longitude AS STRING)
        -- Only update users whose schedule has expired
        AND us.next_refresh_utc <= {current_time_sql};
    """
    
    start_time = time.time()
    try:
        job = client.query(query)
        job.result() # Wait for completion
        elapsed = time.time() - start_time
        print(f"ML Pipeline Success: Updated {job.num_dml_affected_rows} users in {elapsed:.2f}s")
    except Exception as e:
        print(f"ML Pipeline Failed: {e}")