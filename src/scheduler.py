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
    # Fetch Port of Houston data every 15 minutes
    "fetch-port-data-15m": {
        "task": "src.ingestion.scheduler.fetch_port_data",
        "schedule": crontab(minute="*/15"),  # Every 15 minutes
        "options": {"queue": "ingestion"},
    },
    # Fetch financial market data every 15 minutes (Phase 3)
    "fetch-market-data-15m": {
        "task": "src.ingestion.scheduler.fetch_market_data",
        "schedule": crontab(minute="*/15"),  # Every 15 minutes during market hours
        "options": {"queue": "ingestion"},
    },
    # Run anomaly detection hourly
    "detect-anomalies-hourly": {
        "task": "src.ingestion.scheduler.detect_anomalies",
        "schedule": crontab(minute=30),  # 30 minutes past every hour
        "options": {"queue": "analysis"},
    },
    # Run risk engine evaluation every 5 minutes
    "evaluate-risk-5m": {
        "task": "src.ingestion.scheduler.evaluate_risk",
        "schedule": crontab(minute="*/5"),  # Every 5 minutes
        "options": {"queue": "analysis"},
    },
    # Run market correlation check every 5 minutes (Phase 3 - Linked Fate v2)
    "evaluate-market-correlation-5m": {
        "task": "src.ingestion.scheduler.evaluate_market_correlation",
        "schedule": crontab(minute="*/5"),  # Every 5 minutes
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


@app.task(bind=True, name="src.ingestion.scheduler.fetch_port_data")
def fetch_port_data(self):
    """
    Celery task to fetch/generate Port of Houston logistics data.
    
    Returns:
        Dict with fetch summary
    """
    from src.ingestion.port import fetch_port_data as _fetch_port

    try:
        result = _fetch_port()
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


@app.task(bind=True, name="src.ingestion.scheduler.evaluate_risk")
def evaluate_risk(self):
    """
    Celery task to run the Linked Fate risk engine.
    
    Evaluates current conditions across all data feeds and
    generates/updates alerts based on threshold rules.
    
    Returns:
        Dict with risk evaluation summary
    """
    from src.analysis.risk_engine import evaluate_all_risks

    try:
        result = evaluate_all_risks()
        return result
    except Exception as e:
        self.retry(exc=e, countdown=30, max_retries=3)


@app.task(bind=True, name="src.ingestion.scheduler.fetch_market_data")
def fetch_market_data(self):
    """
    Celery task to fetch Texas proxy watchlist market data.
    
    Phase 3: Financial data integration using yfinance.
    Fetches quotes for VST, NRG, TXN and caches for analysis.
    
    Returns:
        Dict with fetch summary
    """
    from src.ingestion.finance import fetch_and_cache_market_data

    try:
        result = fetch_and_cache_market_data()
        return result
    except Exception as e:
        self.retry(exc=e, countdown=60, max_retries=3)


@app.task(bind=True, name="src.ingestion.scheduler.evaluate_market_correlation")
def evaluate_market_correlation(self):
    """
    Celery task to evaluate market-physical correlations (Linked Fate v2).
    
    Cross-references physical alerts with market movements to detect:
    - MARKET_REACTION: ENERGY_STRAIN (VST/NRG moving with GRID alerts)
    - MARKET_REACTION: WATER_STRESS (TXN moving with WATR alerts)
    - MARKET_REACTION: SUPPLY_CHAIN (movement with PORT alerts)
    
    Returns:
        Dict with correlation analysis results
    """
    from src.analysis.market_correlation import evaluate_market_correlations

    try:
        result = evaluate_market_correlations()
        return result
    except Exception as e:
        self.retry(exc=e, countdown=30, max_retries=3)


@app.task(name="src.ingestion.scheduler.health_check")
def health_check():
    """Simple health check task."""
    return {"status": "healthy"}
