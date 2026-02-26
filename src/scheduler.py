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
    # Fetch news and score sentiment every 15 minutes (Phase 4)
    "fetch-news-15m": {
        "task": "src.ingestion.scheduler.fetch_news_sentiment",
        "schedule": crontab(minute="*/15"),  # Every 15 minutes
        "options": {"queue": "ingestion"},
    },
    # Fetch weather forecasts every 2 hours (Phase 5 - Predictive Layer)
    "fetch-weather-2h": {
        "task": "src.ingestion.scheduler.fetch_weather_forecast",
        "schedule": crontab(minute=0, hour="*/2"),  # Every 2 hours at :00
        "options": {"queue": "ingestion"},
    },
    # Evaluate predictive correlations every 15 minutes (Phase 5 - Linked Fate v4)
    "evaluate-predictive-15m": {
        "task": "src.ingestion.scheduler.evaluate_predictive_correlation",
        "schedule": crontab(minute="*/15"),  # Every 15 minutes
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


@app.task(bind=True, name="src.ingestion.scheduler.fetch_news_sentiment")
def fetch_news_sentiment(self):
    """
    Celery task to fetch news headlines and score sentiment (Linked Fate v3).
    
    Phase 4: Unstructured data layer.
    Fetches Google News RSS for Texas Node keywords and scores
    sentiment locally using NLTK VADER.
    
    Returns:
        Dict with news summary
    """
    from src.ingestion.news import get_news_summary

    try:
        result = get_news_summary()
        return {
            "status": "completed",
            "total_headlines": result["total_count"],
            "overall_sentiment": result["overall_sentiment"],
            "critical_count": len(result["critical_headlines"]),
            "fetched_at": result["fetched_at"].isoformat(),
        }
    except Exception as e:
        self.retry(exc=e, countdown=60, max_retries=3)


@app.task(bind=True, name="src.ingestion.scheduler.fetch_weather_forecast")
def fetch_weather_forecast(self):
    """
    Celery task to fetch weather forecasts from NWS API (Linked Fate v4).
    
    Phase 5: Predictive layer.
    Fetches 7-day forecasts for key Texas locations and assesses
    temperature danger zones for grid strain prediction.
    
    Returns:
        Dict with weather fetch summary
    """
    from src.ingestion.weather import get_weather_summary

    try:
        summary = get_weather_summary()
        danger = summary.get("danger_assessment", {}).get("overall", {})
        
        return {
            "status": "completed",
            "forecasts_fetched": len(summary.get("forecasts", {})),
            "alerts_count": len(summary.get("alerts", [])),
            "critical_alerts": len(summary.get("critical_alerts", [])),
            "grid_strain_prediction": danger.get("grid_strain_prediction", "NORMAL"),
            "heat_risk": danger.get("heat_risk", "NONE"),
            "freeze_risk": danger.get("freeze_risk", "NONE"),
            "fetched_at": summary.get("fetched_at"),
        }
    except Exception as e:
        self.retry(exc=e, countdown=120, max_retries=2)


@app.task(bind=True, name="src.ingestion.scheduler.evaluate_predictive_correlation")
def evaluate_predictive_correlation(self):
    """
    Celery task to evaluate predictive weather-physical correlations (Linked Fate v4).
    
    Cross-references weather forecasts with physical system status to generate
    anticipatory alerts before scarcity events occur.
    
    Rules:
    - IF (Forecast Temp > 100°F in 48h) AND (ERCOT Margin < 10%) -> PREDICTIVE: EXTREME GRID STRAIN
    - IF (Forecast Temp < 25°F in 48h) -> PREDICTIVE: FREEZE EMERGENCY
    - IF (Hurricane/Storm Warning for Houston) -> PREDICTIVE: PORT CHOKEPOINT
    
    Returns:
        Dict with predictive correlation analysis results
    """
    from src.analysis.market_correlation import evaluate_predictive_correlations

    try:
        result = evaluate_predictive_correlations()
        return result
    except Exception as e:
        self.retry(exc=e, countdown=60, max_retries=2)


@app.task(name="src.ingestion.scheduler.health_check")
def health_check():
    """Simple health check task."""
    return {"status": "healthy"}
