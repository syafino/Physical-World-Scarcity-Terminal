"""
USGS National Water Information System (NWIS) Fetcher

Fetches groundwater levels and site information for Texas from USGS.

API Documentation:
    - https://waterservices.usgs.gov/
    - https://waterservices.usgs.gov/rest/GW-Levels-Service.html

Data Available:
    - Groundwater levels (depth to water, water level elevation)
    - Site metadata (location, aquifer, well depth)
    - Historical data (decades available)

Rate Limits:
    - No authentication required
    - No hard rate limits (be respectful, batch requests)
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.config.settings import settings
from src.db.connection import get_db_context
from src.db.models import DataSource, Indicator, Observation, Region, Station
from src.ingestion.base import BaseFetcher, FetchError

logger = structlog.get_logger(__name__)


class USGSWaterFetcher(BaseFetcher):
    """
    Fetcher for USGS groundwater level data.
    
    Focuses on Texas groundwater monitoring wells.
    Uses USGS Water Services REST API.
    """

    source_code = "USGS_NWIS"
    base_url = "https://waterservices.usgs.gov/nwis"

    # USGS parameter codes
    # 72019 = Depth to water level, feet below land surface
    # 72020 = Elevation of water surface, feet above NGVD29
    # 62610 = Groundwater level above NGVD 1929, feet
    # 62611 = Groundwater level above NAVD 1988, feet
    GROUNDWATER_PARAM_CODES = ["72019", "72020", "62610", "62611"]

    # Texas state code for USGS
    STATE_CODE = "tx"

    def __init__(
        self,
        state_code: str = "tx",
        days_back: int = 7,
        param_codes: Optional[list[str]] = None,
    ):
        """
        Initialize USGS fetcher.
        
        Args:
            state_code: USGS state code (default: tx for Texas)
            days_back: Number of days of data to fetch (default: 7)
            param_codes: USGS parameter codes to fetch (default: groundwater levels)
        """
        super().__init__()
        self.state_code = state_code
        self.days_back = days_back
        self.param_codes = param_codes or self.GROUNDWATER_PARAM_CODES

    def fetch(self) -> dict[str, Any]:
        """
        Fetch groundwater data from USGS NWIS.
        
        Returns:
            Dict containing site info and time series data
        """
        # Calculate date range
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=self.days_back)

        # Fetch groundwater levels
        # Using the instantaneous values service for recent data
        params = {
            "format": "json",
            "stateCd": self.state_code,
            "parameterCd": ",".join(self.param_codes),
            "startDT": start_date.strftime("%Y-%m-%d"),
            "endDT": end_date.strftime("%Y-%m-%d"),
            "siteType": "GW",  # Groundwater wells only
            "siteStatus": "active",
        }

        self.log.info(
            "fetching_usgs_data",
            state=self.state_code,
            start_date=params["startDT"],
            end_date=params["endDT"],
        )

        try:
            # Use instantaneous values endpoint
            response = self.get_json("iv/", params=params)
            return response
        except FetchError as e:
            # Try daily values as fallback
            self.log.warning("iv_endpoint_failed_trying_dv", error=str(e))
            params["format"] = "json"
            response = self.get_json("dv/", params=params)
            return response

    def parse(self, raw_data: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Parse USGS JSON response into normalized records.
        
        Args:
            raw_data: Raw JSON from USGS API
            
        Returns:
            List of dicts with station info and observations
        """
        records = []

        # USGS JSON structure: value -> timeSeries[]
        time_series = raw_data.get("value", {}).get("timeSeries", [])

        if not time_series:
            self.log.warning("no_timeseries_in_response")
            return records

        for series in time_series:
            try:
                # Extract site info
                source_info = series.get("sourceInfo", {})
                site_code = source_info.get("siteCode", [{}])[0].get("value")
                site_name = source_info.get("siteName", "")

                # Get location
                geo_location = source_info.get("geoLocation", {}).get(
                    "geogLocation", {}
                )
                latitude = geo_location.get("latitude")
                longitude = geo_location.get("longitude")

                if not all([site_code, latitude, longitude]):
                    continue

                # Get site properties
                site_props = {
                    prop.get("name"): prop.get("value")
                    for prop in source_info.get("siteProperty", [])
                }
                aquifer_name = site_props.get("aquiferCd", "")

                # Extract variable info
                variable = series.get("variable", {})
                param_code = variable.get("variableCode", [{}])[0].get("value")
                unit = variable.get("unit", {}).get("unitCode", "ft")

                # Process values
                values = series.get("values", [{}])[0].get("value", [])

                for val in values:
                    value = val.get("value")
                    if value is None or value == "":
                        continue

                    try:
                        numeric_value = float(value)
                    except (ValueError, TypeError):
                        continue

                    # Parse timestamp
                    datetime_str = val.get("dateTime")
                    if not datetime_str:
                        continue

                    try:
                        observed_at = datetime.fromisoformat(
                            datetime_str.replace("Z", "+00:00")
                        )
                    except ValueError:
                        continue

                    # Quality flag
                    qualifiers = val.get("qualifiers", [])
                    quality_flag = "valid"
                    if "e" in qualifiers or "E" in qualifiers:
                        quality_flag = "estimated"
                    elif "P" in qualifiers:
                        quality_flag = "provisional"

                    records.append(
                        {
                            "site_code": site_code,
                            "site_name": site_name,
                            "latitude": latitude,
                            "longitude": longitude,
                            "aquifer_name": aquifer_name,
                            "param_code": param_code,
                            "value": numeric_value,
                            "unit": unit,
                            "observed_at": observed_at,
                            "quality_flag": quality_flag,
                            "raw": val,
                        }
                    )

            except Exception as e:
                self.log.warning(
                    "parse_error_for_series",
                    error=str(e),
                    site=series.get("sourceInfo", {}).get("siteCode"),
                )
                continue

        self.log.info("parsed_records", count=len(records))
        return records

    def load(self, records: list[dict[str, Any]]) -> tuple[int, int]:
        """
        Load parsed records into database.
        
        Creates/updates stations and inserts observations.
        
        Args:
            records: Parsed records from parse()
            
        Returns:
            Tuple of (inserted_count, updated_count)
        """
        if not records:
            return 0, 0

        inserted = 0
        updated = 0

        with get_db_context() as db:
            # Get source and indicator references
            source = db.query(DataSource).filter_by(code=self.source_code).first()
            if not source:
                raise ValueError(f"Source {self.source_code} not found")

            # Get Texas region
            texas_region = db.query(Region).filter_by(code="US-TX").first()

            # Get groundwater indicator
            gw_indicator = (
                db.query(Indicator).filter_by(code="GW_LEVEL").first()
            )
            if not gw_indicator:
                raise ValueError("GW_LEVEL indicator not found")

            # Group records by site
            sites: dict[str, list[dict]] = {}
            for record in records:
                site_code = record["site_code"]
                if site_code not in sites:
                    sites[site_code] = []
                sites[site_code].append(record)

            # Process each site
            for site_code, site_records in sites.items():
                first_record = site_records[0]

                # Upsert station
                point = Point(first_record["longitude"], first_record["latitude"])

                stmt = insert(Station).values(
                    external_id=site_code,
                    source_id=source.source_id,
                    name=first_record["site_name"],
                    station_type="groundwater_well",
                    location=from_shape(point, srid=4326),
                    region_id=texas_region.region_id if texas_region else None,
                    aquifer_name=first_record.get("aquifer_name"),
                    is_active=True,
                    metadata_={
                        "usgs_site_code": site_code,
                        "param_codes": list(
                            set(r["param_code"] for r in site_records)
                        ),
                    },
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["source_id", "external_id"],
                    set_={
                        "name": stmt.excluded.name,
                        "aquifer_name": stmt.excluded.aquifer_name,
                        "updated_at": datetime.now(timezone.utc),
                    },
                )
                db.execute(stmt)
                db.flush()

                # Get station ID
                station = (
                    db.query(Station)
                    .filter_by(source_id=source.source_id, external_id=site_code)
                    .first()
                )

                if not station:
                    continue

                # Insert observations
                for record in site_records:
                    # Check for existing observation
                    existing = (
                        db.query(Observation)
                        .filter_by(
                            indicator_id=gw_indicator.indicator_id,
                            station_id=station.station_id,
                            observed_at=record["observed_at"],
                        )
                        .first()
                    )

                    if existing:
                        # Update if value changed
                        if existing.value != record["value"]:
                            existing.value = record["value"]
                            existing.quality_flag = record["quality_flag"]
                            existing.ingested_at = datetime.now(timezone.utc)
                            updated += 1
                    else:
                        # Insert new observation
                        obs = Observation(
                            indicator_id=gw_indicator.indicator_id,
                            station_id=station.station_id,
                            region_id=texas_region.region_id if texas_region else None,
                            location=from_shape(point, srid=4326),
                            observed_at=record["observed_at"],
                            value=record["value"],
                            quality_flag=record["quality_flag"],
                            value_raw=record.get("raw"),
                        )
                        db.add(obs)
                        inserted += 1

            db.commit()

        self.log.info(
            "load_completed",
            sites_processed=len(sites),
            observations_inserted=inserted,
            observations_updated=updated,
        )

        return inserted, updated


def fetch_texas_groundwater(days_back: int = 7) -> dict[str, Any]:
    """
    Convenience function to fetch Texas groundwater data.
    
    Args:
        days_back: Number of days of data to fetch
        
    Returns:
        Summary dict with counts and status
    """
    with USGSWaterFetcher(state_code="tx", days_back=days_back) as fetcher:
        return fetcher.run()
