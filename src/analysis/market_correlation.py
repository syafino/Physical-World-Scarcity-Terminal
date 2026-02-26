"""
Market Correlation Engine (Linked Fate v4)

Cross-references physical scarcity alerts with financial market movements,
news sentiment, and weather forecasts to detect correlations in real-time
and anticipate future scarcity events.

Phase 3: The Financial Intersection
Phase 4: The Unstructured Data Layer (Sentiment)
Phase 5: The Predictive Layer (Weather)

Correlation Rules (v2 - Market):
- IF (GRID STRAIN/EMERGENCY) AND (VST/NRG moving >2%) -> MARKET_REACTION: ENERGY_STRAIN
- IF (AQUIFER CRITICAL/DROUGHT) AND (TXN moving >2%) -> MARKET_REACTION: WATER_STRESS  
- IF (PORT CONGESTION/GRIDLOCK) AND (relevant stock moving >2%) -> MARKET_REACTION: SUPPLY_CHAIN

Correlation Rules (v3 - Sentiment):
- IF (GRID STRAIN) AND (News Sentiment 'GRID' < -0.5) -> CRITICAL EVENT: PHYSICAL & PUBLIC STRAIN
- IF (WATER ALERT) AND (News Sentiment 'WATER' < -0.5) -> CRITICAL EVENT: WATER CRISIS SENTIMENT
- IF (Physical Alert) AND (Negative Sentiment) AND (Market Move) -> TRIPLE CORRELATION DETECTED

Correlation Rules (v4 - Predictive):
- IF (Forecast Temp > 100°F in 48h) AND (ERCOT Margin < 10%) -> PREDICTIVE: EXTREME GRID STRAIN
- IF (Forecast Temp < 25°F in 48h) -> PREDICTIVE: FREEZE EMERGENCY
- IF (Hurricane/Storm Warning for Houston) -> PREDICTIVE: PORT CHOKEPOINT
- IF (Weather Alert Active) AND (Physical Alert Active) AND (Market Move) -> QUADRUPLE CORRELATION
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

# Sentiment thresholds (Phase 4 - Linked Fate v3)
SENTIMENT_THRESHOLDS = {
    "very_negative": -0.5,    # Critical sentiment - triggers alert
    "negative": -0.2,         # Notable negative sentiment
    "neutral_low": -0.05,
    "neutral_high": 0.05,
    "positive": 0.2,
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
# Sentiment Correlation (Linked Fate v3)
# ─────────────────────────────────────────────────────────────


def get_news_sentiment(category: str) -> float:
    """
    Get current news sentiment for a category.
    
    Args:
        category: GRID, WATER, LOGISTICS, or EQUITY
        
    Returns:
        Sentiment score (-1 to 1), 0 if unavailable
    """
    try:
        from src.ingestion.news import get_sentiment_for_correlation
        return get_sentiment_for_correlation(category)
    except Exception as e:
        logger.warning("news_sentiment_fetch_error", category=category, error=str(e))
        return 0.0  # Neutral fallback


def check_sentiment_correlations(
    physical_alerts: dict[str, list[dict]],
    market_data: dict[str, dict],
) -> list[MarketCorrelation]:
    """
    Check for sentiment-physical correlations (Linked Fate v3).
    
    Rules:
    - IF (Physical Alert Active) AND (News Sentiment < -0.5) -> PHYSICAL_PUBLIC_STRAIN
    - IF (Physical Alert) AND (Negative Sentiment) AND (Market Move >2%) -> TRIPLE_CORRELATION
    
    Args:
        physical_alerts: Dict of alerts by type (GRID, WATR, FLOW)
        market_data: Dict of market quotes by symbol
        
    Returns:
        List of detected sentiment correlations
    """
    correlations = []
    
    # Map physical alert types to news categories and related stocks
    category_mapping = {
        "GRID": {"news_category": "GRID", "symbols": ["VST", "NRG"], "correlation_type": "ENERGY_PUBLIC_STRAIN"},
        "WATR": {"news_category": "WATER", "symbols": ["TXN"], "correlation_type": "WATER_CRISIS_SENTIMENT"},
        "FLOW": {"news_category": "LOGISTICS", "symbols": ["TXN"], "correlation_type": "SUPPLY_CHAIN_SENTIMENT"},
    }
    
    for alert_type, config in category_mapping.items():
        alerts = physical_alerts.get(alert_type, [])
        
        if not alerts:
            continue
        
        # Get the most severe alert
        level_priority = {"NORMAL": 0, "WATCH": 1, "WARNING": 2, "CRITICAL": 3}
        most_severe = max(alerts, key=lambda a: level_priority.get(a["level"], 0))
        
        # Only check if WARNING or CRITICAL
        if most_severe["level"] not in ["WARNING", "CRITICAL"]:
            continue
        
        # Get news sentiment for this category
        sentiment = get_news_sentiment(config["news_category"])
        
        logger.debug(
            "sentiment_check",
            alert_type=alert_type,
            sentiment=sentiment,
            threshold=SENTIMENT_THRESHOLDS["very_negative"],
        )
        
        # Check for physical + public strain (sentiment-only correlation)
        if sentiment <= SENTIMENT_THRESHOLDS["very_negative"]:
            correlation = MarketCorrelation(
                correlation_type=config["correlation_type"],
                symbol="NEWS",  # Not stock-specific
                market_move_percent=0.0,
                market_direction="N/A",
                physical_alert_code=most_severe["title"],
                physical_alert_level=most_severe["level"],
                confidence=CorrelationLevel.STRONG,
                message=f"CRITICAL: {config['news_category']} under physical strain ({most_severe['level']}) with very negative public sentiment ({sentiment:.2f})",
                metadata={
                    "sentiment_score": sentiment,
                    "news_category": config["news_category"],
                    "physical_message": most_severe["message"],
                },
            )
            correlations.append(correlation)
            
            logger.info(
                "sentiment_correlation_detected",
                alert_type=alert_type,
                level=most_severe["level"],
                sentiment=sentiment,
                correlation_type=config["correlation_type"],
            )
        
        # Check for triple correlation (physical + sentiment + market move)
        if sentiment <= SENTIMENT_THRESHOLDS["negative"]:
            for symbol in config["symbols"]:
                if symbol not in market_data:
                    continue
                
                quote = market_data[symbol]
                abs_move = abs(quote["change_percent"])
                
                if abs_move >= CORRELATION_THRESHOLDS["moderate"]:
                    # Triple correlation detected!
                    correlation = MarketCorrelation(
                        correlation_type="TRIPLE_CORRELATION",
                        symbol=symbol,
                        market_move_percent=quote["change_percent"],
                        market_direction=quote["direction"],
                        physical_alert_code=most_severe["title"],
                        physical_alert_level=most_severe["level"],
                        confidence=CorrelationLevel.STRONG,
                        message=f"TRIPLE ALERT: {symbol} {quote['direction']} {abs_move:.1f}% + {config['news_category']} {most_severe['level']} + Negative Sentiment ({sentiment:.2f})",
                        metadata={
                            "sentiment_score": sentiment,
                            "news_category": config["news_category"],
                            "stock_name": quote["name"],
                            "physical_message": most_severe["message"],
                            "market_move": f"{quote['direction']} {abs_move:.1f}%",
                        },
                    )
                    correlations.append(correlation)
                    
                    logger.warning(
                        "triple_correlation_detected",
                        symbol=symbol,
                        alert_type=alert_type,
                        level=most_severe["level"],
                        sentiment=sentiment,
                        market_move=f"{quote['direction']} {abs_move:.1f}%",
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
        
        # Phase 4: Sentiment correlations (Linked Fate v3)
        sentiment_correlations = check_sentiment_correlations(
            physical_alerts, market_data
        )
        all_correlations.extend(sentiment_correlations)
        
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


# ─────────────────────────────────────────────────────────────
# Predictive Correlation (Linked Fate v4)
# ─────────────────────────────────────────────────────────────


@dataclass
class PredictiveCorrelation:
    """Represents a predictive weather-physical correlation."""
    correlation_type: str
    forecast_event: str
    forecast_value: Optional[float]
    physical_system: str
    physical_status: str
    prediction_window: str  # e.g., "48h", "7d"
    confidence: CorrelationLevel
    message: str
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_type": self.correlation_type,
            "forecast_event": self.forecast_event,
            "forecast_value": self.forecast_value,
            "physical_system": self.physical_system,
            "physical_status": self.physical_status,
            "prediction_window": self.prediction_window,
            "confidence": self.confidence.name,
            "message": self.message,
            "detected_at": self.detected_at.isoformat(),
            "metadata": self.metadata,
        }


def get_weather_danger() -> dict[str, Any]:
    """
    Get current weather danger assessment.
    
    Returns:
        Dict with danger assessment for each location
    """
    try:
        from src.ingestion.weather import (
            fetch_all_texas_forecasts,
            assess_temperature_danger,
        )
        
        forecasts = fetch_all_texas_forecasts()
        danger = assess_temperature_danger(forecasts)
        return danger
    except Exception as e:
        logger.warning("weather_danger_fetch_error", error=str(e))
        return {"overall": {}, "locations": {}}


def get_current_grid_margin() -> float:
    """
    Get current ERCOT grid margin (generation - demand / generation).
    
    Returns:
        Grid margin as percentage (0-100), or -1 if unavailable
    """
    with get_db_session() as db:
        from src.db.models import Indicator, Observation
        
        # Get latest grid data
        demand_ind = db.query(Indicator).filter_by(code="GRID_DEMAND").first()
        gen_ind = db.query(Indicator).filter_by(code="GRID_GENERATION").first()
        
        if not demand_ind or not gen_ind:
            return -1
        
        demand_obs = (
            db.query(Observation)
            .filter(Observation.indicator_id == demand_ind.indicator_id)
            .order_by(Observation.observed_at.desc())
            .first()
        )
        
        gen_obs = (
            db.query(Observation)
            .filter(Observation.indicator_id == gen_ind.indicator_id)
            .order_by(Observation.observed_at.desc())
            .first()
        )
        
        if not demand_obs or not gen_obs:
            return -1
        
        # Calculate margin
        if gen_obs.value > 0:
            margin = ((gen_obs.value - demand_obs.value) / gen_obs.value) * 100
            return margin
        
        return -1


def check_predictive_grid_correlations(
    danger: dict[str, Any],
    physical_alerts: dict[str, list[dict]],
    grid_margin: float,
) -> list[PredictiveCorrelation]:
    """
    Check for predictive grid strain correlations.
    
    Rules:
    - IF (Forecast Temp > 100°F in 48h) AND (ERCOT Margin < 10%) -> PREDICTIVE: EXTREME GRID STRAIN
    - IF (Forecast Temp > 98°F in 48h) -> PREDICTIVE: HIGH GRID STRAIN RISK
    - IF (Forecast Temp < 25°F in 48h) -> PREDICTIVE: FREEZE EMERGENCY
    
    Args:
        danger: Weather danger assessment
        physical_alerts: Current physical alerts
        grid_margin: Current ERCOT grid margin percentage
        
    Returns:
        List of detected predictive correlations
    """
    correlations = []
    
    overall_danger = danger.get("overall", {})
    locations = danger.get("locations", {})
    
    # Check for heat risk
    heat_risk = overall_danger.get("heat_risk", "NONE")
    
    if heat_risk in ["HIGH", "EXTREME"]:
        # Find the hottest location
        hottest_loc = None
        hottest_temp = 0
        
        for loc_key, loc_data in locations.items():
            temp = loc_data.get("max_temp_48h", 0)
            if temp and temp > hottest_temp:
                hottest_temp = temp
                hottest_loc = loc_data.get("location", loc_key)
        
        # Check if grid margin is also low
        margin_concern = grid_margin >= 0 and grid_margin < 10
        
        if heat_risk == "EXTREME":
            confidence = CorrelationLevel.STRONG
            level = "CRITICAL"
            if margin_concern:
                message = f"PREDICTIVE CRITICAL: {hottest_loc} forecast {hottest_temp}°F in 48h AND grid margin only {grid_margin:.1f}%"
            else:
                message = f"PREDICTIVE WARNING: {hottest_loc} forecast {hottest_temp}°F in 48h - extreme heat grid strain expected"
        else:
            confidence = CorrelationLevel.MODERATE
            level = "WARNING"
            message = f"PREDICTIVE: {hottest_loc} forecast {hottest_temp}°F in 48h - high heat grid strain risk"
        
        correlation = PredictiveCorrelation(
            correlation_type="PREDICTIVE_HEAT_STRAIN",
            forecast_event="EXTREME_HEAT" if heat_risk == "EXTREME" else "HIGH_HEAT",
            forecast_value=hottest_temp,
            physical_system="GRID",
            physical_status=level,
            prediction_window="48h",
            confidence=confidence,
            message=message,
            metadata={
                "location": hottest_loc,
                "grid_margin": grid_margin,
                "margin_concern": margin_concern,
            },
        )
        correlations.append(correlation)
        
        logger.info(
            "predictive_heat_correlation",
            location=hottest_loc,
            temp=hottest_temp,
            heat_risk=heat_risk,
            grid_margin=grid_margin,
        )
    
    # Check for freeze risk
    freeze_risk = overall_danger.get("freeze_risk", "NONE")
    
    if freeze_risk in ["MODERATE", "SEVERE", "EXTREME"]:
        # Find the coldest location
        coldest_loc = None
        coldest_temp = 999
        
        for loc_key, loc_data in locations.items():
            temp = loc_data.get("min_temp_48h", 999)
            if temp and temp < coldest_temp:
                coldest_temp = temp
                coldest_loc = loc_data.get("location", loc_key)
        
        if freeze_risk == "EXTREME":
            confidence = CorrelationLevel.STRONG
            level = "CRITICAL"
            message = f"PREDICTIVE CRITICAL: {coldest_loc} forecast {coldest_temp}°F in 48h - 2021-level freeze emergency"
        elif freeze_risk == "SEVERE":
            confidence = CorrelationLevel.STRONG
            level = "WARNING"
            message = f"PREDICTIVE WARNING: {coldest_loc} forecast {coldest_temp}°F in 48h - severe freeze risk"
        else:
            confidence = CorrelationLevel.MODERATE
            level = "WATCH"
            message = f"PREDICTIVE: {coldest_loc} forecast {coldest_temp}°F in 48h - freeze conditions expected"
        
        correlation = PredictiveCorrelation(
            correlation_type="PREDICTIVE_FREEZE",
            forecast_event=f"{freeze_risk}_FREEZE",
            forecast_value=coldest_temp,
            physical_system="GRID",
            physical_status=level,
            prediction_window="48h",
            confidence=confidence,
            message=message,
            metadata={
                "location": coldest_loc,
            },
        )
        correlations.append(correlation)
        
        logger.warning(
            "predictive_freeze_correlation",
            location=coldest_loc,
            temp=coldest_temp,
            freeze_risk=freeze_risk,
        )
    
    return correlations


def check_predictive_port_correlations(
    weather_alerts: list[dict],
    physical_alerts: dict[str, list[dict]],
) -> list[PredictiveCorrelation]:
    """
    Check for predictive port/logistics correlations.
    
    Rule: IF (Hurricane/Storm Warning for Houston) -> PREDICTIVE: PORT CHOKEPOINT
    
    Args:
        weather_alerts: NWS weather alerts
        physical_alerts: Current physical alerts
        
    Returns:
        List of detected predictive correlations
    """
    correlations = []
    
    storm_keywords = ["hurricane", "tropical storm", "storm surge", "coastal flood"]
    
    for alert in weather_alerts:
        event = alert.get("event", "").lower()
        headline = alert.get("headline", "")
        areas = alert.get("areas_affected", [])
        
        # Check if it's a storm-related alert
        is_storm = any(keyword in event for keyword in storm_keywords)
        
        # Check if it affects Houston/Gulf Coast
        houston_affected = any(
            "harris" in area.lower() or "houston" in area.lower() or "galveston" in area.lower()
            for area in areas
        )
        
        if is_storm:
            severity = alert.get("severity", "")
            
            if severity in ["Extreme", "Severe"] or houston_affected:
                confidence = CorrelationLevel.STRONG
                level = "CRITICAL"
            else:
                confidence = CorrelationLevel.MODERATE
                level = "WARNING"
            
            correlation = PredictiveCorrelation(
                correlation_type="PREDICTIVE_PORT_STORM",
                forecast_event=alert.get("event", "STORM"),
                forecast_value=None,
                physical_system="PORT",
                physical_status=level,
                prediction_window="varies",
                confidence=confidence,
                message=f"PREDICTIVE: {headline[:100]} - Port of Houston operations may be impacted",
                metadata={
                    "alert_event": alert.get("event"),
                    "severity": severity,
                    "houston_affected": houston_affected,
                    "areas": areas[:5],
                },
            )
            correlations.append(correlation)
            
            logger.warning(
                "predictive_storm_correlation",
                event=alert.get("event"),
                severity=severity,
                houston_affected=houston_affected,
            )
    
    return correlations


def store_predictive_alerts(correlations: list[PredictiveCorrelation]) -> int:
    """
    Store predictive correlation alerts in the database.
    
    Args:
        correlations: List of detected predictive correlations
        
    Returns:
        Number of alerts stored
    """
    if not correlations:
        return 0
    
    stored = 0
    
    with get_db_session() as db:
        for correlation in correlations:
            # Create alert with PREDICTIVE type
            alert = Alert(
                alert_type="PREDICTIVE",
                alert_level=correlation.physical_status,
                region_code="US-TX",
                title=f"Predictive: {correlation.correlation_type}",
                message=correlation.message,
                indicator_values={
                    "forecast_event": correlation.forecast_event,
                    "forecast_value": correlation.forecast_value,
                    "physical_system": correlation.physical_system,
                    "prediction_window": correlation.prediction_window,
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


def evaluate_predictive_correlations() -> dict[str, Any]:
    """
    Main entry point for predictive correlation evaluation (Linked Fate v4).
    Called by the scheduler every 15 minutes.
    
    Implements Linked Fate v4:
    1. Fetch weather danger assessment
    2. Fetch current physical alerts
    3. Get current grid margin
    4. Check for predictive correlations
    5. Generate and store predictive alerts
    
    Returns:
        Dict with evaluation summary
    """
    logger.info("predictive_correlation_evaluation_started")
    
    try:
        # Get weather danger assessment
        danger = get_weather_danger()
        
        if not danger.get("locations"):
            return {
                "status": "no_weather_data",
                "message": "Unable to fetch weather data",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        
        # Get physical alerts
        physical_alerts = get_active_physical_alerts()
        
        # Get grid margin
        grid_margin = get_current_grid_margin()
        
        # Get weather alerts
        try:
            from src.ingestion.weather import fetch_alerts
            weather_alerts = [a.to_dict() for a in fetch_alerts("TX")]
        except Exception:
            weather_alerts = []
        
        # Check all predictive correlation types
        all_correlations = []
        
        # Grid strain predictions (heat/freeze)
        grid_correlations = check_predictive_grid_correlations(
            danger, physical_alerts, grid_margin
        )
        all_correlations.extend(grid_correlations)
        
        # Port/storm predictions
        port_correlations = check_predictive_port_correlations(
            weather_alerts, physical_alerts
        )
        all_correlations.extend(port_correlations)
        
        # Store alerts
        stored_count = store_predictive_alerts(all_correlations)
        
        # Build summary
        summary = {
            "status": "completed",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "weather_danger": {
                "heat_risk": danger.get("overall", {}).get("heat_risk", "NONE"),
                "freeze_risk": danger.get("overall", {}).get("freeze_risk", "NONE"),
                "grid_strain_prediction": danger.get("overall", {}).get("grid_strain_prediction", "NORMAL"),
            },
            "grid_margin": grid_margin,
            "weather_alerts_checked": len(weather_alerts),
            "predictive_correlations_detected": len(all_correlations),
            "alerts_stored": stored_count,
            "correlations": [c.to_dict() for c in all_correlations],
        }
        
        logger.info(
            "predictive_correlation_evaluation_completed",
            correlations=len(all_correlations),
            stored=stored_count,
            heat_risk=danger.get("overall", {}).get("heat_risk"),
            freeze_risk=danger.get("overall", {}).get("freeze_risk"),
        )
        
        return summary
        
    except Exception as e:
        logger.error("predictive_correlation_evaluation_error", error=str(e))
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
