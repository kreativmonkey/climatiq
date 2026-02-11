"""Analyzer module for automatic pattern discovery in HVAC data.

This module implements self-discovery of optimal operating parameters
without hardcoded thresholds. It uses clustering and statistical analysis
to find stable vs unstable operating regions.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)


@dataclass
class OperatingRegion:
    """Represents a discovered operating region."""

    name: str
    power_range: tuple[float, float]  # (min, max)
    stability_score: float  # 0.0 (unstable) to 1.0 (stable)
    avg_cycle_rate: float  # cycles per hour
    sample_count: int
    conditions: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    """Results from the automatic analysis."""

    min_stable_power: float | None = None  # Auto-discovered threshold
    regions: list[OperatingRegion] = field(default_factory=list)
    data_quality_score: float = 0.0  # 0.0 to 1.0
    analysis_timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    sufficient_data: bool = False
    recommendation: str = ""


class Analyzer:
    """Analyzes historical data to discover optimal operating parameters.

    This class implements the self-discovery mechanism that finds:
    - Minimum stable power threshold (instead of hardcoded 400W)
    - Stable vs unstable operating regions
    - Correlations between conditions and cycling
    """

    # Minimum data requirements
    MIN_HOURS_FOR_ANALYSIS = 24  # Need at least 24h of data
    MIN_DATAPOINTS = 1000  # Minimum data points
    IDEAL_DAYS_FOR_TRAINING = 7  # Ideal: 1 week of data

    def __init__(self, config: dict[str, Any] = None):
        self.config = config or {}
        self._last_result: AnalysisResult | None = None
        self._scaler = StandardScaler()

    def check_data_sufficiency(self, df: pd.DataFrame) -> tuple[bool, str]:
        """Check if we have enough data for analysis.

        Returns:
            Tuple of (is_sufficient, message)
        """
        if df.empty:
            return False, "Keine Daten vorhanden. System bleibt im Beobachtungsmodus."

        if len(df) < self.MIN_DATAPOINTS:
            return (
                False,
                f"Nur {len(df)} Datenpunkte. Benötigt: {self.MIN_DATAPOINTS}. Weiter beobachten...",
            )

        # Check time span
        time_span = df.index[-1] - df.index[0]
        hours = time_span.total_seconds() / 3600

        if hours < self.MIN_HOURS_FOR_ANALYSIS:
            return (
                False,
                f"Nur {hours:.1f}h Daten. Benötigt: {self.MIN_HOURS_FOR_ANALYSIS}h. Weiter beobachten...",
            )

        return True, f"Ausreichend Daten: {len(df)} Punkte über {hours:.1f}h"

    def analyze(
        self,
        power_data: pd.Series,
        outdoor_temp: pd.Series | None = None,
        room_temps: dict[str, pd.Series] | None = None,
    ) -> AnalysisResult:
        """Perform comprehensive analysis to discover operating patterns.

        Args:
            power_data: Time series of power consumption (W)
            outdoor_temp: Optional outdoor temperature series
            room_temps: Optional dict of room temperature series

        Returns:
            AnalysisResult with discovered parameters
        """
        result = AnalysisResult()

        # Check data sufficiency
        df = pd.DataFrame({"power": power_data})
        sufficient, message = self.check_data_sufficiency(df)
        result.sufficient_data = sufficient
        result.recommendation = message

        if not sufficient:
            logger.info(f"Insufficient data: {message}")
            return result

        # Calculate data quality score
        result.data_quality_score = self._calculate_data_quality(df)

        # Detect cycling events
        df = self._add_cycling_detection(df)

        # Discover stable power threshold
        result.min_stable_power = self._discover_stable_threshold(df)

        # Discover operating regions via clustering
        result.regions = self._discover_regions(df, outdoor_temp)

        # Generate recommendation
        result.recommendation = self._generate_recommendation(result)

        self._last_result = result
        logger.info(f"Analysis complete. Min stable power: {result.min_stable_power}W")

        return result

    def _calculate_data_quality(self, df: pd.DataFrame) -> float:
        """Calculate a quality score for the data."""
        score = 1.0

        # Penalize for missing values
        missing_ratio = df["power"].isna().sum() / len(df)
        score -= missing_ratio * 0.5

        # Penalize for low variance (sensor might be stuck)
        if df["power"].std() < 10:
            score -= 0.3

        # Check for reasonable value range
        if df["power"].min() < 0 or df["power"].max() > 10000:
            score -= 0.2

        return max(0.0, min(1.0, score))

    def _add_cycling_detection(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add cycling detection columns to dataframe."""
        # Determine on/off state using dynamic thresholds
        power = df["power"].dropna()

        # Use percentiles to find natural thresholds
        p10 = power.quantile(0.10)
        p90 = power.quantile(0.90)

        # Dynamic threshold: midpoint between low and high states
        threshold_off = p10 + (p90 - p10) * 0.15
        threshold_on = p10 + (p90 - p10) * 0.25

        # State detection with hysteresis
        df["compressor_on"] = False
        state = False
        for i in range(len(df)):
            power_val = df["power"].iloc[i]
            if pd.isna(power_val):
                continue
            if state:  # Currently ON
                if power_val < threshold_off:
                    state = False
            else:  # Currently OFF
                if power_val > threshold_on:
                    state = True
            df.iloc[i, df.columns.get_loc("compressor_on")] = state

        # Detect state changes (cycles)
        df["state_change"] = df["compressor_on"].astype(int).diff().abs().fillna(0)

        return df

    def _discover_stable_threshold(self, df: pd.DataFrame) -> float:
        """Discover the minimum power level for stable operation.

        This replaces hardcoded thresholds like "400W" with a data-driven value.
        """
        # Group by power bins and calculate cycling rate per bin
        df["power_bin"] = pd.cut(df["power"], bins=20)

        stability_by_power = []
        for power_range, group in df.groupby("power_bin", observed=True):
            if len(group) < 30:  # Need minimum samples
                continue

            cycles = group["state_change"].sum()
            hours = len(group) / 60  # Assuming 1-min resolution
            cycle_rate = cycles / hours if hours > 0 else 0

            # Stability score: inverse of cycle rate
            stability = 1.0 / (1.0 + cycle_rate)

            # Get midpoint of power range
            if hasattr(power_range, "mid"):
                power_mid = power_range.mid
            else:
                continue

            stability_by_power.append(
                {
                    "power": power_mid,
                    "stability": stability,
                    "cycle_rate": cycle_rate,
                    "samples": len(group),
                }
            )

        if not stability_by_power:
            return 400.0  # Fallback default

        stability_df = pd.DataFrame(stability_by_power)

        # Find the lowest power level where stability is above threshold (0.8)
        stable_regions = stability_df[stability_df["stability"] > 0.8]

        if stable_regions.empty:
            # If no highly stable region, find the inflection point
            # where stability starts improving significantly
            stability_df = stability_df.sort_values("power")
            stability_df["stability_diff"] = stability_df["stability"].diff()

            # Find biggest improvement
            max_improvement_idx = stability_df["stability_diff"].idxmax()
            if pd.notna(max_improvement_idx):
                return float(stability_df.loc[max_improvement_idx, "power"])
            return float(stability_df["power"].median())

        # Return the minimum power level in stable regions
        return float(stable_regions["power"].min())

    def _discover_regions(
        self, df: pd.DataFrame, outdoor_temp: pd.Series | None = None
    ) -> list[OperatingRegion]:
        """Discover distinct operating regions using clustering."""
        regions = []

        # Prepare features for clustering
        features = ["power"]
        feature_df = df[["power"]].copy()

        if outdoor_temp is not None and len(outdoor_temp) > 0:
            # Align outdoor temp with power data
            feature_df["outdoor_temp"] = outdoor_temp.reindex(feature_df.index, method="nearest")
            features.append("outdoor_temp")

        # Add time-based features
        feature_df["hour"] = feature_df.index.hour
        features.append("hour")

        # Remove NaN rows
        feature_df = feature_df.dropna()

        if len(feature_df) < 100:
            return regions

        # Scale features
        X = self._scaler.fit_transform(feature_df[features])

        # Use KMeans to find natural clusters
        n_clusters = min(5, len(feature_df) // 200)  # Dynamic cluster count
        n_clusters = max(2, n_clusters)

        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        feature_df["cluster"] = kmeans.fit_predict(X)

        # Also add cycling info
        feature_df["is_cycling"] = df.loc[feature_df.index, "state_change"] > 0

        # Analyze each cluster
        for cluster_id in range(n_clusters):
            cluster_data = feature_df[feature_df["cluster"] == cluster_id]

            if len(cluster_data) < 30:
                continue

            power_min = cluster_data["power"].min()
            power_max = cluster_data["power"].max()

            # Calculate stability for this cluster
            cycling_ratio = cluster_data["is_cycling"].sum() / len(cluster_data)
            stability = 1.0 - cycling_ratio

            # Estimate cycle rate
            hours = len(cluster_data) / 60
            cycle_rate = cluster_data["is_cycling"].sum() / hours if hours > 0 else 0

            # Determine region name based on power level
            avg_power = cluster_data["power"].mean()
            if avg_power < 300:
                name = "Niedriglast (instabil)"
            elif avg_power < 600:
                name = "Teillast"
            elif avg_power < 1200:
                name = "Mittellast"
            else:
                name = "Volllast"

            if stability > 0.8:
                name += " - Stabil ✓"
            elif stability < 0.5:
                name += " - Instabil ⚠"

            region = OperatingRegion(
                name=name,
                power_range=(power_min, power_max),
                stability_score=stability,
                avg_cycle_rate=cycle_rate,
                sample_count=len(cluster_data),
                conditions={
                    "avg_power": avg_power,
                    "hour_distribution": cluster_data["hour"].value_counts().to_dict(),
                },
            )
            regions.append(region)

        # Sort by power range
        regions.sort(key=lambda r: r.power_range[0])

        return regions

    def _generate_recommendation(self, result: AnalysisResult) -> str:
        """Generate human-readable recommendation."""
        if not result.sufficient_data:
            return "Noch nicht genug Daten für Empfehlungen. Weiter beobachten."

        lines = []

        if result.min_stable_power:
            lines.append(
                f"✓ Erkannte Mindestlast für stabilen Betrieb: {result.min_stable_power:.0f}W"
            )

        stable_regions = [r for r in result.regions if r.stability_score > 0.8]
        unstable_regions = [r for r in result.regions if r.stability_score < 0.5]

        if unstable_regions:
            worst = min(unstable_regions, key=lambda r: r.stability_score)
            lines.append(
                f"⚠ Instabilster Bereich: {worst.power_range[0]:.0f}-{worst.power_range[1]:.0f}W"
            )

        if stable_regions:
            best = max(stable_regions, key=lambda r: r.stability_score)
            lines.append(
                f"✓ Stabilster Bereich: {best.power_range[0]:.0f}-{best.power_range[1]:.0f}W"
            )

        return "\n".join(lines) if lines else "Analyse abgeschlossen."

    def get_dashboard_data(self) -> dict[str, Any]:
        """Get data formatted for Home Assistant dashboard."""
        if not self._last_result:
            return {
                "status": "waiting",
                "message": "Warte auf erste Analyse...",
                "sufficient_data": False,
            }

        r = self._last_result
        return {
            "status": "ready" if r.sufficient_data else "observing",
            "sufficient_data": r.sufficient_data,
            "data_quality": round(r.data_quality_score * 100),
            "min_stable_power": r.min_stable_power,
            "regions": [
                {
                    "name": reg.name,
                    "power_min": reg.power_range[0],
                    "power_max": reg.power_range[1],
                    "stability_pct": round(reg.stability_score * 100),
                    "cycles_per_hour": round(reg.avg_cycle_rate, 2),
                }
                for reg in r.regions
            ],
            "recommendation": r.recommendation,
            "last_analysis": r.analysis_timestamp.isoformat(),
        }
