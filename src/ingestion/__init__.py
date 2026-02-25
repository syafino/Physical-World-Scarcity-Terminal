"""
Data Ingestion Module

Handles fetching data from external APIs (USGS, EIA, etc.)
and loading it into the database.
"""

from src.ingestion.base import BaseFetcher
from src.ingestion.usgs import USGSWaterFetcher
from src.ingestion.eia import EIAGridFetcher

__all__ = [
    "BaseFetcher",
    "USGSWaterFetcher",
    "EIAGridFetcher",
]
