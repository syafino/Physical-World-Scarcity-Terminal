"""
Base Fetcher Class

Abstract base class for all data fetchers with common functionality
for retry logic, rate limiting, and logging.
"""

import abc
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config.settings import settings
from src.db.connection import get_db_context
from src.db.models import DataSource, IngestionRun

logger = structlog.get_logger(__name__)


class FetchError(Exception):
    """Base exception for fetch errors."""

    pass


class RateLimitError(FetchError):
    """Raised when API rate limit is hit."""

    pass


class BaseFetcher(abc.ABC):
    """
    Abstract base class for data fetchers.
    
    Subclasses must implement:
        - source_code: The data source identifier
        - fetch(): Main fetch logic
        - parse(): Parse raw API response
        - load(): Load parsed data into database
    """

    # Must be overridden by subclasses
    source_code: str = ""
    base_url: str = ""
    timeout_seconds: int = 30

    def __init__(self):
        self.client = httpx.Client(
            timeout=httpx.Timeout(self.timeout_seconds),
            headers={"User-Agent": f"PWST/{settings.environment}"},
        )
        self._run_id: Optional[int] = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.close()

    @property
    def log(self):
        """Get logger with source context."""
        return logger.bind(source=self.source_code)

    def start_run(self) -> int:
        """Record the start of an ingestion run."""
        with get_db_context() as db:
            source = db.query(DataSource).filter_by(code=self.source_code).first()
            if not source:
                raise ValueError(f"Unknown source: {self.source_code}")

            run = IngestionRun(
                source_id=source.source_id,
                status="running",
            )
            db.add(run)
            db.flush()
            self._run_id = run.run_id
            self.log.info("ingestion_run_started", run_id=self._run_id)
            return self._run_id

    def complete_run(
        self,
        status: str = "completed",
        records_fetched: int = 0,
        records_inserted: int = 0,
        records_updated: int = 0,
        error_message: Optional[str] = None,
    ):
        """Record the completion of an ingestion run."""
        if not self._run_id:
            return

        with get_db_context() as db:
            run = db.query(IngestionRun).filter_by(run_id=self._run_id).first()
            if run:
                run.status = status
                run.completed_at = datetime.now(timezone.utc)
                run.records_fetched = records_fetched
                run.records_inserted = records_inserted
                run.records_updated = records_updated
                run.error_message = error_message

            # Update source last_successful_fetch
            if status == "completed":
                source = db.query(DataSource).filter_by(code=self.source_code).first()
                if source:
                    source.last_successful_fetch = datetime.now(timezone.utc)

        self.log.info(
            "ingestion_run_completed",
            run_id=self._run_id,
            status=status,
            records_fetched=records_fetched,
            records_inserted=records_inserted,
        )

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def _request(
        self,
        method: str,
        url: str,
        params: Optional[dict] = None,
        **kwargs,
    ) -> httpx.Response:
        """
        Make HTTP request with retry logic.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL or path (will be joined with base_url)
            params: Query parameters
            **kwargs: Additional arguments passed to httpx
            
        Returns:
            httpx.Response object
            
        Raises:
            RateLimitError: If rate limited (429)
            FetchError: For other HTTP errors
        """
        if not url.startswith("http"):
            url = f"{self.base_url.rstrip('/')}/{url.lstrip('/')}"

        self.log.debug("api_request", method=method, url=url, params=params)

        response = self.client.request(method, url, params=params, **kwargs)

        if response.status_code == 429:
            raise RateLimitError(f"Rate limited by {self.source_code}")

        if response.status_code >= 400:
            raise FetchError(
                f"API error {response.status_code}: {response.text[:200]}"
            )

        return response

    def get(self, url: str, params: Optional[dict] = None, **kwargs) -> httpx.Response:
        """Make GET request."""
        return self._request("GET", url, params=params, **kwargs)

    def get_json(self, url: str, params: Optional[dict] = None, **kwargs) -> Any:
        """Make GET request and return JSON."""
        response = self.get(url, params=params, **kwargs)
        return response.json()

    @abc.abstractmethod
    def fetch(self) -> dict[str, Any]:
        """
        Fetch data from the external API.
        
        Returns:
            Raw data from API (typically dict or list)
        """
        pass

    @abc.abstractmethod
    def parse(self, raw_data: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Parse raw API response into normalized records.
        
        Args:
            raw_data: Raw response from fetch()
            
        Returns:
            List of normalized records ready for database
        """
        pass

    @abc.abstractmethod
    def load(self, records: list[dict[str, Any]]) -> tuple[int, int]:
        """
        Load parsed records into the database.
        
        Args:
            records: List of normalized records from parse()
            
        Returns:
            Tuple of (records_inserted, records_updated)
        """
        pass

    def run(self) -> dict[str, Any]:
        """
        Execute full ETL pipeline: fetch -> parse -> load.
        
        Returns:
            Summary dict with counts and status
        """
        self.start_run()
        
        try:
            # Fetch
            self.log.info("fetch_started")
            raw_data = self.fetch()
            
            # Parse
            self.log.info("parse_started")
            records = self.parse(raw_data)
            records_fetched = len(records)
            self.log.info("parse_completed", record_count=records_fetched)
            
            # Load
            self.log.info("load_started")
            inserted, updated = self.load(records)
            
            # Complete
            self.complete_run(
                status="completed",
                records_fetched=records_fetched,
                records_inserted=inserted,
                records_updated=updated,
            )
            
            return {
                "status": "completed",
                "records_fetched": records_fetched,
                "records_inserted": inserted,
                "records_updated": updated,
            }

        except Exception as e:
            self.log.error("ingestion_failed", error=str(e))
            self.complete_run(status="failed", error_message=str(e))
            raise
