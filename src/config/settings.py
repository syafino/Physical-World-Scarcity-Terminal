"""
PWST Application Settings

Loads configuration from environment variables with sensible defaults.
Uses Pydantic Settings for validation and type coercion.
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─────────────────────────────────────────────────────────────
    # Database Configuration
    # ─────────────────────────────────────────────────────────────
    postgres_host: str = Field(default="localhost", description="PostgreSQL host")
    postgres_port: int = Field(default=5432, description="PostgreSQL port")
    postgres_db: str = Field(default="pwst", description="Database name")
    postgres_user: str = Field(default="pwst", description="Database user")
    postgres_password: str = Field(default="pwst_local_dev", description="Database password")

    @computed_field
    @property
    def database_url(self) -> str:
        """Construct database connection URL."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field
    @property
    def async_database_url(self) -> str:
        """Construct async database connection URL."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ─────────────────────────────────────────────────────────────
    # Redis Configuration
    # ─────────────────────────────────────────────────────────────
    redis_host: str = Field(default="localhost", description="Redis host")
    redis_port: int = Field(default=6379, description="Redis port")

    @computed_field
    @property
    def redis_url(self) -> str:
        """Construct Redis connection URL."""
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    # ─────────────────────────────────────────────────────────────
    # External API Configuration
    # ─────────────────────────────────────────────────────────────
    eia_api_key: Optional[str] = Field(
        default=None,
        description="EIA API key (optional, increases rate limits)",
    )
    mapbox_access_token: Optional[str] = Field(
        default=None,
        description="Mapbox access token for map tiles",
    )
    mapbox_style: str = Field(
        default="mapbox://styles/mapbox/dark-v11",
        description="Mapbox style URL",
    )

    # ─────────────────────────────────────────────────────────────
    # Application Settings
    # ─────────────────────────────────────────────────────────────
    refresh_interval_minutes: int = Field(
        default=60,
        description="Data refresh interval in minutes",
    )
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="json", description="Logging format (json or text)")
    debug: bool = Field(default=False, description="Enable debug mode")
    environment: str = Field(default="development", description="Environment name")

    # API Server
    api_host: str = Field(default="0.0.0.0", description="API server host")
    api_port: int = Field(default=8000, description="API server port")

    # Streamlit
    streamlit_port: int = Field(default=8501, description="Streamlit server port")

    # ─────────────────────────────────────────────────────────────
    # MVP Region Configuration (Texas)
    # ─────────────────────────────────────────────────────────────
    default_region: str = Field(default="US-TX", description="Default region code")
    default_grid_zone: str = Field(default="ERCOT", description="Default grid zone")

    # Texas bounding box
    texas_bbox_west: float = Field(default=-106.65, description="Texas west boundary")
    texas_bbox_east: float = Field(default=-93.51, description="Texas east boundary")
    texas_bbox_south: float = Field(default=25.84, description="Texas south boundary")
    texas_bbox_north: float = Field(default=36.50, description="Texas north boundary")

    @computed_field
    @property
    def texas_bbox(self) -> tuple[float, float, float, float]:
        """Return Texas bounding box as (west, south, east, north)."""
        return (
            self.texas_bbox_west,
            self.texas_bbox_south,
            self.texas_bbox_east,
            self.texas_bbox_north,
        )

    # ─────────────────────────────────────────────────────────────
    # Anomaly Detection Thresholds
    # ─────────────────────────────────────────────────────────────
    anomaly_threshold_sigma: float = Field(
        default=2.0,
        description="Z-score threshold for anomaly detection",
    )
    critical_threshold_sigma: float = Field(
        default=3.0,
        description="Z-score threshold for critical anomalies",
    )
    baseline_window_days: int = Field(
        default=30,
        description="Days of historical data for baseline calculation",
    )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Global settings instance
settings = get_settings()
