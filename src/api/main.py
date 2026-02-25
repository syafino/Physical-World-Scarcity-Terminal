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
from src.db.models import Anomaly, Indicator, Observation, Region, Station

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
        elif function_code == "RISK":
            data, anomalies = execute_risk(db, region_code)
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
