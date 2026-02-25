"""
Port of Houston Logistics Data Module

Since real-time AIS data requires expensive commercial APIs ($500+/mo),
this module provides a realistic simulation engine for MVP based on:
- Historical Port of Houston statistics
- Temporal patterns (weekday/weekend, seasonal, hurricane season)
- Random variation for realism

Future: Replace with Spire AIS (Snowflake Marketplace) when budget allows.
"""

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog

from src.config.settings import settings
from src.db.connection import get_db_session
from src.db.models import DataSource, Indicator, IngestionRun, Observation, Station

logger = structlog.get_logger(__name__)

# Port of Houston statistics (based on public data)
# Source: Port of Houston Authority Annual Reports
PORT_STATS = {
    "HOU": {
        "name": "Port of Houston",
        "latitude": 29.7355,
        "longitude": -95.0128,
        "avg_vessels_in_port": 45,  # Average vessels at berth
        "avg_vessels_waiting": 8,   # Average at anchor
        "avg_dwell_hours": 48,      # Average time at berth
        "daily_throughput_teu": 8500,  # TEU per day
        "peak_hour_multiplier": 1.3,
        "weekend_multiplier": 0.7,
        "hurricane_season_variance": 0.4,  # June-November
    },
    "GAL": {
        "name": "Port of Galveston",
        "latitude": 29.3013,
        "longitude": -94.7977,
        "avg_vessels_in_port": 12,
        "avg_vessels_waiting": 3,
        "avg_dwell_hours": 36,
        "daily_throughput_teu": 1200,
        "peak_hour_multiplier": 1.2,
        "weekend_multiplier": 0.6,
        "hurricane_season_variance": 0.5,
    },
    "TXC": {
        "name": "Texas City Terminal",
        "latitude": 29.3838,
        "longitude": -94.9027,
        "avg_vessels_in_port": 8,
        "avg_vessels_waiting": 2,
        "avg_dwell_hours": 24,
        "daily_throughput_teu": 800,
        "peak_hour_multiplier": 1.1,
        "weekend_multiplier": 0.8,
        "hurricane_season_variance": 0.3,
    },
}


class PortSimulator:
    """
    Realistic port traffic simulator for Houston Ship Channel.
    
    Generates vessel counts, wait times, and throughput data with:
    - Circadian patterns (busier during business hours)
    - Weekly patterns (slower weekends)
    - Seasonal patterns (hurricane season variance)
    - Random events (weather delays, mechanical issues)
    """
    
    SOURCE_CODE = "PORT_SIM"
    SOURCE_NAME = "Port Simulation Engine"
    
    def __init__(self):
        self._congestion_event_active = False
        self._congestion_severity = 0.0
        
    def _get_time_multipliers(self, dt: datetime) -> dict[str, float]:
        """Calculate time-based multipliers for realistic variation."""
        hour = dt.hour
        weekday = dt.weekday()
        month = dt.month
        
        # Circadian pattern (busier 8am-6pm)
        if 8 <= hour <= 18:
            hour_mult = 1.0 + 0.3 * math.sin((hour - 8) * math.pi / 10)
        else:
            hour_mult = 0.7
            
        # Weekly pattern (weekends slower)
        weekend_mult = 0.7 if weekday >= 5 else 1.0
        
        # Seasonal pattern (hurricane season June-November)
        if 6 <= month <= 11:
            # More variance during hurricane season
            seasonal_mult = 1.0 + random.uniform(-0.2, 0.3)
        else:
            seasonal_mult = 1.0
            
        return {
            "hour": hour_mult,
            "weekend": weekend_mult,
            "seasonal": seasonal_mult,
        }
    
    def _maybe_trigger_event(self) -> None:
        """Randomly trigger congestion events for realism."""
        if not self._congestion_event_active:
            # 5% chance per hour of a congestion event starting
            if random.random() < 0.05:
                self._congestion_event_active = True
                self._congestion_severity = random.uniform(0.3, 0.8)
                logger.info("congestion_event_started", severity=self._congestion_severity)
        else:
            # 20% chance per hour of event resolving
            if random.random() < 0.20:
                self._congestion_event_active = False
                self._congestion_severity = 0.0
                logger.info("congestion_event_resolved")
    
    def generate_observation(
        self, 
        port_code: str, 
        indicator_code: str,
        observed_at: Optional[datetime] = None
    ) -> dict[str, Any]:
        """Generate a single simulated observation."""
        if port_code not in PORT_STATS:
            raise ValueError(f"Unknown port code: {port_code}")
            
        stats = PORT_STATS[port_code]
        dt = observed_at or datetime.now(timezone.utc)
        multipliers = self._get_time_multipliers(dt)
        
        # Combined multiplier
        combined_mult = (
            multipliers["hour"] * 
            multipliers["weekend"] * 
            multipliers["seasonal"]
        )
        
        # Add congestion event impact
        if self._congestion_event_active:
            congestion_mult = 1.0 + self._congestion_severity
        else:
            congestion_mult = 1.0
        
        # Generate value based on indicator
        if indicator_code == "PORT_VESSELS":
            base = stats["avg_vessels_in_port"]
            value = base * combined_mult * random.uniform(0.8, 1.2)
            
        elif indicator_code == "PORT_WAITING":
            base = stats["avg_vessels_waiting"]
            value = base * combined_mult * congestion_mult * random.uniform(0.5, 1.5)
            # Congestion events dramatically increase waiting vessels
            if self._congestion_event_active:
                value *= (1 + self._congestion_severity * 2)
                
        elif indicator_code == "PORT_DWELL":
            base = stats["avg_dwell_hours"]
            value = base * congestion_mult * random.uniform(0.9, 1.3)
            
        elif indicator_code == "PORT_THROUGHPUT":
            base = stats["daily_throughput_teu"]
            # Throughput inversely affected by congestion
            if self._congestion_event_active:
                value = base * combined_mult * (1 - self._congestion_severity * 0.3)
            else:
                value = base * combined_mult * random.uniform(0.9, 1.1)
        else:
            raise ValueError(f"Unknown indicator: {indicator_code}")
            
        return {
            "port_code": port_code,
            "port_name": stats["name"],
            "latitude": stats["latitude"],
            "longitude": stats["longitude"],
            "indicator_code": indicator_code,
            "value": round(value, 1),
            "observed_at": dt.isoformat(),
            "is_simulated": True,
            "congestion_event": self._congestion_event_active,
        }
    
    def fetch(self, hours_back: int = 24) -> list[dict[str, Any]]:
        """Generate simulated port data for all ports and indicators."""
        self._maybe_trigger_event()
        
        records = []
        now = datetime.now(timezone.utc)
        
        indicators = ["PORT_VESSELS", "PORT_WAITING", "PORT_DWELL", "PORT_THROUGHPUT"]
        
        for port_code in PORT_STATS:
            for indicator in indicators:
                # Generate current observation
                obs = self.generate_observation(port_code, indicator, now)
                records.append(obs)
                
        logger.info(
            "port_data_generated",
            source=self.SOURCE_CODE,
            record_count=len(records),
            congestion_active=self._congestion_event_active,
        )
        
        return records
    
    def parse(self, raw_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Parse simulated data (already in correct format)."""
        return raw_data
    
    def load(self, records: list[dict[str, Any]]) -> dict[str, int]:
        """Load port observations into database."""
        from geoalchemy2 import WKTElement
        
        with get_db_session() as db:
            # Ensure data source exists
            source = db.query(DataSource).filter_by(code=self.SOURCE_CODE).first()
            if not source:
                source = DataSource(
                    code=self.SOURCE_CODE,
                    name=self.SOURCE_NAME,
                    base_url="simulation://localhost",
                    api_type="SIMULATION",
                    is_free=True,
                    status="active",
                )
                db.add(source)
                db.flush()
            
            # Create ingestion run
            run = IngestionRun(
                source_id=source.source_id,
                status="running",
            )
            db.add(run)
            db.flush()
            
            inserted = 0
            
            for record in records:
                # Get or create indicator
                indicator = db.query(Indicator).filter_by(
                    code=record["indicator_code"]
                ).first()
                
                if not indicator:
                    # Create indicator if it doesn't exist
                    unit_map = {
                        "PORT_VESSELS": "count",
                        "PORT_WAITING": "count", 
                        "PORT_DWELL": "hours",
                        "PORT_THROUGHPUT": "TEU",
                    }
                    indicator = Indicator(
                        code=record["indicator_code"],
                        name=record["indicator_code"].replace("_", " ").title(),
                        category="logistics",
                        unit=unit_map.get(record["indicator_code"], "count"),
                        function_code="FLOW",
                        source_id=source.source_id,
                    )
                    db.add(indicator)
                    db.flush()
                
                # Get or create station for the port
                station = db.query(Station).filter_by(
                    external_id=record["port_code"],
                    source_id=source.source_id,
                ).first()
                
                if not station:
                    location = WKTElement(
                        f"POINT({record['longitude']} {record['latitude']})",
                        srid=4326
                    )
                    station = Station(
                        external_id=record["port_code"],
                        source_id=source.source_id,
                        name=record["port_name"],
                        station_type="port",
                        location=location,
                    )
                    db.add(station)
                    db.flush()
                
                # Create observation
                observed_at = datetime.fromisoformat(record["observed_at"].replace("Z", "+00:00"))
                
                obs = Observation(
                    indicator_id=indicator.indicator_id,
                    station_id=station.station_id,
                    location=station.location,
                    observed_at=observed_at,
                    value=record["value"],
                    value_raw=record,
                    quality_flag="simulated",
                )
                db.add(obs)
                inserted += 1
            
            # Update run status
            run.status = "completed"
            run.records_fetched = len(records)
            run.records_inserted = inserted
            
            db.commit()
            
            logger.info(
                "port_data_loaded",
                source=self.SOURCE_CODE,
                inserted=inserted,
            )
            
            return {"inserted": inserted, "updated": 0}


# Celery task wrapper
def fetch_port_data() -> dict[str, Any]:
    """Fetch and load port simulation data."""
    simulator = PortSimulator()
    
    try:
        raw_data = simulator.fetch()
        parsed = simulator.parse(raw_data)
        result = simulator.load(parsed)
        
        return {
            "status": "completed",
            "records_fetched": len(parsed),
            "records_inserted": result["inserted"],
        }
    except Exception as e:
        logger.error("port_ingestion_failed", error=str(e))
        return {
            "status": "failed",
            "error": str(e),
        }
