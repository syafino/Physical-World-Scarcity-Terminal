"""
SQLAlchemy ORM Models for PWST

Defines the database schema using SQLAlchemy with GeoAlchemy2 for spatial types.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Interval,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    type_annotation_map = {
        dict[str, Any]: JSONB,
    }


class Region(Base):
    """Geographic regions (states, watersheds, grid zones)."""

    __tablename__ = "regions"

    region_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    region_type: Mapped[str] = mapped_column(String(50), nullable=False)
    geometry = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=True)
    parent_region_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("regions.region_id"), nullable=True
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    parent = relationship("Region", remote_side=[region_id], backref="children")
    stations = relationship("Station", back_populates="region")

    __table_args__ = (
        Index("idx_regions_geometry", geometry, postgresql_using="gist"),
        Index("idx_regions_code", code),
        Index("idx_regions_type", region_type),
    )


class DataSource(Base):
    """External data sources (APIs)."""

    __tablename__ = "data_sources"

    source_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    api_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    rate_limit_per_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_free: Mapped[bool] = mapped_column(Boolean, default=True)
    auth_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    last_successful_fetch: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    indicators = relationship("Indicator", back_populates="source")
    stations = relationship("Station", back_populates="source")
    ingestion_runs = relationship("IngestionRun", back_populates="source")


class Indicator(Base):
    """Metrics/indicators we track."""

    __tablename__ = "indicators"

    indicator_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    function_code: Mapped[str] = mapped_column(String(4), nullable=False)
    source_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("data_sources.source_id"), nullable=True
    )
    update_frequency = mapped_column(Interval, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    source = relationship("DataSource", back_populates="indicators")
    observations = relationship("Observation", back_populates="indicator")
    anomalies = relationship("Anomaly", back_populates="indicator")

    __table_args__ = (
        Index("idx_indicators_function", function_code),
        Index("idx_indicators_category", category),
    )


class Station(Base):
    """Physical monitoring stations (wells, gauges, etc.)."""

    __tablename__ = "stations"

    station_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("data_sources.source_id"), nullable=False
    )
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    station_type: Mapped[str] = mapped_column(String(50), nullable=False)
    location = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    region_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("regions.region_id"), nullable=True
    )
    elevation_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    aquifer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    source = relationship("DataSource", back_populates="stations")
    region = relationship("Region", back_populates="stations")
    observations = relationship("Observation", back_populates="station")
    anomalies = relationship("Anomaly", back_populates="station")

    __table_args__ = (
        Index("idx_stations_location", location, postgresql_using="gist"),
        Index("idx_stations_source", source_id),
        Index("idx_stations_type", station_type),
        Index("idx_stations_region", region_id),
        # Unique constraint on source + external_id
        Index("idx_stations_unique", source_id, external_id, unique=True),
    )


class Observation(Base):
    """Time-series observations from stations."""

    __tablename__ = "observations"

    observation_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    indicator_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("indicators.indicator_id"), nullable=False
    )
    station_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("stations.station_id"), nullable=True
    )
    region_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("regions.region_id"), nullable=True
    )
    location = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, primary_key=True
    )
    value: Mapped[float] = mapped_column(Float, nullable=False)
    value_raw: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    quality_flag: Mapped[str] = mapped_column(String(20), default="valid")
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    indicator = relationship("Indicator", back_populates="observations")
    station = relationship("Station", back_populates="observations")

    __table_args__ = (
        Index("idx_obs_indicator_time", indicator_id, observed_at.desc()),
        Index("idx_obs_station_time", station_id, observed_at.desc()),
        Index("idx_obs_region", region_id, observed_at.desc()),
        # Partitioning handled at SQL level
        {"postgresql_partition_by": "RANGE (observed_at)"},
    )


class Anomaly(Base):
    """Detected anomalies in observations."""

    __tablename__ = "anomalies"

    anomaly_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    indicator_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("indicators.indicator_id"), nullable=False
    )
    station_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("stations.station_id"), nullable=True
    )
    region_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("regions.region_id"), nullable=True
    )
    location = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    anomaly_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    baseline_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    observed_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    z_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    indicator = relationship("Indicator", back_populates="anomalies")
    station = relationship("Station", back_populates="anomalies")

    __table_args__ = (
        Index("idx_anomalies_time", detected_at.desc()),
        Index("idx_anomalies_severity", severity.desc()),
        Index("idx_anomalies_indicator", indicator_id),
        Index(
            "idx_anomalies_unacked",
            is_acknowledged,
            postgresql_where=(is_acknowledged == False),
        ),
    )


class CommandLog(Base):
    """Audit log for terminal commands."""

    __tablename__ = "command_log"

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    command_raw: Mapped[str] = mapped_column(String(500), nullable=False)
    function_code: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    region_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    parameters: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    response_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    result_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_cmdlog_session", session_id, executed_at.desc()),
        Index("idx_cmdlog_function", function_code, executed_at.desc()),
    )


class IngestionRun(Base):
    """Track data ingestion runs."""

    __tablename__ = "ingestion_runs"

    run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("data_sources.source_id"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="running")
    records_fetched: Mapped[int] = mapped_column(Integer, default=0)
    records_inserted: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )

    # Relationships
    source = relationship("DataSource", back_populates="ingestion_runs")

    __table_args__ = (
        Index("idx_ingestion_source", source_id, started_at.desc()),
        Index("idx_ingestion_status", status),
    )
