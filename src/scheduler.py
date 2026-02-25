"""
Celery Task Scheduler

Defines scheduled tasks for data ingestion.
Runs hourly batch fetches for USGS and EIA data.
"""

from celery import Celery
from celery.schedules import crontab

from src.config.settings import settings

# Initialize Celery
app = Celery(
    "pwst",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

# Celery configuration
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,  # 10 minute timeout
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)

# Beat schedule (periodic tasks)
app.conf.beat_schedule = {
    # Fetch ERCOT grid data every hour
    "fetch-ercot-hourly": {
        "task": "src.ingestion.scheduler.fetch_ercot_data",
        "schedule": crontab(minute=5),  # 5 minutes past every hour
        "options": {"queue": "ingestion"},
    },
    # Fetch Texas groundwater every 6 hours
    "fetch-usgs-water-6h": {
        "task": "src.ingestion.scheduler.fetch_usgs_water",
        "schedule": crontab(minute=15, hour="*/6"),  # Every 6 hours at :15
        "options": {"queue": "ingestion"},
    },
    # Run anomaly detection hourly
    "detect-anomalies-hourly": {
        "task": "src.ingestion.scheduler.detect_anomalies",
        "schedule": crontab(minute=30),  # 30 minutes past every hour
        "options": {"queue": "analysis"},
    },
}


@app.task(bind=True, name="src.ingestion.scheduler.fetch_ercot_data")
def fetch_ercot_data(self, hours_back: int = 24):
    """
    Celery task to fetch ERCOT grid data from EIA.
    
    Args:
        hours_back: Hours of historical data to fetch
        
    Returns:
        Dict with fetch summary
    """
    from src.ingestion.eia import fetch_ercot_grid

    try:
        result = fetch_ercot_grid(hours_back=hours_back)
        return result
    except Exception as e:
        self.retry(exc=e, countdown=60, max_retries=3)


@app.task(bind=True, name="src.ingestion.scheduler.fetch_usgs_water")
def fetch_usgs_water(self, days_back: int = 7):
    """
    Celery task to fetch Texas groundwater data from USGS.
    
    Args:
        days_back: Days of historical data to fetch
        
    Returns:
        Dict with fetch summary
    """
    from src.ingestion.usgs import fetch_texas_groundwater

    try:
        result = fetch_texas_groundwater(days_back=days_back)
        return result
    except Exception as e:
        self.retry(exc=e, countdown=60, max_retries=3)


@app.task(bind=True, name="src.ingestion.scheduler.detect_anomalies")
def detect_anomalies(self):
    """
    Celery task to run anomaly detection on recent observations.
    
    Returns:
        Dict with anomaly detection summary
    """
    from src.analysis.anomaly import run_anomaly_detection

    try:
        result = run_anomaly_detection()
        return result
    except Exception as e:
        self.retry(exc=e, countdown=60, max_retries=3)


@app.task(name="src.ingestion.scheduler.health_check")
def health_check():
    """Simple health check task."""
    return {"status": "healthy"}
