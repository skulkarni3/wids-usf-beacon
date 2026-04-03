# routers/ml_pipeline.py
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Query

# Import your ML service script
from ..services import hwp_pipeline 

# Initialize a dedicated router for ML jobs
router = APIRouter(
    prefix="/monitor/ml",
    tags=["Machine Learning Pipelines"]
)

@router.post("/trigger_hwp_pipeline", status_code=202)
def trigger_hwp_pipeline(
    background_tasks: BackgroundTasks,
    sim_start: Optional[datetime] = Query(None, description="Optional: ISO datetime to run a historical backtest.")
):
    """
    Triggers the BigQuery ML pipeline to update the next_refresh_utc for all users.
    If 'sim_start' is omitted, it runs on the current real-time data.
    """
    # Hand the heavy lifting off to FastAPI's background workers
    background_tasks.add_task(hwp_pipeline.run_ml_scheduler_update, sim_start)
    
    mode = "Simulation" if sim_start else "Production"
    return {
        "status": "accepted",
        "message": f"HWP ML Pipeline ({mode}) triggered and is running in the background."
    }