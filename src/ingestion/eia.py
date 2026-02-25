"""
EIA (Energy Information Administration) API Fetcher

Fetches electricity grid data for ERCOT (Texas) from EIA API v2.

API Documentation:
    - https://www.eia.gov/opendata/documentation.php
    - https://api.eia.gov/v2/electricity/rto/

Data Available:
    - Regional demand (MW)
    - Generation by fuel type (MW)
    - Interchange (imports/exports)
    - Day-ahead forecasts

Rate Limits:
    - Without API key: 30 requests/hour
    - With free API key: Unlimited (register at eia.gov)
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog

from src.config.settings import settings
from src.db.connection import get_db_context
from src.db.models import DataSource, Indicator, Observation, Region
from src.ingestion.base import BaseFetcher, FetchError

logger = structlog.get_logger(__name__)


class EIAGridFetcher(BaseFetcher):
    """
    Fetcher for EIA electricity grid data.
    
    Focuses on ERCOT (Texas) grid operations:
    - Real-time demand
    - Generation by fuel type
    - Capacity margins
    """

    source_code = "EIA_API"
    base_url = "https://api.eia.gov/v2"

    # ERCOT respondent ID in EIA data
    ERCOT_RESPONDENT = "ERCO"

    # Fuel type codes
    FUEL_TYPES = {
        "WAT": "hydro",
        "WND": "wind",
        "SUN": "solar",
        "NG": "natural_gas",
        "COL": "coal",
        "NUC": "nuclear",
        "OTH": "other",
        "OIL": "oil",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        hours_back: int = 24,
        respondent: str = "ERCO",
    ):
        """
        Initialize EIA fetcher.
        
        Args:
            api_key: EIA API key (optional, increases rate limits)
            hours_back: Hours of historical data to fetch
            respondent: Grid operator code (default: ERCO for ERCOT)
        """
        super().__init__()
        self.api_key = api_key or settings.eia_api_key
        self.hours_back = hours_back
        self.respondent = respondent

    def _build_params(
        self,
        facets: Optional[dict] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        frequency: str = "hourly",
        data_columns: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Build query parameters for EIA API."""
        params: dict[str, Any] = {
            "frequency": frequency,
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": 5000,
        }

        if self.api_key:
            params["api_key"] = self.api_key

        if facets:
            for key, values in facets.items():
                if isinstance(values, list):
                    for i, v in enumerate(values):
                        params[f"facets[{key}][]"] = v
                else:
                    params[f"facets[{key}][]"] = values

        if start:
            params["start"] = start.strftime("%Y-%m-%dT%H")
        if end:
            params["end"] = end.strftime("%Y-%m-%dT%H")

        if data_columns:
            for col in data_columns:
                params["data[]"] = col

        return params

    def fetch(self) -> dict[str, Any]:
        """
        Fetch ERCOT grid data from EIA API.
        
        Fetches:
        1. Regional demand data
        2. Generation by fuel type
        
        Returns:
            Dict with demand and generation data
        """
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=self.hours_back)

        self.log.info(
            "fetching_eia_data",
            respondent=self.respondent,
            start=start_time.isoformat(),
            end=end_time.isoformat(),
        )

        results = {
            "demand": [],
            "generation": [],
            "interchange": [],
        }

        # 1. Fetch demand data
        try:
            demand_params = self._build_params(
                facets={"respondent": self.respondent},
                start=start_time,
                end=end_time,
                data_columns=["value"],
            )
            demand_response = self.get_json(
                "electricity/rto/region-data/data/",
                params=demand_params,
            )
            results["demand"] = demand_response.get("response", {}).get("data", [])
            self.log.info("demand_data_fetched", count=len(results["demand"]))
        except FetchError as e:
            self.log.warning("demand_fetch_failed", error=str(e))

        # 2. Fetch generation by fuel type
        try:
            gen_params = self._build_params(
                facets={"respondent": self.respondent},
                start=start_time,
                end=end_time,
                data_columns=["value"],
            )
            gen_response = self.get_json(
                "electricity/rto/fuel-type-data/data/",
                params=gen_params,
            )
            results["generation"] = gen_response.get("response", {}).get("data", [])
            self.log.info("generation_data_fetched", count=len(results["generation"]))
        except FetchError as e:
            self.log.warning("generation_fetch_failed", error=str(e))

        # 3. Fetch interchange (imports/exports)
        try:
            interchange_params = self._build_params(
                facets={"fromba": self.respondent},
                start=start_time,
                end=end_time,
                data_columns=["value"],
            )
            interchange_response = self.get_json(
                "electricity/rto/interchange-data/data/",
                params=interchange_params,
            )
            results["interchange"] = interchange_response.get("response", {}).get(
                "data", []
            )
            self.log.info(
                "interchange_data_fetched", count=len(results["interchange"])
            )
        except FetchError as e:
            self.log.warning("interchange_fetch_failed", error=str(e))

        return results

    def parse(self, raw_data: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Parse EIA API response into normalized records.
        
        Args:
            raw_data: Raw response with demand/generation data
            
        Returns:
            List of normalized observation records
        """
        records = []

        # Parse demand data
        for item in raw_data.get("demand", []):
            try:
                record = self._parse_demand_record(item)
                if record:
                    records.append(record)
            except Exception as e:
                self.log.warning("parse_demand_error", error=str(e), item=item)

        # Parse generation data (by fuel type)
        for item in raw_data.get("generation", []):
            try:
                record = self._parse_generation_record(item)
                if record:
                    records.append(record)
            except Exception as e:
                self.log.warning("parse_generation_error", error=str(e), item=item)

        self.log.info("parsed_records", count=len(records))
        return records

    def _parse_demand_record(self, item: dict) -> Optional[dict[str, Any]]:
        """Parse a single demand record."""
        period = item.get("period")
        value = item.get("value")
        type_name = item.get("type-name", "").lower()

        if not period or value is None:
            return None

        try:
            numeric_value = float(value)
        except (ValueError, TypeError):
            return None

        # Parse period (format: 2026-02-25T14)
        try:
            observed_at = datetime.strptime(period, "%Y-%m-%dT%H")
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

        # Map to indicator code
        indicator_code = "GRID_DEMAND"
        if "generation" in type_name:
            indicator_code = "GRID_GENERATION"

        return {
            "indicator_code": indicator_code,
            "value": numeric_value,
            "observed_at": observed_at,
            "unit": "MW",
            "type_name": type_name,
            "raw": item,
        }

    def _parse_generation_record(self, item: dict) -> Optional[dict[str, Any]]:
        """Parse a single generation-by-fuel record."""
        period = item.get("period")
        value = item.get("value")
        fuel_type = item.get("fueltype")

        if not period or value is None or not fuel_type:
            return None

        try:
            numeric_value = float(value)
        except (ValueError, TypeError):
            return None

        # Parse period
        try:
            observed_at = datetime.strptime(period, "%Y-%m-%dT%H")
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

        # Map fuel type to indicator
        fuel_name = self.FUEL_TYPES.get(fuel_type, fuel_type.lower())
        indicator_code = f"GRID_{fuel_name.upper()}"

        # Only track major fuel types we have indicators for
        if indicator_code not in ["GRID_WIND", "GRID_SOLAR", "GRID_GAS"]:
            indicator_code = "GRID_GENERATION"  # Aggregate others

        return {
            "indicator_code": indicator_code,
            "value": numeric_value,
            "observed_at": observed_at,
            "unit": "MW",
            "fuel_type": fuel_name,
            "raw": item,
        }

    def load(self, records: list[dict[str, Any]]) -> tuple[int, int]:
        """
        Load parsed records into database.
        
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
            # Get ERCOT region
            ercot_region = db.query(Region).filter_by(code="ERCOT").first()
            if not ercot_region:
                self.log.warning("ercot_region_not_found")
                ercot_region = db.query(Region).filter_by(code="US-TX").first()

            # Cache indicators
            indicator_cache: dict[str, Indicator] = {}

            for record in records:
                indicator_code = record["indicator_code"]

                # Get or cache indicator
                if indicator_code not in indicator_cache:
                    indicator = (
                        db.query(Indicator).filter_by(code=indicator_code).first()
                    )
                    if indicator:
                        indicator_cache[indicator_code] = indicator
                    else:
                        self.log.warning(
                            "indicator_not_found", code=indicator_code
                        )
                        continue

                indicator = indicator_cache.get(indicator_code)
                if not indicator:
                    continue

                # Check for existing observation
                existing = (
                    db.query(Observation)
                    .filter_by(
                        indicator_id=indicator.indicator_id,
                        region_id=ercot_region.region_id if ercot_region else None,
                        observed_at=record["observed_at"],
                    )
                    .first()
                )

                if existing:
                    if existing.value != record["value"]:
                        existing.value = record["value"]
                        existing.ingested_at = datetime.now(timezone.utc)
                        updated += 1
                else:
                    obs = Observation(
                        indicator_id=indicator.indicator_id,
                        region_id=ercot_region.region_id if ercot_region else None,
                        observed_at=record["observed_at"],
                        value=record["value"],
                        quality_flag="valid",
                        value_raw=record.get("raw"),
                    )
                    db.add(obs)
                    inserted += 1

            db.commit()

        self.log.info(
            "load_completed",
            observations_inserted=inserted,
            observations_updated=updated,
        )

        return inserted, updated


def fetch_ercot_grid(hours_back: int = 24) -> dict[str, Any]:
    """
    Convenience function to fetch ERCOT grid data.
    
    Args:
        hours_back: Hours of data to fetch
        
    Returns:
        Summary dict with counts and status
    """
    with EIAGridFetcher(hours_back=hours_back) as fetcher:
        return fetcher.run()
