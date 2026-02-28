"""
FastAPI Backend for PWST

Provides REST API endpoints for:
- Data queries (observations, anomalies)
- Command execution
- Health checks
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

import structlog
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.db.connection import check_database_connection, get_db, get_postgis_version
from src.db.models import Alert, Anomaly, Indicator, Observation, Region, Station

logger = structlog.get_logger(__name__)

# FastAPI app
app = FastAPI(
    title="PWST API",
    description="Physical World Scarcity Terminal - Backend API",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# CORS middleware for Streamlit
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Streamlit runs on different port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────
# Request/Response Models
# ─────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    database: bool
    postgis_version: Optional[str]
    timestamp: datetime


class CommandRequest(BaseModel):
    """Terminal command request."""

    command: str = Field(..., description="Raw command string (e.g., 'WATR US-TX <GO>')")
    session_id: Optional[UUID] = Field(default_factory=uuid4)


class CommandResponse(BaseModel):
    """Terminal command response."""

    success: bool
    function_code: Optional[str]
    region_code: Optional[str]
    data: Optional[list[dict[str, Any]]]
    anomalies: Optional[list[dict[str, Any]]]
    message: Optional[str]
    execution_time_ms: int


class ObservationResponse(BaseModel):
    """Single observation record."""

    indicator_code: str
    station_id: Optional[str]
    station_name: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    value: float
    unit: Optional[str]
    observed_at: datetime
    quality_flag: str


class AnomalyResponse(BaseModel):
    """Anomaly record."""

    anomaly_id: int
    indicator_code: str
    station_name: Optional[str]
    detected_at: datetime
    anomaly_type: str
    severity: float
    z_score: float
    baseline_value: float
    observed_value: float


class AlertResponse(BaseModel):
    """Risk alert for ticker display."""

    alert_id: int
    alert_type: str
    alert_level: str
    region_code: Optional[str]
    title: str
    message: str
    indicator_values: dict[str, Any]
    triggered_at: datetime
    is_active: bool


class StockQuoteResponse(BaseModel):
    """Stock quote for financial data."""

    symbol: str
    name: str
    price: float
    change: float
    change_percent: float
    volume: int
    market_cap: Optional[float]
    day_high: float
    day_low: float
    open: float
    prev_close: float
    timestamp: str
    metadata: dict[str, Any]


class MarketSummaryResponse(BaseModel):
    """Market summary for FIN command."""

    status: str
    quotes: list[dict[str, Any]]
    histories: Optional[dict[str, Any]]
    aggregate: dict[str, Any]
    significant_moves: list[dict[str, Any]]
    physical_status: Optional[dict[str, Any]]
    correlations: Optional[list[dict[str, Any]]]
    timestamp: str


# ─────────────────────────────────────────────────────────────
# Health Endpoints
# ─────────────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse, tags=["System"])
def health_check():
    """Check system health and database connectivity."""
    db_healthy = check_database_connection()
    postgis_ver = get_postgis_version() if db_healthy else None

    return HealthResponse(
        status="healthy" if db_healthy else "degraded",
        database=db_healthy,
        postgis_version=postgis_ver,
        timestamp=datetime.now(timezone.utc),
    )


@app.get("/", tags=["System"])
def root():
    """Root endpoint."""
    return {
        "name": "PWST API",
        "version": "0.1.0",
        "status": "operational",
    }


# ─────────────────────────────────────────────────────────────
# Command Endpoints
# ─────────────────────────────────────────────────────────────


@app.post("/command", response_model=CommandResponse, tags=["Commands"])
def execute_command(request: CommandRequest, db: Session = Depends(get_db)):
    """
    Execute a terminal command.
    
    Supported commands:
    - WATR [region] <GO> - Groundwater data
    - GRID [region] <GO> - Power grid data
    - RISK [region] <GO> - Risk dashboard
    """
    import time

    start_time = time.time()

    try:
        # Parse command
        parsed = parse_command(request.command)

        if not parsed["function_code"]:
            return CommandResponse(
                success=False,
                function_code=None,
                region_code=None,
                data=None,
                anomalies=None,
                message="Invalid command. Use format: FUNC [REGION] <GO>",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        # Execute based on function code
        function_code = parsed["function_code"]
        region_code = parsed["region_code"] or settings.default_region

        if function_code == "WATR":
            data, anomalies = execute_watr(db, region_code)
        elif function_code == "GRID":
            data, anomalies = execute_grid(db, region_code)
        elif function_code == "FLOW":
            data, anomalies = execute_flow(db, region_code)
        elif function_code == "RISK":
            data, anomalies = execute_risk(db, region_code)
        elif function_code == "FIN":
            data, anomalies = execute_fin(db, region_code)
        elif function_code == "NEWS":
            data, anomalies = execute_news(db, region_code)
        elif function_code == "WX":
            data, anomalies = execute_wx(db, region_code)
        elif function_code == "MACRO":
            data, anomalies = execute_macro(db, region_code)
        else:
            return CommandResponse(
                success=False,
                function_code=function_code,
                region_code=region_code,
                data=None,
                anomalies=None,
                message=f"Unknown function code: {function_code}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        return CommandResponse(
            success=True,
            function_code=function_code,
            region_code=region_code,
            data=data,
            anomalies=anomalies,
            message=None,
            execution_time_ms=int((time.time() - start_time) * 1000),
        )

    except Exception as e:
        logger.error("command_execution_error", error=str(e))
        return CommandResponse(
            success=False,
            function_code=None,
            region_code=None,
            data=None,
            anomalies=None,
            message=str(e),
            execution_time_ms=int((time.time() - start_time) * 1000),
        )


def parse_command(command: str) -> dict[str, Any]:
    """
    Parse terminal command string.
    
    Format: FUNC [REGION] [MODIFIERS] <GO>
    
    Examples:
        - WATR <GO>
        - WATR US-TX <GO>
        - GRID ERCOT -24h <GO>
    """
    command = command.strip().upper()

    # Remove <GO> if present
    command = command.replace("<GO>", "").strip()

    parts = command.split()

    if not parts:
        return {"function_code": None, "region_code": None, "modifiers": []}

    function_code = parts[0] if len(parts) > 0 else None
    region_code = None
    modifiers = []

    for part in parts[1:]:
        if part.startswith("-"):
            modifiers.append(part)
        elif not region_code:
            region_code = part

    return {
        "function_code": function_code,
        "region_code": region_code,
        "modifiers": modifiers,
    }


def execute_watr(db: Session, region_code: str) -> tuple[list, list]:
    """Execute WATR command - groundwater data."""
    # Get indicator
    indicator = db.query(Indicator).filter_by(code="GW_LEVEL").first()
    if not indicator:
        return [], []

    # Get recent observations
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    observations = (
        db.query(Observation, Station)
        .join(Station, Observation.station_id == Station.station_id)
        .filter(Observation.indicator_id == indicator.indicator_id)
        .filter(Observation.observed_at >= cutoff)
        .order_by(Observation.observed_at.desc())
        .limit(500)
        .all()
    )

    # Get anomalies
    anomalies_query = (
        db.query(Anomaly)
        .filter(Anomaly.indicator_id == indicator.indicator_id)
        .filter(Anomaly.detected_at >= cutoff)
        .filter(Anomaly.is_acknowledged == False)
        .order_by(Anomaly.severity.desc())
        .limit(50)
        .all()
    )

    # Format data
    data = []
    seen_stations = set()

    for obs, station in observations:
        if station.station_id in seen_stations:
            continue
        seen_stations.add(station.station_id)

        # Extract coordinates from PostGIS point
        from geoalchemy2.shape import to_shape

        point = to_shape(station.location)

        data.append(
            {
                "station_id": station.external_id,
                "station_name": station.name,
                "latitude": point.y,
                "longitude": point.x,
                "value": obs.value,
                "unit": indicator.unit,
                "observed_at": obs.observed_at.isoformat(),
                "quality_flag": obs.quality_flag,
                "aquifer": station.aquifer_name,
            }
        )

    anomalies = [
        {
            "anomaly_id": a.anomaly_id,
            "severity": a.severity,
            "z_score": a.z_score,
            "baseline": a.baseline_value,
            "observed": a.observed_value,
            "detected_at": a.detected_at.isoformat(),
            "type": a.anomaly_type,
        }
        for a in anomalies_query
    ]

    return data, anomalies


def execute_grid(db: Session, region_code: str) -> tuple[list, list]:
    """Execute GRID command - power grid data."""
    from sqlalchemy import func as sqlfunc
    
    # Get grid indicators
    indicator_codes = ["GRID_DEMAND", "GRID_GENERATION", "GRID_WIND", "GRID_SOLAR"]
    indicators = db.query(Indicator).filter(Indicator.code.in_(indicator_codes)).all()

    if not indicators:
        return [], []

    indicator_map = {i.indicator_id: i for i in indicators}
    code_to_id = {i.code: i.indicator_id for i in indicators}
    indicator_ids = list(indicator_map.keys())

    # Get recent observations
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    observations = (
        db.query(Observation)
        .filter(Observation.indicator_id.in_(indicator_ids))
        .filter(Observation.observed_at >= cutoff)
        .order_by(Observation.observed_at.desc())
        .limit(1000)
        .all()
    )

    # Get anomalies
    anomalies_query = (
        db.query(Anomaly)
        .filter(Anomaly.indicator_id.in_(indicator_ids))
        .filter(Anomaly.detected_at >= cutoff)
        .filter(Anomaly.is_acknowledged == False)
        .order_by(Anomaly.severity.desc())
        .limit(50)
        .all()
    )

    # Get latest value for EACH indicator (they may have different timestamps)
    latest_values = {}
    for code in indicator_codes:
        ind_id = code_to_id.get(code)
        if ind_id:
            latest_obs = (
                db.query(Observation)
                .filter(Observation.indicator_id == ind_id)
                .order_by(Observation.observed_at.desc())
                .first()
            )
            if latest_obs:
                latest_values[code.lower()] = latest_obs.value

    # Format data - aggregate by time for time series
    time_series: dict[str, dict] = {}

    for obs in observations:
        indicator = indicator_map.get(obs.indicator_id)
        if not indicator:
            continue

        time_key = obs.observed_at.isoformat()
        if time_key not in time_series:
            time_series[time_key] = {"observed_at": time_key}

        time_series[time_key][indicator.code.lower()] = obs.value

    # Build data list with a "latest" summary as the first record
    data = list(time_series.values())
    
    # Insert summary record at the beginning with all latest values
    if latest_values:
        summary = {"observed_at": datetime.now(timezone.utc).isoformat(), "is_summary": True}
        summary.update(latest_values)
        data.insert(0, summary)

    anomalies = [
        {
            "anomaly_id": a.anomaly_id,
            "indicator": indicator_map.get(a.indicator_id, {}).code
            if a.indicator_id in indicator_map
            else "unknown",
            "severity": a.severity,
            "z_score": a.z_score,
            "baseline": a.baseline_value,
            "observed": a.observed_value,
            "detected_at": a.detected_at.isoformat(),
            "type": a.anomaly_type,
        }
        for a in anomalies_query
    ]

    return data, anomalies


def execute_flow(db: Session, region_code: str) -> tuple[list, list]:
    """Execute FLOW command - port/logistics data."""
    from geoalchemy2.shape import to_shape
    
    # Map region codes to port codes
    port_map = {
        "HOU": ["HOU"],
        "HOUSTON": ["HOU"],
        "GAL": ["GAL"],
        "GALVESTON": ["GAL"],
        "TXC": ["TXC"],
        "TEXAS_CITY": ["TXC"],
        "US-TX": ["HOU", "GAL", "TXC"],  # All Texas ports
        "ERCOT": ["HOU", "GAL", "TXC"],
    }
    
    target_ports = port_map.get(region_code.upper(), ["HOU"])
    
    # Get port indicators
    indicator_codes = ["PORT_VESSELS", "PORT_WAITING", "PORT_DWELL", "PORT_THROUGHPUT"]
    indicators = db.query(Indicator).filter(Indicator.code.in_(indicator_codes)).all()

    if not indicators:
        return [], []

    indicator_map = {i.indicator_id: i for i in indicators}
    code_to_id = {i.code: i.indicator_id for i in indicators}
    indicator_ids = list(indicator_map.keys())

    # Get recent observations
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    # Get stations (ports)
    stations = (
        db.query(Station)
        .filter(Station.station_type == "port")
        .filter(Station.external_id.in_(target_ports))
        .all()
    )
    
    station_ids = [s.station_id for s in stations]
    station_map = {s.station_id: s for s in stations}

    observations = (
        db.query(Observation)
        .filter(Observation.indicator_id.in_(indicator_ids))
        .filter(Observation.station_id.in_(station_ids))
        .filter(Observation.observed_at >= cutoff)
        .order_by(Observation.observed_at.desc())
        .limit(500)
        .all()
    )

    # Get anomalies
    anomalies_query = (
        db.query(Anomaly)
        .filter(Anomaly.indicator_id.in_(indicator_ids))
        .filter(Anomaly.detected_at >= cutoff)
        .filter(Anomaly.is_acknowledged == False)
        .order_by(Anomaly.severity.desc())
        .limit(50)
        .all()
    )

    # Get latest value for EACH indicator at EACH port
    latest_by_port: dict[str, dict] = {}
    
    for station in stations:
        port_code = station.external_id
        point = to_shape(station.location)
        latest_by_port[port_code] = {
            "port_code": port_code,
            "port_name": station.name,
            "latitude": point.y,
            "longitude": point.x,
        }
        
        for code in indicator_codes:
            ind_id = code_to_id.get(code)
            if ind_id:
                latest_obs = (
                    db.query(Observation)
                    .filter(Observation.indicator_id == ind_id)
                    .filter(Observation.station_id == station.station_id)
                    .order_by(Observation.observed_at.desc())
                    .first()
                )
                if latest_obs:
                    latest_by_port[port_code][code.lower()] = latest_obs.value
                    latest_by_port[port_code]["observed_at"] = latest_obs.observed_at.isoformat()

    # Build time series for charts
    time_series: dict[str, dict] = {}
    for obs in observations:
        indicator = indicator_map.get(obs.indicator_id)
        station = station_map.get(obs.station_id)
        if not indicator or not station:
            continue

        time_key = f"{station.external_id}_{obs.observed_at.isoformat()}"
        if time_key not in time_series:
            time_series[time_key] = {
                "observed_at": obs.observed_at.isoformat(),
                "port_code": station.external_id,
            }

        time_series[time_key][indicator.code.lower()] = obs.value

    # Combine latest summaries + time series
    data = list(latest_by_port.values()) + list(time_series.values())

    anomalies = [
        {
            "anomaly_id": a.anomaly_id,
            "indicator": indicator_map.get(a.indicator_id).code
            if a.indicator_id in indicator_map
            else "unknown",
            "severity": a.severity,
            "z_score": a.z_score,
            "baseline": a.baseline_value,
            "observed": a.observed_value,
            "detected_at": a.detected_at.isoformat(),
            "type": a.anomaly_type,
        }
        for a in anomalies_query
    ]

    return data, anomalies


def execute_risk(db: Session, region_code: str) -> tuple[list, list]:
    """Execute RISK command - aggregated risk dashboard."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    # Get all recent anomalies grouped by indicator
    anomalies = (
        db.query(Anomaly, Indicator)
        .join(Indicator, Anomaly.indicator_id == Indicator.indicator_id)
        .filter(Anomaly.detected_at >= cutoff)
        .filter(Anomaly.is_acknowledged == False)
        .order_by(Anomaly.severity.desc())
        .limit(100)
        .all()
    )

    # Aggregate by indicator category
    category_risks: dict[str, dict] = {}

    for anomaly, indicator in anomalies:
        category = indicator.category
        if category not in category_risks:
            category_risks[category] = {
                "category": category,
                "anomaly_count": 0,
                "max_severity": 0,
                "critical_count": 0,
            }

        category_risks[category]["anomaly_count"] += 1
        category_risks[category]["max_severity"] = max(
            category_risks[category]["max_severity"], anomaly.severity or 0
        )
        if anomaly.anomaly_type == "critical_deviation":
            category_risks[category]["critical_count"] += 1

    data = list(category_risks.values())

    anomaly_list = [
        {
            "anomaly_id": a.anomaly_id,
            "indicator_code": i.code,
            "indicator_name": i.name,
            "category": i.category,
            "severity": a.severity,
            "z_score": a.z_score,
            "detected_at": a.detected_at.isoformat(),
            "type": a.anomaly_type,
        }
        for a, i in anomalies
    ]

    return data, anomaly_list


def execute_fin(db: Session, region_code: str) -> tuple[list, list]:
    """
    Execute FIN command - financial market correlation view.
    
    Fetches Texas proxy watchlist data and correlates with physical alerts.
    
    Args:
        db: Database session
        region_code: Region code (US-TX for Texas proxy watchlist)
        
    Returns:
        Tuple of (market_data, market_alerts)
    """
    from src.ingestion.finance import (
        fetch_watchlist_quotes,
        detect_significant_moves,
        fetch_all_watchlist_history,
        TEXAS_PROXY_WATCHLIST,
    )
    
    # Fetch current quotes
    quotes = fetch_watchlist_quotes()
    
    # Fetch historical data for sparklines
    histories = fetch_all_watchlist_history(period="5d")
    
    # Detect significant moves
    significant_moves = detect_significant_moves(quotes)
    
    # Get current physical alerts for correlation
    active_alerts = (
        db.query(Alert)
        .filter(Alert.is_active == True)
        .filter(Alert.alert_level.in_(["WARNING", "CRITICAL"]))
        .order_by(Alert.triggered_at.desc())
        .limit(10)
        .all()
    )
    
    # Build physical status summary
    physical_status = {
        "grid": "NORMAL",
        "water": "NORMAL",
        "port": "NORMAL",
    }
    
    for alert in active_alerts:
        if alert.alert_type == "GRID":
            physical_status["grid"] = alert.alert_level
        elif alert.alert_type == "WATR":
            physical_status["water"] = alert.alert_level
        elif alert.alert_type == "FLOW":
            physical_status["port"] = alert.alert_level
        elif alert.alert_type == "LINKED":
            # Linked alerts affect all
            physical_status["grid"] = max(physical_status["grid"], alert.alert_level, key=lambda x: {"NORMAL": 0, "WATCH": 1, "WARNING": 2, "CRITICAL": 3}.get(x, 0))
    
    # Build market data response
    data = []
    
    for quote in quotes:
        quote_dict = quote.to_dict()
        
        # Add sparkline data if available
        history = histories.get(quote.symbol)
        if history:
            quote_dict["sparkline"] = history.prices[-24:]  # Last 24 data points
            quote_dict["sparkline_dates"] = history.dates[-24:]
        
        # Add Texas exposure info
        watchlist_info = TEXAS_PROXY_WATCHLIST.get(quote.symbol, {})
        quote_dict["texas_exposure"] = watchlist_info.get("exposure")
        quote_dict["physical_link"] = watchlist_info.get("physical_link")
        quote_dict["sensitivity"] = watchlist_info.get("sensitivity")
        
        data.append(quote_dict)
    
    # Market alerts (significant moves that may correlate with physical events)
    market_alerts = []
    
    for move in significant_moves:
        physical_link = move.get("physical_link", "").split(",")
        
        # Check if any linked physical systems have alerts
        correlation_detected = False
        correlated_alert = None
        
        for link in physical_link:
            link = link.strip()
            if link == "GRID" and physical_status["grid"] in ["WARNING", "CRITICAL"]:
                correlation_detected = True
                correlated_alert = f"GRID {physical_status['grid']}"
            elif link == "WATR" and physical_status["water"] in ["WARNING", "CRITICAL"]:
                correlation_detected = True
                correlated_alert = f"WATER {physical_status['water']}"
            elif link == "FLOW" and physical_status["port"] in ["WARNING", "CRITICAL"]:
                correlation_detected = True
                correlated_alert = f"PORT {physical_status['port']}"
        
        alert_entry = {
            "symbol": move["symbol"],
            "name": move["name"],
            "move_type": move["move_type"],
            "direction": move["direction"],
            "change_percent": move["change_percent"],
            "physical_link": move.get("physical_link"),
            "correlation_detected": correlation_detected,
            "correlated_alert": correlated_alert,
            "timestamp": move["timestamp"],
        }
        market_alerts.append(alert_entry)
    
    # Add physical status to first data record for UI consumption
    if data:
        data[0]["physical_status"] = physical_status
        data[0]["total_alerts"] = len(active_alerts)
    
    return data, market_alerts


def execute_news(db: Session, region_code: str) -> tuple[list, list]:
    """
    Execute NEWS command - news headlines with sentiment analysis.
    
    Fetches RSS feeds for Texas Node keywords and scores sentiment
    using NLTK VADER. Part of Phase 4: Unstructured Data Layer.
    
    Args:
        db: Database session
        region_code: Region code (used to filter relevant categories)
        
    Returns:
        Tuple of (headlines_data, critical_headlines)
    """
    from src.ingestion.news import get_news_summary, TEXAS_NODE_QUERIES
    
    # Fetch and score news
    news_data = get_news_summary()
    
    headlines = news_data["headlines"]
    summaries = news_data["summaries"]
    critical = news_data["critical_headlines"]
    
    # Format headlines for UI
    data = []
    
    for h in headlines[:50]:  # Limit to 50 headlines
        data.append({
            "title": h.title,
            "source": h.source,
            "url": h.url,
            "published_at": h.published_at.isoformat() if h.published_at else None,
            "category": h.query_category,
            "query_term": h.query_term,
            "sentiment_score": h.compound_score,
            "sentiment_label": h.sentiment_label,
            "positive_score": h.positive_score,
            "negative_score": h.negative_score,
            "neutral_score": h.neutral_score,
        })
    
    # Add summary as first record for UI consumption
    if data:
        data[0]["_summary"] = {
            "total_headlines": news_data["total_count"],
            "overall_sentiment": news_data["overall_sentiment"],
            "fetched_at": news_data["fetched_at"].isoformat(),
            "categories": {
                cat: {
                    "count": s.headline_count,
                    "avg_sentiment": s.avg_sentiment,
                    "negative_count": s.negative_count,
                    "positive_count": s.positive_count,
                }
                for cat, s in summaries.items()
            },
        }
    
    # Critical headlines as "anomalies" for ticker tray
    critical_alerts = []
    for h in critical[:10]:
        critical_alerts.append({
            "title": h.title,
            "source": h.source,
            "sentiment_score": h.compound_score,
            "category": h.query_category,
            "published_at": h.published_at.isoformat() if h.published_at else None,
            "url": h.url,
            "type": "NEGATIVE_SENTIMENT",
            "severity": abs(h.compound_score),
        })
    
    return data, critical_alerts


def execute_wx(db: Session, region_code: str) -> tuple[list, list]:
    """
    Execute WX command - weather forecasts for predictive analysis.
    
    Fetches 7-day weather forecasts from NWS API for key Texas locations.
    Part of Phase 5: The Predictive Layer.
    
    Args:
        db: Database session
        region_code: Region code (used to select forecast locations)
        
    Returns:
        Tuple of (forecast_data, predictive_alerts)
    """
    from src.ingestion.weather import (
        get_weather_summary,
        get_predictive_alerts,
        TEXAS_FORECAST_LOCATIONS,
        TEMPERATURE_THRESHOLDS,
    )
    
    # Fetch weather summary
    weather_data = get_weather_summary()
    
    forecasts = weather_data.get("forecasts", {})
    alerts = weather_data.get("alerts", [])
    critical_alerts = weather_data.get("critical_alerts", [])
    danger = weather_data.get("danger_assessment", {})
    
    # Format forecast data for UI
    data = []
    
    for loc_key, forecast in forecasts.items():
        loc_info = TEXAS_FORECAST_LOCATIONS.get(loc_key, {})
        loc_danger = danger.get("locations", {}).get(loc_key, {})
        
        # Build forecast record
        record = {
            "location_key": loc_key,
            "location_name": forecast.get("location_name"),
            "latitude": forecast.get("latitude"),
            "longitude": forecast.get("longitude"),
            "grid_id": forecast.get("grid_id"),
            "purpose": loc_info.get("purpose"),
            "grid_relevance": loc_info.get("grid_relevance"),
            # Stats
            "max_temp_48h": forecast.get("stats", {}).get("max_temp_48h"),
            "min_temp_48h": forecast.get("stats", {}).get("min_temp_48h"),
            "max_temp_7d": forecast.get("stats", {}).get("max_temp_7d"),
            "min_temp_7d": forecast.get("stats", {}).get("min_temp_7d"),
            # Danger assessment
            "heat_risk": loc_danger.get("heat_risk", "NONE"),
            "freeze_risk": loc_danger.get("freeze_risk", "NONE"),
            "grid_strain_prediction": loc_danger.get("grid_strain_prediction", "NORMAL"),
            # Forecast periods (7-day)
            "periods": forecast.get("periods", [])[:14],
            # Hourly for charts
            "hourly": forecast.get("hourly", [])[:72],  # 3 days hourly
            "fetched_at": forecast.get("fetched_at"),
        }
        data.append(record)
    
    # Add summary as first record metadata
    if data:
        data[0]["_summary"] = {
            "overall_heat_risk": danger.get("overall", {}).get("heat_risk", "NONE"),
            "overall_freeze_risk": danger.get("overall", {}).get("freeze_risk", "NONE"),
            "overall_grid_strain": danger.get("overall", {}).get("grid_strain_prediction", "NORMAL"),
            "active_alerts": len(alerts),
            "critical_alerts": len(critical_alerts),
            "thresholds": TEMPERATURE_THRESHOLDS,
            "fetched_at": weather_data.get("fetched_at"),
        }
        # Include NWS alerts for display
        data[0]["_nws_alerts"] = critical_alerts[:5]
    
    # Get predictive alerts for ticker tray
    predictive_alerts = get_predictive_alerts()
    
    # Format as anomaly-style alerts
    formatted_alerts = []
    for alert in predictive_alerts:
        formatted_alerts.append({
            "type": "PREDICTIVE",
            "category": alert.get("category"),
            "level": alert.get("level"),
            "title": alert.get("title"),
            "message": alert.get("message"),
            "location": alert.get("location"),
            "temperature": alert.get("temperature"),
            "risk_type": alert.get("risk_type"),
            "severity": 1.0 if alert.get("level") == "CRITICAL" else 0.7,
        })
    
    return data, formatted_alerts


def execute_macro(db: Session, region_code: str) -> tuple[list, list]:
    """
    Execute MACRO command - commodity baseline data.
    
    Fetches Henry Hub Natural Gas spot prices from FRED API
    to provide macro-economic context for grid cost analysis.
    
    Part of Phase 6: The Macro-Commodity Layer.
    
    Args:
        db: Database session
        region_code: Region code (Texas focus)
        
    Returns:
        Tuple of (commodity_data, commodity_alerts)
    """
    from src.ingestion.macro_data import (
        get_macro_summary,
        get_gas_premium_status,
        COMMODITY_SERIES,
        HISTORICAL_BASELINE,
    )
    
    # Fetch macro summary (30 days of data)
    summary = get_macro_summary(days_back=30)
    
    # Format data for UI
    data = []
    
    henry_hub = summary.henry_hub
    if henry_hub:
        # Build chart data
        chart_data = []
        for obs in henry_hub.observations:
            chart_data.append({
                "date": obs.date.isoformat(),
                "price": obs.value,
            })
        
        # Get baseline info
        baseline = HISTORICAL_BASELINE.get("DHHNGSP", {})
        
        record = {
            "series_id": henry_hub.series_id,
            "name": henry_hub.name,
            "unit": henry_hub.unit,
            "latest_price": henry_hub.latest_value,
            "latest_date": henry_hub.latest_date.isoformat() if henry_hub.latest_date else None,
            "moving_average_30d": henry_hub.calculate_moving_average(30),
            "std_dev_30d": henry_hub.calculate_std_dev(30),
            "premium_percent": henry_hub.get_premium_percentage(),
            "is_above_ma": henry_hub.is_above_moving_average(),
            "is_mock": henry_hub.is_mock,
            "observation_count": len(henry_hub.observations),
            "chart_data": chart_data,
            # Thresholds for UI
            "premium_threshold": baseline.get("premium_threshold", 4.00),
            "spike_threshold": baseline.get("spike_threshold", 6.00),
            "historical_avg": baseline.get("30d_avg", 2.50),
            # Summary
            "_summary": {
                "commodity_alert_level": summary.commodity_alert_level,
                "grid_cost_impact": summary.grid_cost_impact,
                "alert_message": summary.alert_message,
                "fetched_at": summary.fetched_at.isoformat(),
            },
            # Series info
            "_series_info": COMMODITY_SERIES.get("DHHNGSP", {}),
        }
        data.append(record)
    
    # Generate alerts based on commodity status
    alerts = []
    
    if summary.commodity_alert_level in ["PREMIUM", "SPIKE"]:
        alerts.append({
            "type": "MACRO",
            "category": "COMMODITY",
            "level": "CRITICAL" if summary.commodity_alert_level == "SPIKE" else "WARNING",
            "title": f"GAS {summary.commodity_alert_level}",
            "message": summary.alert_message,
            "severity": 1.0 if summary.commodity_alert_level == "SPIKE" else 0.8,
        })
    elif summary.commodity_alert_level == "ELEVATED":
        alerts.append({
            "type": "MACRO",
            "category": "COMMODITY",
            "level": "WATCH",
            "title": "GAS ELEVATED",
            "message": summary.alert_message,
            "severity": 0.6,
        })
    
    return data, alerts


# ─────────────────────────────────────────────────────────────
# Data Query Endpoints
# ─────────────────────────────────────────────────────────────


@app.get("/observations", response_model=list[ObservationResponse], tags=["Data"])
def get_observations(
    indicator_code: str = Query(..., description="Indicator code (e.g., GW_LEVEL)"),
    hours: int = Query(24, description="Hours of data to retrieve"),
    limit: int = Query(500, description="Maximum records to return"),
    db: Session = Depends(get_db),
):
    """Get recent observations for an indicator."""
    indicator = db.query(Indicator).filter_by(code=indicator_code).first()
    if not indicator:
        raise HTTPException(status_code=404, detail=f"Indicator not found: {indicator_code}")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    observations = (
        db.query(Observation, Station)
        .outerjoin(Station, Observation.station_id == Station.station_id)
        .filter(Observation.indicator_id == indicator.indicator_id)
        .filter(Observation.observed_at >= cutoff)
        .order_by(Observation.observed_at.desc())
        .limit(limit)
        .all()
    )

    results = []
    for obs, station in observations:
        lat, lon = None, None
        if station and station.location:
            from geoalchemy2.shape import to_shape

            point = to_shape(station.location)
            lat, lon = point.y, point.x

        results.append(
            ObservationResponse(
                indicator_code=indicator_code,
                station_id=station.external_id if station else None,
                station_name=station.name if station else None,
                latitude=lat,
                longitude=lon,
                value=obs.value,
                unit=indicator.unit,
                observed_at=obs.observed_at,
                quality_flag=obs.quality_flag,
            )
        )

    return results


@app.get("/anomalies", response_model=list[AnomalyResponse], tags=["Data"])
def get_anomalies(
    hours: int = Query(24, description="Hours of anomalies to retrieve"),
    min_severity: float = Query(0.0, description="Minimum severity (0-1)"),
    indicator_code: Optional[str] = Query(None, description="Filter by indicator"),
    db: Session = Depends(get_db),
):
    """Get recent anomalies."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    query = (
        db.query(Anomaly, Indicator, Station)
        .join(Indicator, Anomaly.indicator_id == Indicator.indicator_id)
        .outerjoin(Station, Anomaly.station_id == Station.station_id)
        .filter(Anomaly.detected_at >= cutoff)
        .filter(Anomaly.severity >= min_severity)
    )

    if indicator_code:
        query = query.filter(Indicator.code == indicator_code)

    results = query.order_by(Anomaly.severity.desc()).limit(100).all()

    return [
        AnomalyResponse(
            anomaly_id=a.anomaly_id,
            indicator_code=i.code,
            station_name=s.name if s else None,
            detected_at=a.detected_at,
            anomaly_type=a.anomaly_type,
            severity=a.severity or 0,
            z_score=a.z_score or 0,
            baseline_value=a.baseline_value or 0,
            observed_value=a.observed_value or 0,
        )
        for a, i, s in results
    ]


@app.get("/indicators", tags=["Data"])
def get_indicators(db: Session = Depends(get_db)):
    """Get list of available indicators."""
    indicators = db.query(Indicator).all()
    return [
        {
            "code": i.code,
            "name": i.name,
            "category": i.category,
            "unit": i.unit,
            "function_code": i.function_code,
        }
        for i in indicators
    ]


@app.get("/stations", tags=["Data"])
def get_stations(
    station_type: Optional[str] = Query(None, description="Filter by type"),
    limit: int = Query(500, description="Maximum records"),
    db: Session = Depends(get_db),
):
    """Get list of monitoring stations."""
    query = db.query(Station).filter(Station.is_active == True)

    if station_type:
        query = query.filter(Station.station_type == station_type)

    stations = query.limit(limit).all()

    results = []
    for s in stations:
        from geoalchemy2.shape import to_shape

        point = to_shape(s.location)
        results.append(
            {
                "station_id": s.station_id,
                "external_id": s.external_id,
                "name": s.name,
                "station_type": s.station_type,
                "latitude": point.y,
                "longitude": point.x,
                "aquifer": s.aquifer_name,
            }
        )

    return results


# ─────────────────────────────────────────────────────────────
# Alerts Endpoint (Ticker Tray)
# ─────────────────────────────────────────────────────────────


@app.get("/alerts", response_model=list[AlertResponse], tags=["Alerts"])
def get_alerts(
    active_only: bool = Query(True, description="Only return active alerts"),
    alert_type: Optional[str] = Query(None, description="Filter by type (GRID, WATR, FLOW, LINKED)"),
    alert_level: Optional[str] = Query(None, description="Filter by level (WATCH, WARNING, CRITICAL)"),
    limit: int = Query(50, description="Maximum alerts to return"),
    db: Session = Depends(get_db),
):
    """
    Get risk alerts for ticker display.
    
    Returns alerts from the Linked Fate risk engine, sorted by severity and time.
    Used by the Ticker Tray UI component.
    """
    query = db.query(Alert)
    
    if active_only:
        query = query.filter(Alert.is_active == True)
    
    if alert_type:
        query = query.filter(Alert.alert_type == alert_type)
    
    if alert_level:
        query = query.filter(Alert.alert_level == alert_level)
    
    # Order by severity (CRITICAL > WARNING > WATCH) then by time
    level_order = {
        "CRITICAL": 0,
        "WARNING": 1,
        "WATCH": 2,
        "NORMAL": 3,
    }
    
    alerts = query.order_by(
        Alert.triggered_at.desc()
    ).limit(limit).all()
    
    # Sort by level priority (in memory since we can't easily do case expression)
    alerts_sorted = sorted(
        alerts,
        key=lambda a: (level_order.get(a.alert_level, 99), -a.triggered_at.timestamp())
    )
    
    return [
        AlertResponse(
            alert_id=a.alert_id,
            alert_type=a.alert_type,
            alert_level=a.alert_level,
            region_code=a.region_code,
            title=a.title,
            message=a.message,
            indicator_values=a.indicator_values or {},
            triggered_at=a.triggered_at,
            is_active=a.is_active,
        )
        for a in alerts_sorted
    ]


@app.post("/alerts/{alert_id}/acknowledge", tags=["Alerts"])
def acknowledge_alert(
    alert_id: int,
    db: Session = Depends(get_db),
):
    """Acknowledge an alert (user has seen it)."""
    alert = db.query(Alert).filter(Alert.alert_id == alert_id).first()
    
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    alert.is_acknowledged = True
    alert.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    
    return {"status": "acknowledged", "alert_id": alert_id}


# ─────────────────────────────────────────────────────────────
# Financial Data Endpoints (Phase 3)
# ─────────────────────────────────────────────────────────────


@app.get("/finance/quotes", tags=["Finance"])
def get_finance_quotes(
    symbols: Optional[str] = Query(None, description="Comma-separated symbols (default: Texas watchlist)"),
):
    """
    Get current stock quotes for Texas proxy watchlist.
    
    Default watchlist: VST (Vistra), NRG (NRG Energy), TXN (Texas Instruments)
    """
    from src.ingestion.finance import fetch_watchlist_quotes, TEXAS_PROXY_WATCHLIST
    
    symbol_list = None
    if symbols:
        symbol_list = [s.strip().upper() for s in symbols.split(",")]
    
    quotes = fetch_watchlist_quotes(symbol_list)
    
    return {
        "status": "success",
        "quotes": [q.to_dict() for q in quotes],
        "watchlist_info": TEXAS_PROXY_WATCHLIST,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/finance/history/{symbol}", tags=["Finance"])
def get_finance_history(
    symbol: str,
    period: str = Query("5d", description="Period: 1d, 5d, 1mo, 3mo, 6mo, 1y"),
    interval: str = Query("1h", description="Interval: 1m, 5m, 15m, 1h, 1d"),
):
    """
    Get historical price data for a symbol.
    
    Used for sparkline and chart rendering.
    """
    from src.ingestion.finance import fetch_stock_history
    
    history = fetch_stock_history(symbol.upper(), period=period, interval=interval)
    
    if not history:
        raise HTTPException(status_code=404, detail=f"No history found for {symbol}")
    
    return {
        "status": "success",
        "symbol": symbol.upper(),
        "period": period,
        "interval": interval,
        "prices": history.prices,
        "dates": history.dates,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/finance/summary", response_model=MarketSummaryResponse, tags=["Finance"])
def get_finance_summary(
    include_physical: bool = Query(True, description="Include physical alert status"),
    db: Session = Depends(get_db),
):
    """
    Get full market summary with physical correlation.
    
    Returns:
    - Current quotes for Texas proxy watchlist
    - Historical data for sparklines
    - Significant market moves
    - Physical alert status (Grid/Water/Port)
    - Detected correlations between market moves and physical events
    """
    from src.ingestion.finance import (
        fetch_watchlist_quotes,
        fetch_all_watchlist_history,
        detect_significant_moves,
        TEXAS_PROXY_WATCHLIST,
    )
    
    # Fetch market data
    quotes = fetch_watchlist_quotes()
    histories = fetch_all_watchlist_history(period="5d")
    significant_moves = detect_significant_moves(quotes)
    
    # Calculate aggregates
    if quotes:
        total_market_cap = sum(q.market_cap or 0 for q in quotes)
        avg_change = sum(q.change_percent for q in quotes) / len(quotes)
        aggregate = {
            "total_market_cap": total_market_cap,
            "avg_change_percent": avg_change,
            "symbols_up": sum(1 for q in quotes if q.change_percent > 0),
            "symbols_down": sum(1 for q in quotes if q.change_percent < 0),
        }
    else:
        aggregate = {}
    
    # Get physical status if requested
    physical_status = None
    correlations = None
    
    if include_physical:
        # Get active physical alerts
        active_alerts = (
            db.query(Alert)
            .filter(Alert.is_active == True)
            .filter(Alert.alert_level.in_(["WARNING", "CRITICAL"]))
            .order_by(Alert.triggered_at.desc())
            .limit(10)
            .all()
        )
        
        physical_status = {
            "grid": {"status": "NORMAL", "alerts": []},
            "water": {"status": "NORMAL", "alerts": []},
            "port": {"status": "NORMAL", "alerts": []},
        }
        
        for alert in active_alerts:
            alert_info = {
                "title": alert.title,
                "level": alert.alert_level,
                "message": alert.message,
            }
            if alert.alert_type == "GRID":
                physical_status["grid"]["status"] = alert.alert_level
                physical_status["grid"]["alerts"].append(alert_info)
            elif alert.alert_type == "WATR":
                physical_status["water"]["status"] = alert.alert_level
                physical_status["water"]["alerts"].append(alert_info)
            elif alert.alert_type == "FLOW":
                physical_status["port"]["status"] = alert.alert_level
                physical_status["port"]["alerts"].append(alert_info)
        
        # Check for market-physical correlations
        correlations = []
        for move in significant_moves:
            physical_link = move.get("physical_link", "").split(",")
            
            for link in physical_link:
                link = link.strip()
                if link == "GRID" and physical_status["grid"]["status"] in ["WARNING", "CRITICAL"]:
                    correlations.append({
                        "symbol": move["symbol"],
                        "market_move": f"{move['direction']} {abs(move['change_percent']):.1f}%",
                        "physical_event": f"GRID {physical_status['grid']['status']}",
                        "correlation_type": "ENERGY_STRAIN",
                        "confidence": "high" if move["move_type"] == "MAJOR" else "medium",
                    })
                elif link == "WATR" and physical_status["water"]["status"] in ["WARNING", "CRITICAL"]:
                    correlations.append({
                        "symbol": move["symbol"],
                        "market_move": f"{move['direction']} {abs(move['change_percent']):.1f}%",
                        "physical_event": f"WATER {physical_status['water']['status']}",
                        "correlation_type": "WATER_STRESS",
                        "confidence": "medium",
                    })
    
    return MarketSummaryResponse(
        status="active" if quotes else "unavailable",
        quotes=[q.to_dict() for q in quotes],
        histories={k: v.to_dict() for k, v in histories.items()} if histories else None,
        aggregate=aggregate,
        significant_moves=significant_moves,
        physical_status=physical_status,
        correlations=correlations,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ─────────────────────────────────────────────────────────────
# News & Sentiment Endpoints (Phase 4)
# ─────────────────────────────────────────────────────────────


@app.get("/news/headlines", tags=["News"])
def get_news_headlines(
    category: Optional[str] = Query(None, description="Filter by category: GRID, WATER, LOGISTICS, EQUITY"),
    limit: int = Query(50, description="Maximum headlines to return"),
):
    """
    Get news headlines with sentiment scores.
    
    Fetches from Google News RSS for Texas Node keywords and scores
    sentiment locally using NLTK VADER.
    """
    from src.ingestion.news import fetch_all_news, fetch_news_by_category
    
    if category:
        headlines = fetch_news_by_category(category.upper(), max_per_query=10)
    else:
        headlines = fetch_all_news(max_per_query=5)
    
    return {
        "status": "success",
        "headlines": [
            {
                "title": h.title,
                "source": h.source,
                "url": h.url,
                "published_at": h.published_at.isoformat() if h.published_at else None,
                "category": h.query_category,
                "query_term": h.query_term,
                "sentiment": {
                    "compound": h.compound_score,
                    "label": h.sentiment_label,
                    "positive": h.positive_score,
                    "negative": h.negative_score,
                    "neutral": h.neutral_score,
                },
            }
            for h in headlines[:limit]
        ],
        "count": len(headlines[:limit]),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/news/summary", tags=["News"])
def get_news_summary_endpoint():
    """
    Get aggregated news summary with category breakdowns.
    
    Includes overall sentiment, category-level stats, and critical headlines.
    """
    from src.ingestion.news import get_news_summary
    
    summary = get_news_summary()
    
    return {
        "status": "success",
        "overall_sentiment": summary["overall_sentiment"],
        "total_headlines": summary["total_count"],
        "critical_count": len(summary["critical_headlines"]),
        "categories": {
            cat: {
                "headline_count": s.headline_count,
                "avg_sentiment": s.avg_sentiment,
                "negative_count": s.negative_count,
                "positive_count": s.positive_count,
                "most_negative": {
                    "title": s.most_negative.title,
                    "score": s.most_negative.compound_score,
                } if s.most_negative else None,
                "most_positive": {
                    "title": s.most_positive.title,
                    "score": s.most_positive.compound_score,
                } if s.most_positive else None,
            }
            for cat, s in summary["summaries"].items()
        },
        "critical_headlines": [
            {
                "title": h.title,
                "source": h.source,
                "category": h.query_category,
                "sentiment_score": h.compound_score,
            }
            for h in summary["critical_headlines"][:5]
        ],
        "fetched_at": summary["fetched_at"].isoformat(),
    }


@app.get("/news/sentiment/{category}", tags=["News"])
def get_category_sentiment(
    category: str,
):
    """
    Get sentiment score for a specific category.
    
    Used by Linked Fate v3 for correlation checks.
    Categories: GRID, WATER, LOGISTICS, EQUITY
    """
    from src.ingestion.news import get_sentiment_for_correlation
    
    valid_categories = ["GRID", "WATER", "LOGISTICS", "EQUITY"]
    category = category.upper()
    
    if category not in valid_categories:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Must be one of: {valid_categories}",
        )
    
    sentiment = get_sentiment_for_correlation(category)
    
    # Determine label
    if sentiment <= -0.5:
        label = "VERY_NEGATIVE"
    elif sentiment <= -0.05:
        label = "NEGATIVE"
    elif sentiment < 0.05:
        label = "NEUTRAL"
    elif sentiment < 0.5:
        label = "POSITIVE"
    else:
        label = "VERY_POSITIVE"
    
    return {
        "category": category,
        "sentiment_score": sentiment,
        "sentiment_label": label,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────────────────────
# Weather & Forecast Endpoints (Phase 5)
# ─────────────────────────────────────────────────────────────


@app.get("/weather/forecast", tags=["Weather"])
def get_weather_forecast(
    location: Optional[str] = Query(None, description="Location key: DALLAS, HOUSTON, AUSTIN, SAN_ANTONIO"),
):
    """
    Get 7-day weather forecast for Texas locations.
    
    Fetches from NWS API for key Texas cities used in predictive analysis.
    Includes temperature danger zone assessment for grid strain prediction.
    """
    from src.ingestion.weather import (
        fetch_location_forecast,
        fetch_all_texas_forecasts,
        TEXAS_FORECAST_LOCATIONS,
    )
    
    if location:
        location = location.upper()
        if location not in TEXAS_FORECAST_LOCATIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid location. Must be one of: {list(TEXAS_FORECAST_LOCATIONS.keys())}",
            )
        forecast = fetch_location_forecast(location)
        if not forecast:
            raise HTTPException(status_code=503, detail="Unable to fetch forecast from NWS")
        forecasts = {location: forecast.to_dict()}
    else:
        forecasts_obj = fetch_all_texas_forecasts()
        forecasts = {k: v.to_dict() for k, v in forecasts_obj.items()}
    
    return {
        "status": "success",
        "forecasts": forecasts,
        "locations_available": list(TEXAS_FORECAST_LOCATIONS.keys()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/weather/alerts", tags=["Weather"])
def get_weather_alerts(
    state: str = Query("TX", description="State code (default: TX)"),
    critical_only: bool = Query(False, description="Only return critical alerts"),
):
    """
    Get active weather alerts from NWS.
    
    Returns alerts that may impact physical systems (grid, port, water).
    """
    from src.ingestion.weather import fetch_alerts
    
    alerts = fetch_alerts(state.upper())
    
    if critical_only:
        alerts = [a for a in alerts if a.is_critical]
    
    return {
        "status": "success",
        "alerts": [a.to_dict() for a in alerts],
        "count": len(alerts),
        "critical_count": sum(1 for a in alerts if a.is_critical),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/weather/danger", tags=["Weather"])
def get_weather_danger_assessment():
    """
    Get temperature danger zone assessment.
    
    Analyzes forecasts for grid strain prediction based on:
    - Extreme heat (>100°F): Extreme grid strain
    - High heat (>98°F): High grid strain danger zone
    - Hard freeze (<25°F): Severe freeze risk (2021 crisis level)
    - Freeze (<32°F): Freeze risk
    
    Used by Linked Fate v4 for predictive correlation.
    """
    from src.ingestion.weather import (
        fetch_all_texas_forecasts,
        assess_temperature_danger,
        TEMPERATURE_THRESHOLDS,
    )
    
    forecasts = fetch_all_texas_forecasts()
    danger = assess_temperature_danger(forecasts)
    
    return {
        "status": "success",
        "danger_assessment": danger,
        "thresholds": TEMPERATURE_THRESHOLDS,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/weather/predictive-alerts", tags=["Weather"])
def get_predictive_alerts_endpoint():
    """
    Get predictive alerts based on weather forecasts.
    
    Generates anticipatory alerts for:
    - Extreme grid strain (high temps in 48h)
    - Freeze emergencies (low temps in 48h)
    - Port disruptions (hurricane/storm warnings)
    
    Used by ticker tray for [PREDICTIVE] alert display.
    """
    from src.ingestion.weather import get_predictive_alerts
    
    alerts = get_predictive_alerts()
    
    return {
        "status": "success",
        "predictive_alerts": alerts,
        "count": len(alerts),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/weather/summary", tags=["Weather"])
def get_weather_summary_endpoint():
    """
    Get complete weather summary for Texas.
    
    Includes forecasts, alerts, and danger assessments aggregated
    for terminal display.
    """
    from src.ingestion.weather import get_weather_summary
    
    summary = get_weather_summary()
    
    return {
        "status": "success",
        **summary,
    }
