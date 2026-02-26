"""
Market Correlation Engine (Linked Fate v2)

Cross-references physical scarcity alerts with financial market movements
to detect market reactions to physical events in real-time.

Phase 3: The Financial Intersection

Correlation Rules:
- IF (GRID STRAIN/EMERGENCY) AND (VST/NRG moving >2%) -> MARKET_REACTION: ENERGY_STRAIN
- IF (AQUIFER CRITICAL/DROUGHT) AND (TXN moving >2%) -> MARKET_REACTION: WATER_STRESS  
- IF (PORT CONGESTION/GRIDLOCK) AND (relevant stock moving >2%) -> MARKET_REACTION: SUPPLY_CHAIN
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from typing import Any, Optional

import structlog

from src.db.connection import get_db_session
from src.db.models import Alert

logger = structlog.get_logger(__name__)


class CorrelationLevel(IntEnum):
    """Correlation confidence levels."""
    NONE = 0
    WEAK = 1
    MODERATE = 2
    STRONG = 3


@dataclass
class MarketCorrelation:
    """Represents a detected market-physical correlation."""
    correlation_type: str
    symbol: str
    market_move_percent: float
    market_direction: str
    physical_alert_code: str
    physical_alert_level: str
    confidence: CorrelationLevel
    message: str
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_type": self.correlation_type,
            "symbol": self.symbol,
            "market_move_percent": self.market_move_percent,
            "market_direction": self.market_direction,
            "physical_alert_code": self.physical_alert_code,
            "physical_alert_level": self.physical_alert_level,
            "confidence": self.confidence.name,
            "message": self.message,
            "detected_at": self.detected_at.isoformat(),
            "metadata": self.metadata,
        }


# ─────────────────────────────────────────────────────────────
# Correlation Rule Definitions
# ─────────────────────────────────────────────────────────────

# Symbol to physical system mapping
SYMBOL_PHYSICAL_MAP = {
    "VST": {
        "name": "Vistra Corp",
        "physical_systems": ["GRID"],
        "sensitivity": "high",
        "correlation_type": "ENERGY_STRAIN",
    },
    "NRG": {
        "name": "NRG Energy",
        "physical_systems": ["GRID"],
        "sensitivity": "high",
        "correlation_type": "ENERGY_STRAIN",
    },
    "TXN": {
        "name": "Texas Instruments",
        "physical_systems": ["WATR", "GRID"],
        "sensitivity": "medium",
        "correlation_type": "WATER_STRESS",
    },
}

# Physical alert codes that trigger correlation checks
GRID_ALERT_CODES = ["GRID_STRAIN", "GRID_EMERGENCY", "GRID_MARGIN_LOW"]
WATER_ALERT_CODES = ["AQUIFER_CRITICAL", "DROUGHT_RISK", "AQUIFER_DECLINING"]
PORT_ALERT_CODES = ["PORT_GRIDLOCK", "PORT_CONGESTION", "PORT_BUSY"]

# Movement thresholds for correlation
CORRELATION_THRESHOLDS = {
    "weak": 1.0,      # 1% move
    "moderate": 2.0,  # 2% move - triggers alert
    "strong": 5.0,    # 5% move - high confidence correlation
}


# ─────────────────────────────────────────────────────────────
# Core Correlation Functions
# ─────────────────────────────────────────────────────────────

def get_active_physical_alerts() -> dict[str, list[dict]]:
    """
    Get currently active physical alerts from database.
    
    Returns:
        Dict mapping alert type to list of alerts
    """
    with get_db_session() as db:
        # Get alerts from last 30 minutes
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        
        alerts = (
            db.query(Alert)
            .filter(Alert.is_active == True)
            .filter(Alert.triggered_at >= cutoff)
            .all()
        )
        
        # Group by type
        alerts_by_type = {
            "GRID": [],
            "WATR": [],
            "FLOW": [],
            "LINKED": [],
        }
        
        for alert in alerts:
            alert_dict = {
                "alert_id": alert.alert_id,
                "title": alert.title,
                "level": alert.alert_level,
                "message": alert.message,
                "triggered_at": alert.triggered_at,
            }
            
            if alert.alert_type in alerts_by_type:
                alerts_by_type[alert.alert_type].append(alert_dict)
        
        return alerts_by_type


def get_market_data() -> dict[str, dict]:
    """
    Get current market data for watchlist.
    
    Returns:
        Dict mapping symbol to quote data
    """
    from src.ingestion.finance import fetch_watchlist_quotes
    
    quotes = fetch_watchlist_quotes()
    
    return {
        q.symbol: {
            "name": q.name,
            "price": q.price,
            "change_percent": q.change_percent,
            "direction": "UP" if q.change_percent > 0 else "DOWN",
            "volume": q.volume,
        }
        for q in quotes
    }


def check_energy_correlation(
    market_data: dict[str, dict],
    grid_alerts: list[dict],
) -> list[MarketCorrelation]:
    """
    Check for energy sector market-physical correlations.
    
    Rule: IF (GRID STRAIN) AND (VST/NRG moving >2%) -> MARKET_REACTION: ENERGY_STRAIN
    """
    correlations = []
    
    if not grid_alerts:
        return correlations
    
    # Get the most severe grid alert
    level_priority = {"NORMAL": 0, "WATCH": 1, "WARNING": 2, "CRITICAL": 3}
    most_severe = max(grid_alerts, key=lambda a: level_priority.get(a["level"], 0))
    
    # Only check if WARNING or CRITICAL
    if most_severe["level"] not in ["WARNING", "CRITICAL"]:
        return correlations
    
    # Check energy stocks
    for symbol in ["VST", "NRG"]:
        if symbol not in market_data:
            continue
            
        quote = market_data[symbol]
        abs_move = abs(quote["change_percent"])
        
        if abs_move >= CORRELATION_THRESHOLDS["moderate"]:
            # Determine confidence
            if abs_move >= CORRELATION_THRESHOLDS["strong"]:
                confidence = CorrelationLevel.STRONG
            elif abs_move >= CORRELATION_THRESHOLDS["moderate"]:
                confidence = CorrelationLevel.MODERATE
            else:
                confidence = CorrelationLevel.WEAK
            
            # Build correlation
            correlation = MarketCorrelation(
                correlation_type="ENERGY_STRAIN",
                symbol=symbol,
                market_move_percent=quote["change_percent"],
                market_direction=quote["direction"],
                physical_alert_code=most_severe["title"],
                physical_alert_level=most_severe["level"],
                confidence=confidence,
                message=f"MARKET REACTION: {symbol} {quote['direction']} {abs_move:.1f}% while ERCOT grid under {most_severe['level']} conditions",
                metadata={
                    "stock_name": quote["name"],
                    "grid_message": most_severe["message"],
                },
            )
            correlations.append(correlation)
            
            logger.info(
                "energy_correlation_detected",
                symbol=symbol,
                move=f"{quote['direction']} {abs_move:.1f}%",
                grid_level=most_severe["level"],
                confidence=confidence.name,
            )
    
    return correlations


def check_water_correlation(
    market_data: dict[str, dict],
    water_alerts: list[dict],
) -> list[MarketCorrelation]:
    """
    Check for water-dependent sector market-physical correlations.
    
    Rule: IF (AQUIFER CRITICAL) AND (TXN moving >2%) -> MARKET_REACTION: WATER_STRESS
    """
    correlations = []
    
    if not water_alerts:
        return correlations
    
    # Get the most severe water alert
    level_priority = {"NORMAL": 0, "WATCH": 1, "WARNING": 2, "CRITICAL": 3}
    most_severe = max(water_alerts, key=lambda a: level_priority.get(a["level"], 0))
    
    # Only check if WARNING or CRITICAL
    if most_severe["level"] not in ["WARNING", "CRITICAL"]:
        return correlations
    
    # Check water-dependent stocks (TXN - semiconductor fabs need water)
    for symbol in ["TXN"]:
        if symbol not in market_data:
            continue
            
        quote = market_data[symbol]
        abs_move = abs(quote["change_percent"])
        
        if abs_move >= CORRELATION_THRESHOLDS["moderate"]:
            # Determine confidence
            if abs_move >= CORRELATION_THRESHOLDS["strong"]:
                confidence = CorrelationLevel.STRONG
            elif abs_move >= CORRELATION_THRESHOLDS["moderate"]:
                confidence = CorrelationLevel.MODERATE
            else:
                confidence = CorrelationLevel.WEAK
            
            # Build correlation
            correlation = MarketCorrelation(
                correlation_type="WATER_STRESS",
                symbol=symbol,
                market_move_percent=quote["change_percent"],
                market_direction=quote["direction"],
                physical_alert_code=most_severe["title"],
                physical_alert_level=most_severe["level"],
                confidence=confidence,
                message=f"MARKET REACTION: {symbol} {quote['direction']} {abs_move:.1f}% during Texas water {most_severe['level']}",
                metadata={
                    "stock_name": quote["name"],
                    "water_message": most_severe["message"],
                },
            )
            correlations.append(correlation)
            
            logger.info(
                "water_correlation_detected",
                symbol=symbol,
                move=f"{quote['direction']} {abs_move:.1f}%",
                water_level=most_severe["level"],
                confidence=confidence.name,
            )
    
    return correlations


def check_supply_chain_correlation(
    market_data: dict[str, dict],
    port_alerts: list[dict],
) -> list[MarketCorrelation]:
    """
    Check for supply chain market-physical correlations.
    
    Rule: IF (PORT CONGESTION) AND (relevant stocks moving >2%) -> MARKET_REACTION: SUPPLY_CHAIN
    """
    correlations = []
    
    if not port_alerts:
        return correlations
    
    # Get the most severe port alert
    level_priority = {"NORMAL": 0, "WATCH": 1, "WARNING": 2, "CRITICAL": 3}
    most_severe = max(port_alerts, key=lambda a: level_priority.get(a["level"], 0))
    
    # Only check if WARNING or CRITICAL
    if most_severe["level"] not in ["WARNING", "CRITICAL"]:
        return correlations
    
    # Currently TXN is also supply-chain dependent
    # Future: Add logistics/shipping stocks when available
    for symbol in ["TXN"]:
        if symbol not in market_data:
            continue
            
        quote = market_data[symbol]
        abs_move = abs(quote["change_percent"])
        
        if abs_move >= CORRELATION_THRESHOLDS["moderate"]:
            # Determine confidence
            if abs_move >= CORRELATION_THRESHOLDS["strong"]:
                confidence = CorrelationLevel.STRONG
            elif abs_move >= CORRELATION_THRESHOLDS["moderate"]:
                confidence = CorrelationLevel.MODERATE
            else:
                confidence = CorrelationLevel.WEAK
            
            # Build correlation
            correlation = MarketCorrelation(
                correlation_type="SUPPLY_CHAIN",
                symbol=symbol,
                market_move_percent=quote["change_percent"],
                market_direction=quote["direction"],
                physical_alert_code=most_severe["title"],
                physical_alert_level=most_severe["level"],
                confidence=confidence,
                message=f"MARKET REACTION: {symbol} {quote['direction']} {abs_move:.1f}% during Port of Houston {most_severe['level']}",
                metadata={
                    "stock_name": quote["name"],
                    "port_message": most_severe["message"],
                },
            )
            correlations.append(correlation)
            
            logger.info(
                "supply_chain_correlation_detected",
                symbol=symbol,
                move=f"{quote['direction']} {abs_move:.1f}%",
                port_level=most_severe["level"],
                confidence=confidence.name,
            )
    
    return correlations


# ─────────────────────────────────────────────────────────────
# Alert Generation
# ─────────────────────────────────────────────────────────────

def store_market_correlation_alerts(correlations: list[MarketCorrelation]) -> int:
    """
    Store market correlation alerts in the database.
    
    Args:
        correlations: List of detected correlations
        
    Returns:
        Number of alerts stored
    """
    if not correlations:
        return 0
    
    stored = 0
    
    with get_db_session() as db:
        for correlation in correlations:
            # Create alert
            alert = Alert(
                alert_type="MARKET",
                alert_level="WARNING" if correlation.confidence >= CorrelationLevel.MODERATE else "WATCH",
                region_code="US-TX",
                title=f"Market Reaction: {correlation.correlation_type}",
                message=correlation.message,
                indicator_values={
                    "symbol": correlation.symbol,
                    "change_percent": correlation.market_move_percent,
                    "direction": correlation.market_direction,
                    "physical_alert": correlation.physical_alert_code,
                    "confidence": correlation.confidence.name,
                },
                triggered_at=correlation.detected_at,
                is_active=True,
                metadata_=correlation.metadata,
            )
            db.add(alert)
            stored += 1
        
        db.commit()
    
    return stored


# ─────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────

def evaluate_market_correlations() -> dict[str, Any]:
    """
    Main entry point for market correlation evaluation.
    Called by the scheduler every 5 minutes.
    
    Implements Linked Fate v2:
    1. Fetch current physical alerts
    2. Fetch current market data
    3. Check for correlations across all rule types
    4. Generate and store correlation alerts
    
    Returns:
        Dict with evaluation summary
    """
    logger.info("market_correlation_evaluation_started")
    
    try:
        # Get physical alerts
        physical_alerts = get_active_physical_alerts()
        
        # Get market data
        market_data = get_market_data()
        
        if not market_data:
            return {
                "status": "no_market_data",
                "message": "Unable to fetch market data",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        
        # Check all correlation types
        all_correlations = []
        
        # Energy correlations (GRID + VST/NRG)
        energy_correlations = check_energy_correlation(
            market_data, physical_alerts.get("GRID", [])
        )
        all_correlations.extend(energy_correlations)
        
        # Water correlations (WATR + TXN)
        water_correlations = check_water_correlation(
            market_data, physical_alerts.get("WATR", [])
        )
        all_correlations.extend(water_correlations)
        
        # Supply chain correlations (FLOW/PORT + various)
        supply_correlations = check_supply_chain_correlation(
            market_data, physical_alerts.get("FLOW", [])
        )
        all_correlations.extend(supply_correlations)
        
        # Store alerts
        stored_count = store_market_correlation_alerts(all_correlations)
        
        # Build summary
        summary = {
            "status": "completed",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "physical_alerts": {
                "grid": len(physical_alerts.get("GRID", [])),
                "water": len(physical_alerts.get("WATR", [])),
                "port": len(physical_alerts.get("FLOW", [])),
            },
            "market_symbols_checked": len(market_data),
            "correlations_detected": len(all_correlations),
            "alerts_stored": stored_count,
            "correlations": [c.to_dict() for c in all_correlations],
        }
        
        logger.info(
            "market_correlation_evaluation_completed",
            correlations=len(all_correlations),
            stored=stored_count,
        )
        
        return summary
        
    except Exception as e:
        logger.error("market_correlation_evaluation_error", error=str(e))
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
