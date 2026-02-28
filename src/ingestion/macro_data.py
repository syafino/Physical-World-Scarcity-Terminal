"""
FRED API Macro-Commodity Data Module

Fetches macro-economic baseline data from the Federal Reserve Economic Data (FRED) API.
Primary focus: Natural gas spot prices (Henry Hub) for Texas grid correlation.

Phase 6: The Macro-Commodity Layer
- Texas Node depends heavily on natural gas for power generation
- Commodity prices provide context for grid strain economics
- Linked Fate v5: Grid strain + commodity premium = expensive power generation

FRED Series:
- DHHNGSP: Henry Hub Natural Gas Spot Price ($/MMBtu)

API Documentation: https://fred.stlouisfed.org/docs/api/fred/
Free API Key: https://fred.stlouisfed.org/docs/api/api_key.html
"""

import os
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

FRED_API_BASE = "https://api.stlouisfed.org/fred"
USER_AGENT = "PWST_Terminal_MVP/1.0 (Physical World Scarcity Terminal)"

# Target FRED series
HENRY_HUB_SERIES = "DHHNGSP"  # Daily Natural Gas Spot Price, Henry Hub

# All commodity series we track
COMMODITY_SERIES = {
    "DHHNGSP": {
        "name": "Henry Hub Natural Gas Spot Price",
        "unit": "$/MMBtu",
        "frequency": "daily",
        "category": "energy",
        "texas_relevance": "Primary fuel for ERCOT gas-fired generation (~50% of grid)",
    },
    # Future expansion:
    # "DCOILWTICO": {
    #     "name": "WTI Crude Oil Spot Price",
    #     "unit": "$/barrel",
    #     "frequency": "daily",
    #     "category": "energy",
    # },
}

# Historical averages for anomaly detection
HISTORICAL_BASELINE = {
    "DHHNGSP": {
        "30d_avg": 2.50,  # Typical $2.50/MMBtu baseline
        "sigma": 0.80,    # Standard deviation
        "premium_threshold": 4.00,  # Price above which signals premium
        "spike_threshold": 6.00,    # Major price spike
    }
}


# ─────────────────────────────────────────────────────────────
# Data Classes
# ─────────────────────────────────────────────────────────────

@dataclass
class CommodityObservation:
    """Single observation from FRED time series."""
    series_id: str
    date: date
    value: float
    realtime_start: date
    realtime_end: date
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "series_id": self.series_id,
            "date": self.date.isoformat(),
            "value": self.value,
            "realtime_start": self.realtime_start.isoformat(),
            "realtime_end": self.realtime_end.isoformat(),
        }


@dataclass
class CommodityTimeSeries:
    """Time series data from FRED."""
    series_id: str
    name: str
    unit: str
    frequency: str
    observations: list[CommodityObservation] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_mock: bool = False
    
    @property
    def latest_value(self) -> Optional[float]:
        """Get most recent observation value."""
        if self.observations:
            return self.observations[-1].value
        return None
    
    @property
    def latest_date(self) -> Optional[date]:
        """Get most recent observation date."""
        if self.observations:
            return self.observations[-1].date
        return None
    
    def calculate_moving_average(self, window: int = 30) -> Optional[float]:
        """Calculate moving average over specified window."""
        if len(self.observations) < window:
            values = [o.value for o in self.observations]
        else:
            values = [o.value for o in self.observations[-window:]]
        
        if values:
            return sum(values) / len(values)
        return None
    
    def calculate_std_dev(self, window: int = 30) -> Optional[float]:
        """Calculate standard deviation over window."""
        if len(self.observations) < 2:
            return None
        
        values = [o.value for o in self.observations[-window:]] if len(self.observations) >= window else [o.value for o in self.observations]
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5
    
    def is_above_moving_average(self) -> bool:
        """Check if current price is above 30-day moving average."""
        latest = self.latest_value
        ma = self.calculate_moving_average(30)
        if latest is not None and ma is not None:
            return latest > ma
        return False
    
    def get_premium_percentage(self) -> Optional[float]:
        """Calculate percentage premium over moving average."""
        latest = self.latest_value
        ma = self.calculate_moving_average(30)
        if latest is not None and ma is not None and ma > 0:
            return ((latest - ma) / ma) * 100
        return None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "series_id": self.series_id,
            "name": self.name,
            "unit": self.unit,
            "frequency": self.frequency,
            "latest_value": self.latest_value,
            "latest_date": self.latest_date.isoformat() if self.latest_date else None,
            "moving_average_30d": self.calculate_moving_average(30),
            "std_dev_30d": self.calculate_std_dev(30),
            "premium_percent": self.get_premium_percentage(),
            "above_ma": self.is_above_moving_average(),
            "observation_count": len(self.observations),
            "fetched_at": self.fetched_at.isoformat(),
            "is_mock": self.is_mock,
            "observations": [o.to_dict() for o in self.observations],
        }


@dataclass
class MacroSummary:
    """Summary of all macro-commodity data."""
    henry_hub: Optional[CommodityTimeSeries] = None
    commodity_alert_level: str = "NORMAL"  # NORMAL, ELEVATED, PREMIUM, SPIKE
    grid_cost_impact: str = "NORMAL"       # NORMAL, ELEVATED, HIGH, CRITICAL
    alert_message: Optional[str] = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "henry_hub": self.henry_hub.to_dict() if self.henry_hub else None,
            "commodity_alert_level": self.commodity_alert_level,
            "grid_cost_impact": self.grid_cost_impact,
            "alert_message": self.alert_message,
            "fetched_at": self.fetched_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────
# FRED API Functions
# ─────────────────────────────────────────────────────────────

def get_fred_api_key() -> Optional[str]:
    """Get FRED API key from environment."""
    from src.config.settings import settings
    return getattr(settings, 'fred_api_key', None) or os.getenv("FRED_API_KEY")


def fetch_fred_series(
    series_id: str,
    days_back: int = 30,
    api_key: Optional[str] = None,
) -> Optional[CommodityTimeSeries]:
    """
    Fetch time series data from FRED API.
    
    Args:
        series_id: FRED series ID (e.g., "DHHNGSP")
        days_back: Number of days of history to fetch
        api_key: FRED API key (uses env if not provided)
        
    Returns:
        CommodityTimeSeries or None if fetch fails
    """
    api_key = api_key or get_fred_api_key()
    
    if not api_key:
        logger.warning("fred_api_key_missing", series=series_id)
        return generate_mock_series(series_id, days_back)
    
    series_info = COMMODITY_SERIES.get(series_id, {})
    
    try:
        # Calculate date range
        end_date = date.today()
        start_date = end_date - timedelta(days=days_back + 10)  # Extra buffer for weekends/holidays
        
        url = f"{FRED_API_BASE}/series/observations"
        params = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": start_date.isoformat(),
            "observation_end": end_date.isoformat(),
            "sort_order": "asc",
        }
        
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            data = response.json()
        
        observations = []
        for obs in data.get("observations", []):
            # Skip missing values (FRED uses "." for missing)
            if obs.get("value") == ".":
                continue
                
            try:
                observations.append(CommodityObservation(
                    series_id=series_id,
                    date=date.fromisoformat(obs["date"]),
                    value=float(obs["value"]),
                    realtime_start=date.fromisoformat(obs["realtime_start"]),
                    realtime_end=date.fromisoformat(obs["realtime_end"]),
                ))
            except (ValueError, KeyError) as e:
                logger.debug("fred_observation_parse_error", obs=obs, error=str(e))
                continue
        
        logger.info(
            "fred_series_fetched",
            series=series_id,
            observations=len(observations),
            start=start_date.isoformat(),
            end=end_date.isoformat(),
        )
        
        return CommodityTimeSeries(
            series_id=series_id,
            name=series_info.get("name", series_id),
            unit=series_info.get("unit", ""),
            frequency=series_info.get("frequency", "daily"),
            observations=observations,
            is_mock=False,
        )
        
    except httpx.HTTPStatusError as e:
        logger.error("fred_api_http_error", series=series_id, status=e.response.status_code)
        return generate_mock_series(series_id, days_back)
    except Exception as e:
        logger.error("fred_api_error", series=series_id, error=str(e))
        return generate_mock_series(series_id, days_back)


def generate_mock_series(series_id: str, days_back: int = 30) -> CommodityTimeSeries:
    """
    Generate realistic mock data when API key is not available.
    
    Uses historical baseline to generate plausible values with realistic
    day-to-day variation.
    """
    series_info = COMMODITY_SERIES.get(series_id, {})
    baseline = HISTORICAL_BASELINE.get(series_id, {})
    
    base_price = baseline.get("30d_avg", 2.50)
    sigma = baseline.get("sigma", 0.80)
    
    observations = []
    current_price = base_price + random.uniform(-sigma, sigma)
    
    end_date = date.today()
    
    for i in range(days_back):
        obs_date = end_date - timedelta(days=days_back - i - 1)
        
        # Skip weekends (FRED doesn't have weekend data)
        if obs_date.weekday() >= 5:
            continue
        
        # Random walk with mean reversion
        change = random.gauss(0, sigma * 0.1)
        mean_reversion = (base_price - current_price) * 0.05
        current_price = max(0.50, current_price + change + mean_reversion)
        
        observations.append(CommodityObservation(
            series_id=series_id,
            date=obs_date,
            value=round(current_price, 2),
            realtime_start=obs_date,
            realtime_end=obs_date,
        ))
    
    logger.info(
        "fred_mock_series_generated",
        series=series_id,
        observations=len(observations),
    )
    
    return CommodityTimeSeries(
        series_id=series_id,
        name=series_info.get("name", series_id),
        unit=series_info.get("unit", ""),
        frequency=series_info.get("frequency", "daily"),
        observations=observations,
        is_mock=True,
    )


# ─────────────────────────────────────────────────────────────
# Henry Hub Specific Functions
# ─────────────────────────────────────────────────────────────

def fetch_henry_hub(days_back: int = 30) -> Optional[CommodityTimeSeries]:
    """
    Fetch Henry Hub Natural Gas Spot Price.
    
    This is the primary commodity for Texas grid correlation.
    ~50% of ERCOT generation is gas-fired.
    
    Args:
        days_back: Days of history to fetch
        
    Returns:
        CommodityTimeSeries for Henry Hub prices
    """
    return fetch_fred_series(HENRY_HUB_SERIES, days_back=days_back)


def assess_commodity_impact(series: CommodityTimeSeries) -> dict[str, Any]:
    """
    Assess the impact of current commodity price on grid economics.
    
    Returns assessment dict with alert levels and messages.
    """
    baseline = HISTORICAL_BASELINE.get(series.series_id, {})
    
    latest = series.latest_value
    ma_30d = series.calculate_moving_average(30)
    premium_pct = series.get_premium_percentage()
    
    # Default assessment
    assessment = {
        "series_id": series.series_id,
        "latest_price": latest,
        "moving_average_30d": ma_30d,
        "premium_percent": premium_pct,
        "alert_level": "NORMAL",
        "grid_cost_impact": "NORMAL",
        "alert_message": None,
        "assessed_at": datetime.now(timezone.utc).isoformat(),
    }
    
    if latest is None:
        return assessment
    
    premium_threshold = baseline.get("premium_threshold", 4.00)
    spike_threshold = baseline.get("spike_threshold", 6.00)
    
    # Assess alert level based on price
    if latest >= spike_threshold:
        assessment["alert_level"] = "SPIKE"
        assessment["grid_cost_impact"] = "CRITICAL"
        assessment["alert_message"] = f"GAS PRICE SPIKE: ${latest:.2f}/MMBtu - Power generation costs severely elevated"
    elif latest >= premium_threshold:
        assessment["alert_level"] = "PREMIUM"
        assessment["grid_cost_impact"] = "HIGH"
        assessment["alert_message"] = f"GAS PREMIUM: ${latest:.2f}/MMBtu - Above typical trading range"
    elif premium_pct and premium_pct > 20:
        assessment["alert_level"] = "ELEVATED"
        assessment["grid_cost_impact"] = "ELEVATED"
        assessment["alert_message"] = f"GAS ELEVATED: {premium_pct:.1f}% above 30-day average"
    else:
        assessment["alert_level"] = "NORMAL"
        assessment["grid_cost_impact"] = "NORMAL"
    
    return assessment


# ─────────────────────────────────────────────────────────────
# Main Entry Points
# ─────────────────────────────────────────────────────────────

def get_macro_summary(days_back: int = 30) -> MacroSummary:
    """
    Get complete macro-commodity summary.
    
    Returns:
        MacroSummary with all commodity data and assessments
    """
    # Fetch Henry Hub
    henry_hub = fetch_henry_hub(days_back=days_back)
    
    # Assess impact
    assessment = assess_commodity_impact(henry_hub) if henry_hub else {}
    
    return MacroSummary(
        henry_hub=henry_hub,
        commodity_alert_level=assessment.get("alert_level", "NORMAL"),
        grid_cost_impact=assessment.get("grid_cost_impact", "NORMAL"),
        alert_message=assessment.get("alert_message"),
    )


def get_current_gas_price() -> Optional[float]:
    """
    Quick helper to get current Henry Hub price.
    Used by Linked Fate v5 correlation checks.
    """
    series = fetch_henry_hub(days_back=5)
    return series.latest_value if series else None


def get_gas_premium_status() -> dict[str, Any]:
    """
    Get current gas price premium status for correlation engine.
    
    Returns dict with:
    - is_premium: bool - True if price > 30d MA
    - premium_percent: float - Percentage above MA
    - alert_level: str - NORMAL/ELEVATED/PREMIUM/SPIKE
    """
    series = fetch_henry_hub(days_back=30)
    
    if not series or series.latest_value is None:
        return {
            "is_premium": False,
            "premium_percent": 0.0,
            "alert_level": "UNKNOWN",
            "current_price": None,
            "moving_average": None,
        }
    
    assessment = assess_commodity_impact(series)
    
    return {
        "is_premium": series.is_above_moving_average(),
        "premium_percent": series.get_premium_percentage() or 0.0,
        "alert_level": assessment.get("alert_level", "NORMAL"),
        "current_price": series.latest_value,
        "moving_average": series.calculate_moving_average(30),
    }


def fetch_and_cache_macro_data() -> dict[str, Any]:
    """
    Celery task entry point - fetch and cache macro data.
    Called daily to update commodity prices.
    
    Returns:
        Dict with fetch summary
    """
    logger.info("macro_data_fetch_started")
    
    summary = get_macro_summary(days_back=30)
    
    result = {
        "status": "completed",
        "fetched_at": summary.fetched_at.isoformat(),
        "henry_hub_price": summary.henry_hub.latest_value if summary.henry_hub else None,
        "henry_hub_date": summary.henry_hub.latest_date.isoformat() if summary.henry_hub and summary.henry_hub.latest_date else None,
        "is_mock_data": summary.henry_hub.is_mock if summary.henry_hub else True,
        "commodity_alert_level": summary.commodity_alert_level,
        "grid_cost_impact": summary.grid_cost_impact,
        "alert_message": summary.alert_message,
    }
    
    logger.info(
        "macro_data_fetch_completed",
        price=result["henry_hub_price"],
        alert_level=result["commodity_alert_level"],
        is_mock=result["is_mock_data"],
    )
    
    return result
