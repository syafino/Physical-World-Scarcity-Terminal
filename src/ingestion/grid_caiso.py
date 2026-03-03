"""
CAISO (California Independent System Operator) Grid Data Fetcher

Fetches real-time grid data from CAISO's public APIs:
- System demand
- Renewable generation (Solar/Wind)
- Operating reserves

Phase 7: Horizontal Scaling - California Node (US-CA)

CAISO OASIS API:
    - http://oasis.caiso.com/oasisapi/SingleZip
    - Free, no API key required
    - Returns XML/ZIP files

CAISO Today's Outlook (simpler, JSON-friendly):
    - https://www.caiso.com/outlook/
    - Daily demand/supply curves
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

# CAISO public API endpoints
CAISO_OUTLOOK_BASE = "https://www.caiso.com/outlook/SP"

# Demand endpoint returns today's demand data
CAISO_DEMAND_URL = f"{CAISO_OUTLOOK_BASE}/demand.json"
CAISO_SUPPLY_URL = f"{CAISO_OUTLOOK_BASE}/fuelsource.json"
CAISO_RENEWABLES_URL = f"{CAISO_OUTLOOK_BASE}/renewables.json"

# CAISO capacity thresholds (MW)
CAISO_CAPACITY_NOMINAL = 52000  # Approximate peak capacity
CAISO_RESERVE_WARNING = 0.08   # 8% reserve margin warning
CAISO_RESERVE_CRITICAL = 0.05  # 5% reserve margin critical

# Fuel type mapping
CAISO_FUEL_TYPES = {
    "Solar": "solar",
    "Wind": "wind",
    "Geothermal": "geothermal",
    "Biomass": "biomass",
    "Biogas": "biogas",
    "Small hydro": "small_hydro",
    "Batteries": "batteries",
    "Natural Gas": "natural_gas",
    "Large Hydro": "large_hydro",
    "Imports": "imports",
    "Nuclear": "nuclear",
    "Coal": "coal",
}


# ─────────────────────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────────────────────


@dataclass
class CAISODemand:
    """Current CAISO system demand."""
    current_demand: float  # MW
    forecasted_demand: float  # MW
    timestamp: datetime
    hour: int
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "current_demand": self.current_demand,
            "forecasted_demand": self.forecasted_demand,
            "timestamp": self.timestamp.isoformat(),
            "hour": self.hour,
        }


@dataclass
class CAISOGeneration:
    """CAISO generation by fuel source."""
    solar: float = 0.0
    wind: float = 0.0
    geothermal: float = 0.0
    biomass: float = 0.0
    biogas: float = 0.0
    small_hydro: float = 0.0
    batteries: float = 0.0
    natural_gas: float = 0.0
    large_hydro: float = 0.0
    imports: float = 0.0
    nuclear: float = 0.0
    coal: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    @property
    def total_renewables(self) -> float:
        """Total renewable generation (solar + wind + small hydro + geothermal + batteries)."""
        return self.solar + self.wind + self.small_hydro + self.geothermal + self.batteries
    
    @property
    def total_generation(self) -> float:
        """Total generation from all sources."""
        return (
            self.solar + self.wind + self.geothermal + self.biomass +
            self.biogas + self.small_hydro + self.batteries +
            self.natural_gas + self.large_hydro + self.imports +
            self.nuclear + self.coal
        )
    
    @property
    def renewable_percentage(self) -> float:
        """Percentage of generation from renewables."""
        total = self.total_generation
        if total == 0:
            return 0.0
        return (self.total_renewables / total) * 100
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "solar": self.solar,
            "wind": self.wind,
            "geothermal": self.geothermal,
            "biomass": self.biomass,
            "biogas": self.biogas,
            "small_hydro": self.small_hydro,
            "batteries": self.batteries,
            "natural_gas": self.natural_gas,
            "large_hydro": self.large_hydro,
            "imports": self.imports,
            "nuclear": self.nuclear,
            "coal": self.coal,
            "total_renewables": self.total_renewables,
            "total_generation": self.total_generation,
            "renewable_percentage": self.renewable_percentage,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class CAISOGridSummary:
    """Complete CAISO grid status summary."""
    demand: Optional[CAISODemand]
    generation: Optional[CAISOGeneration]
    reserve_margin: float  # Percentage
    grid_status: str  # NORMAL, WATCH, WARNING, CRITICAL
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "demand": self.demand.to_dict() if self.demand else None,
            "generation": self.generation.to_dict() if self.generation else None,
            "reserve_margin": self.reserve_margin,
            "grid_status": self.grid_status,
            "fetched_at": self.fetched_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────
# HTTP Client
# ─────────────────────────────────────────────────────────────


def get_caiso_client() -> httpx.Client:
    """Get configured HTTP client for CAISO API."""
    return httpx.Client(
        headers={
            "User-Agent": "PWST_Terminal/1.0 (Physical World Scarcity Terminal)",
            "Accept": "application/json",
        },
        timeout=30.0,
        follow_redirects=True,
    )


# ─────────────────────────────────────────────────────────────
# Data Fetching Functions
# ─────────────────────────────────────────────────────────────


def fetch_caiso_demand() -> Optional[CAISODemand]:
    """
    Fetch current CAISO system demand.
    
    Returns:
        CAISODemand object or None on failure
    """
    try:
        with get_caiso_client() as client:
            response = client.get(CAISO_DEMAND_URL)
            
            if response.status_code != 200:
                logger.error(
                    "caiso_demand_fetch_error",
                    status=response.status_code,
                    url=CAISO_DEMAND_URL,
                )
                return None
            
            data = response.json()
            
            # CAISO demand.json format has "Current demand" and "Forecasted demand" arrays
            # Each array has entries per 5-minute interval
            current_demand_data = data.get("Current demand", [])
            forecast_demand_data = data.get("Forecasted demand", [])
            
            if not current_demand_data:
                logger.warning("caiso_demand_empty_response")
                return None
            
            # Get most recent data point (last entry)
            latest = current_demand_data[-1]
            latest_forecast = forecast_demand_data[-1] if forecast_demand_data else latest
            
            current_mw = float(latest.get("value", 0))
            forecast_mw = float(latest_forecast.get("value", current_mw))
            
            # Parse timestamp - CAISO uses format like "2026-03-03T14:00:00-08:00"
            timestamp_str = latest.get("interval_start_time", "")
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
            except (ValueError, TypeError):
                timestamp = datetime.now(timezone.utc)
            
            demand = CAISODemand(
                current_demand=current_mw,
                forecasted_demand=forecast_mw,
                timestamp=timestamp,
                hour=timestamp.hour,
            )
            
            logger.info(
                "caiso_demand_fetched",
                current_mw=current_mw,
                forecast_mw=forecast_mw,
            )
            
            return demand
            
    except Exception as e:
        logger.error("caiso_demand_exception", error=str(e))
        return None


def fetch_caiso_generation() -> Optional[CAISOGeneration]:
    """
    Fetch current CAISO generation by fuel source.
    
    Returns:
        CAISOGeneration object or None on failure
    """
    try:
        with get_caiso_client() as client:
            response = client.get(CAISO_SUPPLY_URL)
            
            if response.status_code != 200:
                logger.error(
                    "caiso_generation_fetch_error",
                    status=response.status_code,
                    url=CAISO_SUPPLY_URL,
                )
                return None
            
            data = response.json()
            
            # Parse fuel source data - format is array of fuel types with time series
            generation = CAISOGeneration()
            
            for fuel_entry in data:
                fuel_name = fuel_entry.get("fuel", "")
                values = fuel_entry.get("values", [])
                
                if not values:
                    continue
                
                # Get latest value
                latest_value = float(values[-1].get("value", 0))
                
                # Map to our field names
                fuel_key = CAISO_FUEL_TYPES.get(fuel_name, "").replace(" ", "_").lower()
                
                if fuel_key and hasattr(generation, fuel_key):
                    setattr(generation, fuel_key, latest_value)
            
            generation.timestamp = datetime.now(timezone.utc)
            
            logger.info(
                "caiso_generation_fetched",
                total_mw=generation.total_generation,
                renewable_pct=f"{generation.renewable_percentage:.1f}%",
                solar_mw=generation.solar,
                wind_mw=generation.wind,
            )
            
            return generation
            
    except Exception as e:
        logger.error("caiso_generation_exception", error=str(e))
        return None


def fetch_caiso_renewables() -> dict[str, Any]:
    """
    Fetch CAISO renewables trend data for charts.
    
    Returns:
        Dict with solar and wind time series
    """
    try:
        with get_caiso_client() as client:
            response = client.get(CAISO_RENEWABLES_URL)
            
            if response.status_code != 200:
                logger.error(
                    "caiso_renewables_fetch_error",
                    status=response.status_code,
                )
                return {}
            
            data = response.json()
            
            result = {
                "solar": [],
                "wind": [],
                "timestamps": [],
            }
            
            # Extract time series for charts
            for fuel_entry in data:
                fuel_name = fuel_entry.get("fuel", "").lower()
                values = fuel_entry.get("values", [])
                
                if fuel_name == "solar":
                    result["solar"] = [float(v.get("value", 0)) for v in values]
                    result["timestamps"] = [v.get("interval_start_time") for v in values]
                elif fuel_name == "wind":
                    result["wind"] = [float(v.get("value", 0)) for v in values]
            
            logger.info("caiso_renewables_fetched", data_points=len(result["solar"]))
            return result
            
    except Exception as e:
        logger.error("caiso_renewables_exception", error=str(e))
        return {}


def calculate_grid_status(
    demand: Optional[CAISODemand],
    generation: Optional[CAISOGeneration],
) -> tuple[float, str]:
    """
    Calculate reserve margin and grid status.
    
    Args:
        demand: Current demand data
        generation: Current generation data
        
    Returns:
        Tuple of (reserve_margin_percentage, status_string)
    """
    if not demand or not generation:
        return 0.0, "UNKNOWN"
    
    total_gen = generation.total_generation
    current_demand = demand.current_demand
    
    if current_demand == 0:
        return 100.0, "NORMAL"
    
    # Reserve margin = (generation capacity - demand) / demand
    # Using actual generation as proxy for available capacity
    reserve_margin = (total_gen - current_demand) / current_demand
    
    if reserve_margin > CAISO_RESERVE_WARNING:
        status = "NORMAL"
    elif reserve_margin > CAISO_RESERVE_CRITICAL:
        status = "WARNING"
    else:
        status = "CRITICAL"
    
    return reserve_margin * 100, status


def get_caiso_grid_summary() -> CAISOGridSummary:
    """
    Get complete CAISO grid summary.
    
    Returns:
        CAISOGridSummary with all grid data
    """
    demand = fetch_caiso_demand()
    generation = fetch_caiso_generation()
    reserve_margin, status = calculate_grid_status(demand, generation)
    
    return CAISOGridSummary(
        demand=demand,
        generation=generation,
        reserve_margin=reserve_margin,
        grid_status=status,
    )


# ─────────────────────────────────────────────────────────────
# Mock Data (Fallback when API unavailable)
# ─────────────────────────────────────────────────────────────


def get_mock_caiso_summary() -> CAISOGridSummary:
    """
    Generate realistic mock CAISO data for testing.
    
    Returns:
        CAISOGridSummary with mock data
    """
    import random
    
    now = datetime.now(timezone.utc)
    hour = now.hour
    
    # Realistic demand curve (peaks mid-afternoon Pacific time)
    # Adjust for UTC - Pacific is UTC-8
    pacific_hour = (hour - 8) % 24
    
    # Base demand around 25,000 MW, peaks around 35,000-45,000 MW
    if 14 <= pacific_hour <= 20:  # Peak hours
        base_demand = 38000 + random.uniform(-2000, 5000)
    elif 6 <= pacific_hour <= 14:  # Ramp up
        base_demand = 28000 + (pacific_hour - 6) * 1200 + random.uniform(-1000, 1000)
    else:  # Off-peak
        base_demand = 23000 + random.uniform(-2000, 2000)
    
    # Solar generation (high during midday, zero at night)
    if 8 <= pacific_hour <= 18:
        solar = max(0, 10000 * (1 - abs(pacific_hour - 13) / 5) + random.uniform(-1000, 1000))
    else:
        solar = 0
    
    # Wind generation (more variable, often higher at night)
    wind = 3500 + random.uniform(-1500, 2500)
    
    # Other sources
    natural_gas = max(10000, base_demand - solar - wind - 8000)
    
    demand = CAISODemand(
        current_demand=base_demand,
        forecasted_demand=base_demand + random.uniform(-500, 1000),
        timestamp=now,
        hour=pacific_hour,
    )
    
    generation = CAISOGeneration(
        solar=solar,
        wind=wind,
        natural_gas=natural_gas,
        large_hydro=2500 + random.uniform(-500, 500),
        nuclear=2200,  # Diablo Canyon - fairly constant
        imports=4000 + random.uniform(-1000, 1000),
        geothermal=800,
        batteries=500 + random.uniform(-200, 800),
        small_hydro=300,
        biomass=200,
        biogas=150,
        timestamp=now,
    )
    
    reserve_margin, status = calculate_grid_status(demand, generation)
    
    return CAISOGridSummary(
        demand=demand,
        generation=generation,
        reserve_margin=reserve_margin,
        grid_status=status,
    )


def get_caiso_data(use_mock: bool = False) -> dict[str, Any]:
    """
    Main entry point for CAISO grid data.
    
    Args:
        use_mock: Force mock data generation
        
    Returns:
        Dict with complete grid data for UI consumption
    """
    if use_mock:
        summary = get_mock_caiso_summary()
    else:
        summary = get_caiso_grid_summary()
        
        # Fall back to mock if API fails
        if not summary.demand or not summary.generation:
            logger.warning("caiso_api_failed_using_mock")
            summary = get_mock_caiso_summary()
    
    # Build response for UI
    result = {
        "grid_operator": "CAISO",
        "region": "US-CA",
        "fetched_at": summary.fetched_at.isoformat(),
        "status": summary.grid_status,
        "reserve_margin_pct": round(summary.reserve_margin, 2),
    }
    
    if summary.demand:
        result["demand"] = summary.demand.to_dict()
        result["current_demand_mw"] = summary.demand.current_demand
        result["forecasted_demand_mw"] = summary.demand.forecasted_demand
    
    if summary.generation:
        result["generation"] = summary.generation.to_dict()
        result["total_generation_mw"] = summary.generation.total_generation
        result["total_renewables_mw"] = summary.generation.total_renewables
        result["renewable_percentage"] = round(summary.generation.renewable_percentage, 1)
        result["solar_mw"] = summary.generation.solar
        result["wind_mw"] = summary.generation.wind
        result["natural_gas_mw"] = summary.generation.natural_gas
    
    # Fetch renewables trend for charts
    renewables_trend = fetch_caiso_renewables()
    if renewables_trend:
        result["renewables_trend"] = renewables_trend
    
    return result
