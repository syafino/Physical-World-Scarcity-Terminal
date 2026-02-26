"""
Weather Forecast Ingestion Module

Fetches 7-day weather forecasts from the US National Weather Service (NWS) API.
Free, no API key required. Implements the 2-step NWS API process:
1. Query lat/lon to get gridId and gridX/Y
2. Query forecast endpoint for that specific grid

Phase 5: The Predictive Layer
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

# NWS API requires custom User-Agent header
NWS_USER_AGENT = "PWST_Terminal_MVP/1.0 (pwst-terminal@example.com)"
NWS_BASE_URL = "https://api.weather.gov"

# Texas key coordinates for forecasting
TEXAS_FORECAST_LOCATIONS = {
    "DALLAS": {
        "name": "Dallas-Fort Worth",
        "lat": 32.7767,
        "lon": -96.7970,
        "purpose": "ERCOT load center",
        "grid_relevance": "GRID",
    },
    "HOUSTON": {
        "name": "Houston",
        "lat": 29.7604,
        "lon": -95.3698,
        "purpose": "Port/Logistics center",
        "grid_relevance": "PORT",
    },
    "AUSTIN": {
        "name": "Austin",
        "lat": 30.2672,
        "lon": -97.7431,
        "purpose": "State capital, population center",
        "grid_relevance": "GRID",
    },
    "SAN_ANTONIO": {
        "name": "San Antonio",
        "lat": 29.4241,
        "lon": -98.4936,
        "purpose": "Edwards Aquifer region",
        "grid_relevance": "WATER",
    },
}

# Temperature danger thresholds (Fahrenheit)
TEMPERATURE_THRESHOLDS = {
    "EXTREME_HEAT": 100,      # Extreme grid strain
    "HIGH_HEAT": 98,          # High grid strain danger zone
    "MODERATE_HEAT": 95,      # Elevated demand
    "FREEZE_WARNING": 32,     # Freeze risk
    "HARD_FREEZE": 25,        # Severe freeze (2021 crisis level)
    "EXTREME_COLD": 15,       # Extreme cold emergency
}

# Severe weather alert types that impact physical systems
CRITICAL_ALERT_TYPES = [
    "Extreme Heat Warning",
    "Excessive Heat Warning",
    "Heat Advisory",
    "Freeze Warning",
    "Hard Freeze Warning",
    "Winter Storm Warning",
    "Winter Storm Watch",
    "Ice Storm Warning",
    "Blizzard Warning",
    "Hurricane Warning",
    "Hurricane Watch",
    "Tropical Storm Warning",
    "Tornado Warning",
    "Severe Thunderstorm Warning",
    "Flash Flood Warning",
    "Flood Warning",
]


# ─────────────────────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────────────────────


@dataclass
class GridPoint:
    """NWS grid point information."""
    grid_id: str  # e.g., "FWD" for Dallas, "HGX" for Houston
    grid_x: int
    grid_y: int
    forecast_url: str
    forecast_hourly_url: str
    observation_stations_url: str


@dataclass
class ForecastPeriod:
    """Single forecast period (typically 12 hours)."""
    name: str
    start_time: datetime
    end_time: datetime
    temperature: int
    temperature_unit: str
    wind_speed: str
    wind_direction: str
    short_forecast: str
    detailed_forecast: str
    is_daytime: bool
    probability_of_precipitation: Optional[int] = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "temperature": self.temperature,
            "temperature_unit": self.temperature_unit,
            "wind_speed": self.wind_speed,
            "wind_direction": self.wind_direction,
            "short_forecast": self.short_forecast,
            "detailed_forecast": self.detailed_forecast,
            "is_daytime": self.is_daytime,
            "pop": self.probability_of_precipitation,
        }


@dataclass
class HourlyForecast:
    """Single hourly forecast point."""
    time: datetime
    temperature: int
    temperature_unit: str
    wind_speed: str
    wind_direction: str
    short_forecast: str
    probability_of_precipitation: Optional[int] = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "time": self.time.isoformat(),
            "temperature": self.temperature,
            "temperature_unit": self.temperature_unit,
            "wind_speed": self.wind_speed,
            "short_forecast": self.short_forecast,
            "pop": self.probability_of_precipitation,
        }


@dataclass
class WeatherAlert:
    """Active weather alert."""
    alert_id: str
    event: str
    headline: str
    severity: str
    certainty: str
    urgency: str
    onset: Optional[datetime]
    expires: Optional[datetime]
    description: str
    instruction: Optional[str]
    areas_affected: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "event": self.event,
            "headline": self.headline,
            "severity": self.severity,
            "certainty": self.certainty,
            "urgency": self.urgency,
            "onset": self.onset.isoformat() if self.onset else None,
            "expires": self.expires.isoformat() if self.expires else None,
            "description": self.description[:500],  # Truncate long descriptions
            "instruction": self.instruction[:300] if self.instruction else None,
            "areas_affected": self.areas_affected[:5],  # Limit areas list
        }
    
    @property
    def is_critical(self) -> bool:
        """Check if alert is critical for physical systems."""
        return self.event in CRITICAL_ALERT_TYPES or self.severity in ["Extreme", "Severe"]


@dataclass
class LocationForecast:
    """Complete forecast for a location."""
    location_key: str
    location_name: str
    latitude: float
    longitude: float
    grid_point: Optional[GridPoint]
    periods: list[ForecastPeriod]
    hourly: list[HourlyForecast]
    alerts: list[WeatherAlert]
    fetched_at: datetime
    
    # Computed stats
    max_temp_48h: Optional[int] = None
    min_temp_48h: Optional[int] = None
    max_temp_7d: Optional[int] = None
    min_temp_7d: Optional[int] = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "location_key": self.location_key,
            "location_name": self.location_name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "grid_id": self.grid_point.grid_id if self.grid_point else None,
            "periods": [p.to_dict() for p in self.periods[:14]],  # 7 days
            "hourly": [h.to_dict() for h in self.hourly[:168]],   # 7 days hourly
            "alerts": [a.to_dict() for a in self.alerts],
            "fetched_at": self.fetched_at.isoformat(),
            "stats": {
                "max_temp_48h": self.max_temp_48h,
                "min_temp_48h": self.min_temp_48h,
                "max_temp_7d": self.max_temp_7d,
                "min_temp_7d": self.min_temp_7d,
            },
        }


# ─────────────────────────────────────────────────────────────
# NWS API Client
# ─────────────────────────────────────────────────────────────


def get_nws_client() -> httpx.Client:
    """Get configured HTTP client for NWS API."""
    return httpx.Client(
        base_url=NWS_BASE_URL,
        headers={
            "User-Agent": NWS_USER_AGENT,
            "Accept": "application/geo+json",
        },
        timeout=30.0,
    )


def fetch_grid_point(lat: float, lon: float) -> Optional[GridPoint]:
    """
    Step 1 of NWS API: Get grid point info from lat/lon.
    
    Args:
        lat: Latitude
        lon: Longitude
        
    Returns:
        GridPoint with forecast URLs, or None on failure
    """
    try:
        with get_nws_client() as client:
            response = client.get(f"/points/{lat},{lon}")
            
            if response.status_code != 200:
                logger.error(
                    "nws_grid_point_error",
                    lat=lat,
                    lon=lon,
                    status=response.status_code,
                    response=response.text[:200],
                )
                return None
            
            data = response.json()
            properties = data.get("properties", {})
            
            grid_point = GridPoint(
                grid_id=properties.get("gridId", ""),
                grid_x=properties.get("gridX", 0),
                grid_y=properties.get("gridY", 0),
                forecast_url=properties.get("forecast", ""),
                forecast_hourly_url=properties.get("forecastHourly", ""),
                observation_stations_url=properties.get("observationStations", ""),
            )
            
            logger.debug(
                "nws_grid_point_fetched",
                lat=lat,
                lon=lon,
                grid_id=grid_point.grid_id,
            )
            
            return grid_point
            
    except Exception as e:
        logger.error("nws_grid_point_exception", lat=lat, lon=lon, error=str(e))
        return None


def fetch_forecast(grid_point: GridPoint) -> list[ForecastPeriod]:
    """
    Step 2a: Fetch 7-day forecast from grid point.
    
    Args:
        grid_point: GridPoint with forecast URL
        
    Returns:
        List of ForecastPeriod objects
    """
    try:
        with get_nws_client() as client:
            response = client.get(grid_point.forecast_url)
            
            if response.status_code != 200:
                logger.error(
                    "nws_forecast_error",
                    url=grid_point.forecast_url,
                    status=response.status_code,
                )
                return []
            
            data = response.json()
            periods_data = data.get("properties", {}).get("periods", [])
            
            periods = []
            for p in periods_data:
                period = ForecastPeriod(
                    name=p.get("name", ""),
                    start_time=datetime.fromisoformat(p.get("startTime", "").replace("Z", "+00:00")),
                    end_time=datetime.fromisoformat(p.get("endTime", "").replace("Z", "+00:00")),
                    temperature=p.get("temperature", 0),
                    temperature_unit=p.get("temperatureUnit", "F"),
                    wind_speed=p.get("windSpeed", ""),
                    wind_direction=p.get("windDirection", ""),
                    short_forecast=p.get("shortForecast", ""),
                    detailed_forecast=p.get("detailedForecast", ""),
                    is_daytime=p.get("isDaytime", True),
                    probability_of_precipitation=p.get("probabilityOfPrecipitation", {}).get("value"),
                )
                periods.append(period)
            
            logger.info("nws_forecast_fetched", grid_id=grid_point.grid_id, periods=len(periods))
            return periods
            
    except Exception as e:
        logger.error("nws_forecast_exception", error=str(e))
        return []


def fetch_hourly_forecast(grid_point: GridPoint) -> list[HourlyForecast]:
    """
    Step 2b: Fetch hourly forecast from grid point.
    
    Args:
        grid_point: GridPoint with hourly forecast URL
        
    Returns:
        List of HourlyForecast objects
    """
    try:
        with get_nws_client() as client:
            response = client.get(grid_point.forecast_hourly_url)
            
            if response.status_code != 200:
                logger.error(
                    "nws_hourly_error",
                    url=grid_point.forecast_hourly_url,
                    status=response.status_code,
                )
                return []
            
            data = response.json()
            periods_data = data.get("properties", {}).get("periods", [])
            
            hourly = []
            for p in periods_data:
                hour = HourlyForecast(
                    time=datetime.fromisoformat(p.get("startTime", "").replace("Z", "+00:00")),
                    temperature=p.get("temperature", 0),
                    temperature_unit=p.get("temperatureUnit", "F"),
                    wind_speed=p.get("windSpeed", ""),
                    wind_direction=p.get("windDirection", ""),
                    short_forecast=p.get("shortForecast", ""),
                    probability_of_precipitation=p.get("probabilityOfPrecipitation", {}).get("value"),
                )
                hourly.append(hour)
            
            logger.info("nws_hourly_fetched", grid_id=grid_point.grid_id, hours=len(hourly))
            return hourly
            
    except Exception as e:
        logger.error("nws_hourly_exception", error=str(e))
        return []


def fetch_alerts(state: str = "TX") -> list[WeatherAlert]:
    """
    Fetch active weather alerts for a state.
    
    Args:
        state: State code (e.g., "TX")
        
    Returns:
        List of WeatherAlert objects
    """
    try:
        with get_nws_client() as client:
            response = client.get(f"/alerts/active?area={state}")
            
            if response.status_code != 200:
                logger.error("nws_alerts_error", state=state, status=response.status_code)
                return []
            
            data = response.json()
            features = data.get("features", [])
            
            alerts = []
            for f in features:
                props = f.get("properties", {})
                
                # Parse datetime fields
                onset = None
                expires = None
                if props.get("onset"):
                    try:
                        onset = datetime.fromisoformat(props["onset"].replace("Z", "+00:00"))
                    except:
                        pass
                if props.get("expires"):
                    try:
                        expires = datetime.fromisoformat(props["expires"].replace("Z", "+00:00"))
                    except:
                        pass
                
                alert = WeatherAlert(
                    alert_id=props.get("id", ""),
                    event=props.get("event", ""),
                    headline=props.get("headline", ""),
                    severity=props.get("severity", ""),
                    certainty=props.get("certainty", ""),
                    urgency=props.get("urgency", ""),
                    onset=onset,
                    expires=expires,
                    description=props.get("description", ""),
                    instruction=props.get("instruction"),
                    areas_affected=props.get("areaDesc", "").split("; ")[:10],
                )
                alerts.append(alert)
            
            logger.info("nws_alerts_fetched", state=state, count=len(alerts))
            return alerts
            
    except Exception as e:
        logger.error("nws_alerts_exception", state=state, error=str(e))
        return []


# ─────────────────────────────────────────────────────────────
# High-Level Fetchers
# ─────────────────────────────────────────────────────────────


def fetch_location_forecast(location_key: str) -> Optional[LocationForecast]:
    """
    Fetch complete forecast for a predefined Texas location.
    
    Args:
        location_key: Key from TEXAS_FORECAST_LOCATIONS (e.g., "DALLAS")
        
    Returns:
        LocationForecast with all data, or None on failure
    """
    if location_key not in TEXAS_FORECAST_LOCATIONS:
        logger.error("unknown_location", location_key=location_key)
        return None
    
    location = TEXAS_FORECAST_LOCATIONS[location_key]
    lat, lon = location["lat"], location["lon"]
    
    logger.info("fetching_location_forecast", location=location_key, lat=lat, lon=lon)
    
    # Step 1: Get grid point
    grid_point = fetch_grid_point(lat, lon)
    
    # Step 2: Fetch forecasts
    periods = []
    hourly = []
    
    if grid_point:
        periods = fetch_forecast(grid_point)
        hourly = fetch_hourly_forecast(grid_point)
    
    # Fetch state-wide alerts
    alerts = fetch_alerts("TX")
    
    # Compute temperature stats
    max_temp_48h = None
    min_temp_48h = None
    max_temp_7d = None
    min_temp_7d = None
    
    if hourly:
        # 48-hour stats (first 48 hours)
        temps_48h = [h.temperature for h in hourly[:48]]
        if temps_48h:
            max_temp_48h = max(temps_48h)
            min_temp_48h = min(temps_48h)
        
        # 7-day stats
        temps_7d = [h.temperature for h in hourly]
        if temps_7d:
            max_temp_7d = max(temps_7d)
            min_temp_7d = min(temps_7d)
    
    forecast = LocationForecast(
        location_key=location_key,
        location_name=location["name"],
        latitude=lat,
        longitude=lon,
        grid_point=grid_point,
        periods=periods,
        hourly=hourly,
        alerts=alerts,
        fetched_at=datetime.now(timezone.utc),
        max_temp_48h=max_temp_48h,
        min_temp_48h=min_temp_48h,
        max_temp_7d=max_temp_7d,
        min_temp_7d=min_temp_7d,
    )
    
    return forecast


def fetch_all_texas_forecasts() -> dict[str, LocationForecast]:
    """
    Fetch forecasts for all key Texas locations.
    
    Returns:
        Dict mapping location key to LocationForecast
    """
    forecasts = {}
    
    # Only fetch Dallas and Houston for MVP (ERCOT load center + Port)
    for location_key in ["DALLAS", "HOUSTON"]:
        forecast = fetch_location_forecast(location_key)
        if forecast:
            forecasts[location_key] = forecast
    
    return forecasts


def get_weather_summary() -> dict[str, Any]:
    """
    Get aggregated weather summary for Texas.
    
    Returns:
        Dict with forecasts, alerts, and danger assessments
    """
    forecasts = fetch_all_texas_forecasts()
    
    # Aggregate alerts
    all_alerts = []
    for forecast in forecasts.values():
        all_alerts.extend(forecast.alerts)
    
    # Deduplicate alerts by ID
    seen_ids = set()
    unique_alerts = []
    for alert in all_alerts:
        if alert.alert_id not in seen_ids:
            seen_ids.add(alert.alert_id)
            unique_alerts.append(alert)
    
    # Critical alerts
    critical_alerts = [a for a in unique_alerts if a.is_critical]
    
    # Assess danger zones
    danger_assessment = assess_temperature_danger(forecasts)
    
    return {
        "forecasts": {k: v.to_dict() for k, v in forecasts.items()},
        "alerts": [a.to_dict() for a in unique_alerts],
        "critical_alerts": [a.to_dict() for a in critical_alerts],
        "danger_assessment": danger_assessment,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────────────────────
# Danger Assessment (Linked Fate v4)
# ─────────────────────────────────────────────────────────────


def assess_temperature_danger(forecasts: dict[str, LocationForecast]) -> dict[str, Any]:
    """
    Assess temperature danger zones for grid strain prediction.
    
    Uses thresholds:
    - EXTREME_HEAT (>100°F): Extreme grid strain expected
    - HIGH_HEAT (>98°F): High grid strain danger zone
    - HARD_FREEZE (<25°F): Severe freeze risk (2021 crisis level)
    - FREEZE_WARNING (<32°F): Freeze risk
    
    Returns:
        Dict with danger assessments for each location
    """
    assessments = {}
    
    for location_key, forecast in forecasts.items():
        location_assessment = {
            "location": forecast.location_name,
            "max_temp_48h": forecast.max_temp_48h,
            "min_temp_48h": forecast.min_temp_48h,
            "max_temp_7d": forecast.max_temp_7d,
            "min_temp_7d": forecast.min_temp_7d,
            "heat_risk": "NONE",
            "freeze_risk": "NONE",
            "grid_strain_prediction": "NORMAL",
            "danger_hours_48h": [],
        }
        
        # Assess heat risk (48h window)
        if forecast.max_temp_48h:
            if forecast.max_temp_48h >= TEMPERATURE_THRESHOLDS["EXTREME_HEAT"]:
                location_assessment["heat_risk"] = "EXTREME"
                location_assessment["grid_strain_prediction"] = "EXTREME"
            elif forecast.max_temp_48h >= TEMPERATURE_THRESHOLDS["HIGH_HEAT"]:
                location_assessment["heat_risk"] = "HIGH"
                location_assessment["grid_strain_prediction"] = "HIGH"
            elif forecast.max_temp_48h >= TEMPERATURE_THRESHOLDS["MODERATE_HEAT"]:
                location_assessment["heat_risk"] = "MODERATE"
                location_assessment["grid_strain_prediction"] = "ELEVATED"
        
        # Assess freeze risk (48h window)
        if forecast.min_temp_48h:
            if forecast.min_temp_48h <= TEMPERATURE_THRESHOLDS["EXTREME_COLD"]:
                location_assessment["freeze_risk"] = "EXTREME"
                location_assessment["grid_strain_prediction"] = "EXTREME"
            elif forecast.min_temp_48h <= TEMPERATURE_THRESHOLDS["HARD_FREEZE"]:
                location_assessment["freeze_risk"] = "SEVERE"
                if location_assessment["grid_strain_prediction"] not in ["EXTREME"]:
                    location_assessment["grid_strain_prediction"] = "SEVERE"
            elif forecast.min_temp_48h <= TEMPERATURE_THRESHOLDS["FREEZE_WARNING"]:
                location_assessment["freeze_risk"] = "MODERATE"
        
        # Find danger hours in 48h window
        danger_hours = []
        for hour in forecast.hourly[:48]:
            temp = hour.temperature
            danger_type = None
            
            if temp >= TEMPERATURE_THRESHOLDS["HIGH_HEAT"]:
                danger_type = "HIGH_HEAT"
            elif temp <= TEMPERATURE_THRESHOLDS["HARD_FREEZE"]:
                danger_type = "HARD_FREEZE"
            elif temp <= TEMPERATURE_THRESHOLDS["FREEZE_WARNING"]:
                danger_type = "FREEZE"
            
            if danger_type:
                danger_hours.append({
                    "time": hour.time.isoformat(),
                    "temperature": temp,
                    "danger_type": danger_type,
                })
        
        location_assessment["danger_hours_48h"] = danger_hours
        assessments[location_key] = location_assessment
    
    # Overall assessment
    overall = {
        "heat_risk": "NONE",
        "freeze_risk": "NONE",
        "grid_strain_prediction": "NORMAL",
    }
    
    risk_order = {"NONE": 0, "MODERATE": 1, "HIGH": 2, "SEVERE": 3, "EXTREME": 4}
    strain_order = {"NORMAL": 0, "ELEVATED": 1, "HIGH": 2, "SEVERE": 3, "EXTREME": 4}
    
    for assessment in assessments.values():
        if risk_order.get(assessment["heat_risk"], 0) > risk_order.get(overall["heat_risk"], 0):
            overall["heat_risk"] = assessment["heat_risk"]
        if risk_order.get(assessment["freeze_risk"], 0) > risk_order.get(overall["freeze_risk"], 0):
            overall["freeze_risk"] = assessment["freeze_risk"]
        if strain_order.get(assessment["grid_strain_prediction"], 0) > strain_order.get(overall["grid_strain_prediction"], 0):
            overall["grid_strain_prediction"] = assessment["grid_strain_prediction"]
    
    return {
        "overall": overall,
        "locations": assessments,
        "thresholds": TEMPERATURE_THRESHOLDS,
    }


def get_predictive_alerts() -> list[dict]:
    """
    Generate predictive alerts based on weather forecasts.
    
    Used by Linked Fate v4 for anticipatory correlation.
    
    Returns:
        List of predictive alert dicts
    """
    forecasts = fetch_all_texas_forecasts()
    danger = assess_temperature_danger(forecasts)
    
    alerts = []
    
    # Check for extreme heat grid strain
    if danger["overall"]["heat_risk"] in ["HIGH", "EXTREME"]:
        for loc_key, loc_data in danger["locations"].items():
            if loc_data["heat_risk"] in ["HIGH", "EXTREME"]:
                alerts.append({
                    "type": "PREDICTIVE",
                    "category": "GRID",
                    "level": "WARNING" if loc_data["heat_risk"] == "HIGH" else "CRITICAL",
                    "title": f"PREDICTIVE: Extreme Grid Strain - {loc_data['location']}",
                    "message": f"Forecast high of {loc_data['max_temp_48h']}°F in next 48h. ERCOT grid strain anticipated.",
                    "location": loc_key,
                    "temperature": loc_data["max_temp_48h"],
                    "risk_type": "heat",
                })
    
    # Check for freeze risk
    if danger["overall"]["freeze_risk"] in ["MODERATE", "SEVERE", "EXTREME"]:
        for loc_key, loc_data in danger["locations"].items():
            if loc_data["freeze_risk"] in ["SEVERE", "EXTREME"]:
                alerts.append({
                    "type": "PREDICTIVE",
                    "category": "GRID",
                    "level": "CRITICAL",
                    "title": f"PREDICTIVE: Freeze Emergency - {loc_data['location']}",
                    "message": f"Forecast low of {loc_data['min_temp_48h']}°F in next 48h. 2021-level freeze risk.",
                    "location": loc_key,
                    "temperature": loc_data["min_temp_48h"],
                    "risk_type": "freeze",
                })
            elif loc_data["freeze_risk"] == "MODERATE":
                alerts.append({
                    "type": "PREDICTIVE",
                    "category": "GRID",
                    "level": "WARNING",
                    "title": f"PREDICTIVE: Freeze Warning - {loc_data['location']}",
                    "message": f"Forecast low of {loc_data['min_temp_48h']}°F in next 48h. Monitor grid conditions.",
                    "location": loc_key,
                    "temperature": loc_data["min_temp_48h"],
                    "risk_type": "freeze",
                })
    
    # Check for hurricane/storm alerts (port impact)
    forecasts_data = forecasts.get("HOUSTON")
    if forecasts_data:
        for alert in forecasts_data.alerts:
            if any(keyword in alert.event.lower() for keyword in ["hurricane", "tropical storm", "storm surge"]):
                alerts.append({
                    "type": "PREDICTIVE",
                    "category": "PORT",
                    "level": "CRITICAL" if "warning" in alert.event.lower() else "WARNING",
                    "title": f"PREDICTIVE: Port Chokepoint - {alert.event}",
                    "message": f"{alert.headline}. Port of Houston operations may be impacted.",
                    "alert_event": alert.event,
                    "risk_type": "storm",
                })
    
    return alerts
