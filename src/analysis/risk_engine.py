"""
PWST Linked Fate Risk Engine

Implements threshold-based alerting and multi-signal correlation rules.
Evaluates current conditions across GRID, WATR, and FLOW feeds to
generate real-time risk alerts.

Alert Severity Levels:
- 0: NORMAL - Within expected parameters
- 1: WATCH - Approaching threshold  
- 2: WARNING - Threshold breached
- 3: CRITICAL - Multiple thresholds / cascading risk
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from typing import Any, Optional

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.connection import get_db_session
from src.db.models import Alert, Anomaly, Indicator, Observation, Station

logger = structlog.get_logger(__name__)


class AlertLevel(IntEnum):
    """Alert severity levels."""
    NORMAL = 0
    WATCH = 1
    WARNING = 2
    CRITICAL = 3


@dataclass
class RiskAlert:
    """Represents a single risk alert."""
    code: str
    level: AlertLevel
    message: str
    indicator_code: Optional[str] = None
    value: Optional[float] = None
    threshold: Optional[float] = None
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "level": self.level.value,
            "level_name": self.level.name,
            "message": self.message,
            "indicator_code": self.indicator_code,
            "value": self.value,
            "threshold": self.threshold,
            "detected_at": self.detected_at.isoformat(),
            "metadata": self.metadata,
        }


# ─────────────────────────────────────────────────────────────
# Threshold Definitions
# ─────────────────────────────────────────────────────────────

# GRID (ERCOT) Thresholds
GRID_THRESHOLDS = {
    # Reserve margin = (Generation - Demand) / Generation * 100
    "reserve_margin_watch": 10.0,      # Below 10% = WATCH
    "reserve_margin_warning": 5.0,     # Below 5% = WARNING
    "reserve_margin_critical": 3.0,    # Below 3% = CRITICAL
    "demand_capacity_critical": 0.95,  # Demand > 95% of generation = CRITICAL
}

# WATR (Groundwater) Thresholds
WATR_THRESHOLDS = {
    "z_score_watch": 1.0,       # 1σ below mean = WATCH
    "z_score_warning": 2.0,     # 2σ below mean = WARNING  
    "z_score_critical": 3.0,    # 3σ below mean = CRITICAL
    "decline_rate_critical": 0.5,  # >0.5m/week decline = CRITICAL
}

# FLOW (Port) Thresholds
FLOW_THRESHOLDS = {
    "vessels_waiting_watch": 5,      # >5 waiting = WATCH
    "vessels_waiting_warning": 15,   # >15 waiting = WARNING
    "vessels_waiting_critical": 30,  # >30 waiting = CRITICAL
    "dwell_time_warning": 72,        # >72 hours dwell = WARNING
    "dwell_time_critical": 96,       # >96 hours dwell = CRITICAL
}


# ─────────────────────────────────────────────────────────────
# Individual Feed Evaluators
# ─────────────────────────────────────────────────────────────

def evaluate_grid_risk(db: Session) -> list[RiskAlert]:
    """Evaluate ERCOT grid risk based on current conditions."""
    alerts = []
    
    # Get latest grid observations
    demand_ind = db.query(Indicator).filter_by(code="GRID_DEMAND").first()
    gen_ind = db.query(Indicator).filter_by(code="GRID_GENERATION").first()
    
    if not demand_ind:
        return alerts
    
    # Get latest demand
    latest_demand = (
        db.query(Observation)
        .filter(Observation.indicator_id == demand_ind.indicator_id)
        .order_by(Observation.observed_at.desc())
        .first()
    )
    
    latest_gen = None
    if gen_ind:
        latest_gen = (
            db.query(Observation)
            .filter(Observation.indicator_id == gen_ind.indicator_id)
            .order_by(Observation.observed_at.desc())
            .first()
        )
    
    if not latest_demand:
        return alerts
        
    demand = latest_demand.value
    
    # If we have generation data, calculate reserve margin
    if latest_gen and latest_gen.value > 0:
        generation = latest_gen.value
        reserve_margin = ((generation - demand) / generation) * 100
        
        if reserve_margin < GRID_THRESHOLDS["reserve_margin_critical"]:
            alerts.append(RiskAlert(
                code="GRID_EMERGENCY",
                level=AlertLevel.CRITICAL,
                message=f"ERCOT RESERVE MARGIN CRITICAL: {reserve_margin:.1f}%",
                indicator_code="GRID_DEMAND",
                value=reserve_margin,
                threshold=GRID_THRESHOLDS["reserve_margin_critical"],
                metadata={"demand": demand, "generation": generation},
            ))
        elif reserve_margin < GRID_THRESHOLDS["reserve_margin_warning"]:
            alerts.append(RiskAlert(
                code="GRID_STRAIN",
                level=AlertLevel.WARNING,
                message=f"ERCOT RESERVE MARGIN LOW: {reserve_margin:.1f}%",
                indicator_code="GRID_DEMAND",
                value=reserve_margin,
                threshold=GRID_THRESHOLDS["reserve_margin_warning"],
                metadata={"demand": demand, "generation": generation},
            ))
        elif reserve_margin < GRID_THRESHOLDS["reserve_margin_watch"]:
            alerts.append(RiskAlert(
                code="GRID_MARGIN_LOW",
                level=AlertLevel.WATCH,
                message=f"ERCOT Reserve Margin: {reserve_margin:.1f}%",
                indicator_code="GRID_DEMAND",
                value=reserve_margin,
                threshold=GRID_THRESHOLDS["reserve_margin_watch"],
            ))
        else:
            alerts.append(RiskAlert(
                code="GRID_NORMAL",
                level=AlertLevel.NORMAL,
                message=f"ERCOT Grid Normal: {demand:,.0f} MW demand",
                indicator_code="GRID_DEMAND",
                value=demand,
            ))
    else:
        # No generation data, just report demand
        alerts.append(RiskAlert(
            code="GRID_NORMAL",
            level=AlertLevel.NORMAL,
            message=f"ERCOT Demand: {demand:,.0f} MW",
            indicator_code="GRID_DEMAND",
            value=demand,
        ))
    
    logger.debug("grid_risk_evaluated", alerts=len(alerts))
    return alerts


def evaluate_water_risk(db: Session) -> list[RiskAlert]:
    """Evaluate groundwater risk based on current conditions."""
    alerts = []
    
    # Get groundwater indicator
    gw_ind = db.query(Indicator).filter_by(code="GW_LEVEL").first()
    if not gw_ind:
        return alerts
    
    # Get recent observations (last 24h)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    
    observations = (
        db.query(Observation, Station)
        .join(Station, Observation.station_id == Station.station_id)
        .filter(Observation.indicator_id == gw_ind.indicator_id)
        .filter(Observation.observed_at >= cutoff)
        .all()
    )
    
    if not observations:
        alerts.append(RiskAlert(
            code="WATR_NORMAL",
            level=AlertLevel.NORMAL,
            message="Groundwater levels stable",
            indicator_code="GW_LEVEL",
        ))
        return alerts
    
    # Calculate statistics
    values = [obs.value for obs, _ in observations]
    avg_level = sum(values) / len(values)
    
    # Check for recent anomalies
    anomaly_count = (
        db.query(Anomaly)
        .filter(Anomaly.indicator_id == gw_ind.indicator_id)
        .filter(Anomaly.detected_at >= cutoff)
        .filter(Anomaly.is_acknowledged == False)
        .count()
    )
    
    critical_anomalies = (
        db.query(Anomaly)
        .filter(Anomaly.indicator_id == gw_ind.indicator_id)
        .filter(Anomaly.detected_at >= cutoff)
        .filter(Anomaly.severity >= 0.75)
        .filter(Anomaly.is_acknowledged == False)
        .count()
    )
    
    if critical_anomalies > 0:
        alerts.append(RiskAlert(
            code="AQUIFER_CRITICAL",
            level=AlertLevel.CRITICAL,
            message=f"CRITICAL: {critical_anomalies} aquifer anomalies detected",
            indicator_code="GW_LEVEL",
            value=critical_anomalies,
            metadata={"total_anomalies": anomaly_count, "avg_level": avg_level},
        ))
    elif anomaly_count > 3:
        alerts.append(RiskAlert(
            code="DROUGHT_RISK",
            level=AlertLevel.WARNING,
            message=f"WARNING: {anomaly_count} groundwater anomalies",
            indicator_code="GW_LEVEL",
            value=anomaly_count,
            metadata={"avg_level": avg_level},
        ))
    elif anomaly_count > 0:
        alerts.append(RiskAlert(
            code="AQUIFER_DECLINING",
            level=AlertLevel.WATCH,
            message=f"WATCH: {anomaly_count} minor groundwater anomalies",
            indicator_code="GW_LEVEL",
            value=anomaly_count,
        ))
    else:
        alerts.append(RiskAlert(
            code="WATR_NORMAL",
            level=AlertLevel.NORMAL,
            message=f"Groundwater levels normal ({len(observations)} stations)",
            indicator_code="GW_LEVEL",
            value=avg_level,
        ))
    
    logger.debug("water_risk_evaluated", alerts=len(alerts))
    return alerts


def evaluate_port_risk(db: Session) -> list[RiskAlert]:
    """Evaluate port/logistics risk based on current conditions."""
    alerts = []
    
    # Get port indicators
    waiting_ind = db.query(Indicator).filter_by(code="PORT_WAITING").first()
    dwell_ind = db.query(Indicator).filter_by(code="PORT_DWELL").first()
    
    if not waiting_ind:
        return alerts
    
    # Get latest observations for vessels waiting
    latest_waiting = (
        db.query(Observation, Station)
        .join(Station, Observation.station_id == Station.station_id)
        .filter(Observation.indicator_id == waiting_ind.indicator_id)
        .order_by(Observation.observed_at.desc())
        .first()
    )
    
    latest_dwell = None
    if dwell_ind:
        latest_dwell = (
            db.query(Observation)
            .filter(Observation.indicator_id == dwell_ind.indicator_id)
            .order_by(Observation.observed_at.desc())
            .first()
        )
    
    if not latest_waiting:
        return alerts
    
    waiting_obs, station = latest_waiting
    vessels_waiting = waiting_obs.value
    port_name = station.name if station else "Houston"
    
    dwell_time = latest_dwell.value if latest_dwell else 0
    
    # Evaluate waiting vessels threshold
    if vessels_waiting > FLOW_THRESHOLDS["vessels_waiting_critical"] or dwell_time > FLOW_THRESHOLDS["dwell_time_critical"]:
        alerts.append(RiskAlert(
            code="PORT_GRIDLOCK",
            level=AlertLevel.CRITICAL,
            message=f"PORT GRIDLOCK: {vessels_waiting:.0f} vessels waiting at {port_name}",
            indicator_code="PORT_WAITING",
            value=vessels_waiting,
            threshold=FLOW_THRESHOLDS["vessels_waiting_critical"],
            metadata={"port": port_name, "dwell_time": dwell_time},
        ))
    elif vessels_waiting > FLOW_THRESHOLDS["vessels_waiting_warning"] or dwell_time > FLOW_THRESHOLDS["dwell_time_warning"]:
        alerts.append(RiskAlert(
            code="PORT_CONGESTION",
            level=AlertLevel.WARNING,
            message=f"PORT CONGESTION: {vessels_waiting:.0f} vessels waiting",
            indicator_code="PORT_WAITING",
            value=vessels_waiting,
            threshold=FLOW_THRESHOLDS["vessels_waiting_warning"],
            metadata={"port": port_name, "dwell_time": dwell_time},
        ))
    elif vessels_waiting > FLOW_THRESHOLDS["vessels_waiting_watch"]:
        alerts.append(RiskAlert(
            code="PORT_BUSY",
            level=AlertLevel.WATCH,
            message=f"Port traffic elevated: {vessels_waiting:.0f} vessels waiting",
            indicator_code="PORT_WAITING",
            value=vessels_waiting,
            threshold=FLOW_THRESHOLDS["vessels_waiting_watch"],
        ))
    else:
        alerts.append(RiskAlert(
            code="PORT_NORMAL",
            level=AlertLevel.NORMAL,
            message=f"{port_name} normal: {vessels_waiting:.0f} vessels waiting",
            indicator_code="PORT_WAITING",
            value=vessels_waiting,
        ))
    
    logger.debug("port_risk_evaluated", alerts=len(alerts))
    return alerts


# ─────────────────────────────────────────────────────────────
# Linked Fate (Multi-Signal Correlation)
# ─────────────────────────────────────────────────────────────

def evaluate_linked_fate(
    grid_alerts: list[RiskAlert],
    water_alerts: list[RiskAlert],
    port_alerts: list[RiskAlert],
) -> list[RiskAlert]:
    """
    Evaluate cascading/correlated risks across multiple feeds.
    
    Implements the "Linked Fate" rules:
    - TEXAS_SUPPLY_CHAIN_CRITICAL: Grid + Port stress
    - TEXAS_INFRASTRUCTURE_STRESS: Water + Grid stress
    - TEXAS_PERFECT_STORM: All three feeds in WARNING+
    """
    linked_alerts = []
    
    # Get max severity for each feed
    grid_max = max((a.level for a in grid_alerts), default=AlertLevel.NORMAL)
    water_max = max((a.level for a in water_alerts), default=AlertLevel.NORMAL)
    port_max = max((a.level for a in port_alerts), default=AlertLevel.NORMAL)
    
    # RULE: TEXAS_PERFECT_STORM
    # All three feeds at WARNING or higher
    if grid_max >= AlertLevel.WARNING and water_max >= AlertLevel.WARNING and port_max >= AlertLevel.WARNING:
        linked_alerts.append(RiskAlert(
            code="TEXAS_PERFECT_STORM",
            level=AlertLevel.CRITICAL,
            message="⚠️ PERFECT STORM: Grid strain + Drought + Port congestion",
            metadata={
                "grid_level": grid_max.name,
                "water_level": water_max.name,
                "port_level": port_max.name,
            },
        ))
        logger.warning("linked_fate_triggered", rule="TEXAS_PERFECT_STORM")
        return linked_alerts  # Don't stack with lesser alerts
    
    # RULE: TEXAS_SUPPLY_CHAIN_CRITICAL
    # Grid stress + Port congestion
    if grid_max >= AlertLevel.WARNING and port_max >= AlertLevel.WARNING:
        combined_severity = max(grid_max, port_max)
        linked_alerts.append(RiskAlert(
            code="TEXAS_SUPPLY_CHAIN_CRITICAL",
            level=AlertLevel.CRITICAL if combined_severity == AlertLevel.CRITICAL else AlertLevel.WARNING,
            message="SUPPLY CHAIN RISK: Grid strain + Port congestion",
            metadata={
                "grid_level": grid_max.name,
                "port_level": port_max.name,
            },
        ))
        logger.warning("linked_fate_triggered", rule="TEXAS_SUPPLY_CHAIN_CRITICAL")
    
    # RULE: TEXAS_INFRASTRUCTURE_STRESS
    # Water crisis + Grid stress
    if water_max >= AlertLevel.WARNING and grid_max >= AlertLevel.WARNING:
        combined_severity = max(water_max, grid_max)
        linked_alerts.append(RiskAlert(
            code="TEXAS_INFRASTRUCTURE_STRESS",
            level=AlertLevel.CRITICAL if combined_severity == AlertLevel.CRITICAL else AlertLevel.WARNING,
            message="INFRASTRUCTURE STRESS: Drought conditions + Grid strain",
            metadata={
                "water_level": water_max.name,
                "grid_level": grid_max.name,
            },
        ))
        logger.warning("linked_fate_triggered", rule="TEXAS_INFRASTRUCTURE_STRESS")
    
    return linked_alerts


# ─────────────────────────────────────────────────────────────
# Main Evaluation Entry Point
# ─────────────────────────────────────────────────────────────

def evaluate_all_risks() -> dict[str, Any]:
    """
    Main entry point for risk evaluation.
    Called by the scheduler every 5 minutes.
    
    Returns:
        Dict with evaluation summary and all active alerts
    """
    with get_db_session() as db:
        # Evaluate individual feeds
        grid_alerts = evaluate_grid_risk(db)
        water_alerts = evaluate_water_risk(db)
        port_alerts = evaluate_port_risk(db)
        
        # Evaluate linked fate rules
        linked_alerts = evaluate_linked_fate(grid_alerts, water_alerts, port_alerts)
        
        # Combine all alerts
        all_alerts = linked_alerts + grid_alerts + water_alerts + port_alerts
        
        # Sort by severity (highest first)
        all_alerts.sort(key=lambda a: a.level, reverse=True)
        
        # Store alerts in database for ticker consumption
        store_alerts(db, all_alerts)
        
        # Build summary
        summary = {
            "status": "completed",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "total_alerts": len(all_alerts),
            "critical_count": sum(1 for a in all_alerts if a.level == AlertLevel.CRITICAL),
            "warning_count": sum(1 for a in all_alerts if a.level == AlertLevel.WARNING),
            "watch_count": sum(1 for a in all_alerts if a.level == AlertLevel.WATCH),
            "alerts": [a.to_dict() for a in all_alerts],
        }
        
        logger.info(
            "risk_evaluation_completed",
            total=len(all_alerts),
            critical=summary["critical_count"],
            warning=summary["warning_count"],
        )
        
        return summary


def store_alerts(db: Session, alerts: list[RiskAlert]) -> None:
    """Store alerts in database for ticker tray consumption."""
    # Deactivate old alerts (older than 1 hour)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    db.query(Alert).filter(Alert.triggered_at < cutoff).update({"is_active": False})
    
    # Insert new alerts
    for alert in alerts:
        # Determine alert type from code
        alert_type = "SYSTEM"
        if alert.code.startswith("GRID"):
            alert_type = "GRID"
        elif alert.code.startswith("WATR"):
            alert_type = "WATR"
        elif alert.code.startswith("FLOW") or alert.code.startswith("PORT"):
            alert_type = "FLOW"
        elif alert.code.startswith("LINKED") or "TEXAS" in alert.code:
            alert_type = "LINKED"
        
        # Map alert level
        level_name = AlertLevel(alert.level).name if isinstance(alert.level, int) else alert.level.name
        
        db_alert = Alert(
            alert_type=alert_type,
            alert_level=level_name,
            region_code=alert.metadata.get("region_code"),
            title=alert.code.replace("_", " ").title(),
            message=alert.message,
            indicator_values={
                "indicator_code": alert.indicator_code,
                "value": alert.value,
                "threshold": alert.threshold,
            },
            triggered_at=alert.detected_at,
            is_active=True,
            metadata_=alert.metadata,
        )
        db.add(db_alert)
    
    db.commit()


def get_active_alerts() -> list[dict[str, Any]]:
    """Get current active alerts for ticker display."""
    with get_db_session() as db:
        # Get active alerts from last 30 minutes
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        
        alerts = (
            db.query(Alert)
            .filter(Alert.is_active == True)
            .filter(Alert.triggered_at >= cutoff)
            .order_by(Alert.triggered_at.desc())
            .all()
        )
        
        return [
            {
                "alert_id": a.alert_id,
                "alert_type": a.alert_type,
                "alert_level": a.alert_level,
                "region_code": a.region_code,
                "title": a.title,
                "message": a.message,
                "indicator_values": a.indicator_values,
                "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None,
                "is_active": a.is_active,
            }
            for a in alerts
        ]
