"""
Anomaly Detection Engine

Detects statistical anomalies in time-series observations using:
- Z-score detection (deviation from rolling mean)
- Simple threshold-based flagging

Future enhancements:
- Seasonal decomposition (STL)
- Change point detection (PELT)
- Spatial clustering (DBSCAN)
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import numpy as np
import structlog
from sqlalchemy import func, select, text

from src.config.settings import settings
from src.db.connection import get_db_context
from src.db.models import Anomaly, Indicator, Observation, Station

logger = structlog.get_logger(__name__)


class AnomalyDetector:
    """
    Statistical anomaly detector for time-series data.
    
    Uses z-score based detection with configurable thresholds.
    """

    def __init__(
        self,
        threshold_sigma: float = 2.0,
        critical_sigma: float = 3.0,
        baseline_days: int = 30,
    ):
        """
        Initialize detector with thresholds.
        
        Args:
            threshold_sigma: Z-score threshold for anomaly flagging (default: 2.0)
            critical_sigma: Z-score threshold for critical anomalies (default: 3.0)
            baseline_days: Days of history to use for baseline (default: 30)
        """
        self.threshold_sigma = threshold_sigma
        self.critical_sigma = critical_sigma
        self.baseline_days = baseline_days
        self.log = logger.bind(component="anomaly_detector")

    def calculate_baseline(
        self,
        indicator_id: int,
        station_id: Optional[int] = None,
        region_id: Optional[int] = None,
        end_time: Optional[datetime] = None,
    ) -> tuple[float, float]:
        """
        Calculate baseline statistics (mean, std) from historical data.
        
        Args:
            indicator_id: Indicator to calculate baseline for
            station_id: Optional station filter
            region_id: Optional region filter
            end_time: End of baseline window (default: now)
            
        Returns:
            Tuple of (mean, standard_deviation)
        """
        if end_time is None:
            end_time = datetime.now(timezone.utc)

        start_time = end_time - timedelta(days=self.baseline_days)

        with get_db_context() as db:
            query = (
                db.query(
                    func.avg(Observation.value).label("mean"),
                    func.stddev(Observation.value).label("std"),
                )
                .filter(Observation.indicator_id == indicator_id)
                .filter(Observation.observed_at >= start_time)
                .filter(Observation.observed_at < end_time)
                .filter(Observation.quality_flag == "valid")
            )

            if station_id:
                query = query.filter(Observation.station_id == station_id)
            if region_id:
                query = query.filter(Observation.region_id == region_id)

            result = query.first()

            mean = float(result.mean) if result.mean else 0.0
            std = float(result.std) if result.std else 0.0

            return mean, std

    def calculate_z_score(
        self, value: float, mean: float, std: float
    ) -> float:
        """
        Calculate z-score for a value.
        
        Args:
            value: Observed value
            mean: Baseline mean
            std: Baseline standard deviation
            
        Returns:
            Z-score (number of standard deviations from mean)
        """
        if std == 0 or np.isnan(std):
            return 0.0
        return (value - mean) / std

    def classify_anomaly(self, z_score: float) -> Optional[str]:
        """
        Classify anomaly type based on z-score.
        
        Args:
            z_score: Calculated z-score
            
        Returns:
            Anomaly type string or None if not anomalous
        """
        abs_z = abs(z_score)

        if abs_z >= self.critical_sigma:
            return "critical_deviation"
        elif abs_z >= self.threshold_sigma:
            return "significant_deviation"
        return None

    def get_severity(self, z_score: float) -> float:
        """
        Convert z-score to severity score (0-1 scale).
        
        Args:
            z_score: Calculated z-score
            
        Returns:
            Severity score between 0 and 1
        """
        # Map z-score to 0-1 scale
        # 2σ = 0.5, 3σ = 0.75, 4σ+ = 1.0
        abs_z = abs(z_score)
        if abs_z < self.threshold_sigma:
            return 0.0
        elif abs_z >= 4.0:
            return 1.0
        else:
            return min(1.0, (abs_z - self.threshold_sigma) / 2.0 + 0.5)

    def detect_for_indicator(
        self,
        indicator_id: int,
        lookback_hours: int = 6,
    ) -> list[dict[str, Any]]:
        """
        Detect anomalies for a specific indicator.
        
        Args:
            indicator_id: Indicator to analyze
            lookback_hours: Hours of recent data to analyze
            
        Returns:
            List of detected anomalies
        """
        anomalies = []
        now = datetime.now(timezone.utc)
        lookback_start = now - timedelta(hours=lookback_hours)

        with get_db_context() as db:
            # Get recent observations
            observations = (
                db.query(Observation)
                .filter(Observation.indicator_id == indicator_id)
                .filter(Observation.observed_at >= lookback_start)
                .filter(Observation.quality_flag == "valid")
                .order_by(Observation.observed_at.desc())
                .all()
            )

            if not observations:
                return anomalies

            # Group by station/region
            groups: dict[tuple, list[Observation]] = {}
            for obs in observations:
                key = (obs.station_id, obs.region_id)
                if key not in groups:
                    groups[key] = []
                groups[key].append(obs)

            # Analyze each group
            for (station_id, region_id), obs_list in groups.items():
                # Calculate baseline excluding recent observations
                mean, std = self.calculate_baseline(
                    indicator_id=indicator_id,
                    station_id=station_id,
                    region_id=region_id,
                    end_time=lookback_start,
                )

                if std == 0:
                    continue

                # Check each observation
                for obs in obs_list:
                    z_score = self.calculate_z_score(obs.value, mean, std)
                    anomaly_type = self.classify_anomaly(z_score)

                    if anomaly_type:
                        anomalies.append(
                            {
                                "indicator_id": indicator_id,
                                "station_id": station_id,
                                "region_id": region_id,
                                "location": obs.location,
                                "detected_at": obs.observed_at,
                                "anomaly_type": anomaly_type,
                                "severity": self.get_severity(z_score),
                                "baseline_value": mean,
                                "observed_value": obs.value,
                                "z_score": z_score,
                            }
                        )

        return anomalies

    def save_anomalies(self, anomalies: list[dict[str, Any]]) -> int:
        """
        Save detected anomalies to database.
        
        Args:
            anomalies: List of anomaly dicts
            
        Returns:
            Number of anomalies saved
        """
        if not anomalies:
            return 0

        saved = 0

        with get_db_context() as db:
            for anomaly_data in anomalies:
                # Check if already exists
                existing = (
                    db.query(Anomaly)
                    .filter_by(
                        indicator_id=anomaly_data["indicator_id"],
                        station_id=anomaly_data.get("station_id"),
                        region_id=anomaly_data.get("region_id"),
                        detected_at=anomaly_data["detected_at"],
                    )
                    .first()
                )

                if not existing:
                    anomaly = Anomaly(
                        indicator_id=anomaly_data["indicator_id"],
                        station_id=anomaly_data.get("station_id"),
                        region_id=anomaly_data.get("region_id"),
                        location=anomaly_data.get("location"),
                        detected_at=anomaly_data["detected_at"],
                        anomaly_type=anomaly_data["anomaly_type"],
                        severity=anomaly_data["severity"],
                        baseline_value=anomaly_data["baseline_value"],
                        observed_value=anomaly_data["observed_value"],
                        z_score=anomaly_data["z_score"],
                    )
                    db.add(anomaly)
                    saved += 1

            db.commit()

        return saved


def run_anomaly_detection(lookback_hours: int = 6) -> dict[str, Any]:
    """
    Run anomaly detection across all indicators.
    
    Args:
        lookback_hours: Hours of recent data to analyze
        
    Returns:
        Summary dict with detection results
    """
    detector = AnomalyDetector(
        threshold_sigma=settings.anomaly_threshold_sigma,
        critical_sigma=settings.critical_threshold_sigma,
        baseline_days=settings.baseline_window_days,
    )

    total_anomalies = 0
    results_by_indicator: dict[str, int] = {}

    with get_db_context() as db:
        # Get all active indicators
        indicators = db.query(Indicator).all()

        for indicator in indicators:
            anomalies = detector.detect_for_indicator(
                indicator_id=indicator.indicator_id,
                lookback_hours=lookback_hours,
            )

            if anomalies:
                saved = detector.save_anomalies(anomalies)
                results_by_indicator[indicator.code] = saved
                total_anomalies += saved

    logger.info(
        "anomaly_detection_completed",
        total_anomalies=total_anomalies,
        by_indicator=results_by_indicator,
    )

    return {
        "status": "completed",
        "total_anomalies": total_anomalies,
        "by_indicator": results_by_indicator,
    }


def get_recent_anomalies(
    hours: int = 24,
    indicator_code: Optional[str] = None,
    min_severity: float = 0.0,
) -> list[dict[str, Any]]:
    """
    Get recent anomalies for display.
    
    Args:
        hours: Hours of history to retrieve
        indicator_code: Optional filter by indicator
        min_severity: Minimum severity threshold
        
    Returns:
        List of anomaly records with related data
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    with get_db_context() as db:
        query = (
            db.query(Anomaly, Indicator, Station)
            .join(Indicator, Anomaly.indicator_id == Indicator.indicator_id)
            .outerjoin(Station, Anomaly.station_id == Station.station_id)
            .filter(Anomaly.detected_at >= cutoff)
            .filter(Anomaly.severity >= min_severity)
            .order_by(Anomaly.detected_at.desc())
        )

        if indicator_code:
            query = query.filter(Indicator.code == indicator_code)

        results = query.limit(100).all()

        anomalies = []
        for anomaly, indicator, station in results:
            anomalies.append(
                {
                    "anomaly_id": anomaly.anomaly_id,
                    "indicator_code": indicator.code,
                    "indicator_name": indicator.name,
                    "station_name": station.name if station else None,
                    "station_id": station.external_id if station else None,
                    "detected_at": anomaly.detected_at.isoformat(),
                    "anomaly_type": anomaly.anomaly_type,
                    "severity": anomaly.severity,
                    "z_score": anomaly.z_score,
                    "baseline_value": anomaly.baseline_value,
                    "observed_value": anomaly.observed_value,
                    "is_acknowledged": anomaly.is_acknowledged,
                }
            )

        return anomalies
