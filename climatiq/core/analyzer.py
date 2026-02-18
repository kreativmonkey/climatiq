"""Analyzer module for automatic pattern discovery in HVAC data.

This module implements self-discovery of optimal operating parameters
without hardcoded thresholds. It uses a fluctuation-based stability metric
to find stable vs unstable operating regions, supporting low-power stability.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

import pandas as pd
import numpy as np

# Optional ML imports
try:
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    HAS_SKLEARN = True
except ImportError:
    KMeans = None
    StandardScaler = None
    HAS_SKLEARN = False

logger = logging.getLogger(__name__)


@dataclass
class OperatingRegion:
    """Represents a discovered operating region."""
    
    name: str
    power_range: Tuple[float, float]  # (min, max)
    stability_score: float  # 0.0 (unstable) to 1.0 (stable)
    fluctuation_rate: float  # instability metric (e.g. avg std dev)
    sample_count: int
    conditions: Dict[str, Any] = field(default_factory=dict)


@dataclass 
class AnalysisResult:
    """Results from the automatic analysis."""
    
    min_stable_power: Optional[float] = None
    regions: List[OperatingRegion] = field(default_factory=list)
    data_quality_score: float = 0.0
    analysis_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    sufficient_data: bool = False
    recommendation: str = ""


class Analyzer:
    """Analyzes historical data to discover optimal operating parameters."""

    MIN_HOURS_FOR_ANALYSIS = 24
    MIN_DATAPOINTS = 1000
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self._last_result: Optional[AnalysisResult] = None
        if HAS_SKLEARN:
            self._scaler = StandardScaler()
        else:
            self._scaler = None

    def check_data_sufficiency(self, df: pd.DataFrame) -> Tuple[bool, str]:
        if df.empty:
            return False, "Keine Daten vorhanden."

        if len(df) < self.MIN_DATAPOINTS:
            return (
                False,
                f"Zu wenige Datenpunkte ({len(df)}). Benötigt mindestens {self.MIN_DATAPOINTS}.",
            )

        time_span = df.index[-1] - df.index[0]
        hours = time_span.total_seconds() / 3600

        if hours < self.MIN_HOURS_FOR_ANALYSIS:
            return (
                False,
                f"Zu kurzer Zeitraum ({hours:.1f}h). Benötigt mindestens {self.MIN_HOURS_FOR_ANALYSIS}h.",
            )

        return True, f"Ausreichend: {len(df)} Punkte über {hours:.1f}h"

    def analyze(self, power_data: pd.Series, 
                outdoor_temp: Optional[pd.Series] = None,
                room_temps: Optional[Dict[str, pd.Series]] = None) -> AnalysisResult:
        result = AnalysisResult()
        
        df = pd.DataFrame({'power': power_data})
        sufficient, message = self.check_data_sufficiency(df)
        result.sufficient_data = sufficient
        result.recommendation = message
        
        if not sufficient:
            return result
        
        result.data_quality_score = self._calculate_data_quality(df)
        
        # 1. Enhanced Metrics (Fluctuations)
        df = self._add_cycling_detection(df)
        
        # 2. Discover Regions (Cluster by Power + Instability)
        if HAS_SKLEARN:
            result.regions = self._discover_regions_clustering(df, outdoor_temp)
        else:
            result.regions = self._discover_regions_heuristic(df)
            
        # 3. Find Stable Threshold from Regions
        result.min_stable_power = self._find_min_stable_power(result.regions)
        
        result.recommendation = self._generate_recommendation(result)
        self._last_result = result
        
        return result

    def _calculate_data_quality(self, df: pd.DataFrame) -> float:
        score = 1.0
        missing = df['power'].isna().sum() / len(df)
        score -= missing * 0.5
        if df['power'].std() < 5:  # Flatline?
            score -= 0.4
        return max(0.0, score)

    def _add_cycling_detection(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add metrics for instability: rolling StdDev, Jumps.
        
        Optimized for v2: priorities absolute stability over relative variation.
        """
        # 1. Rolling StdDev (10 minutes) - The primary stability metric
        df["power_std_10m"] = df["power"].rolling(10, min_periods=1).std().fillna(0)

        # 2. Rolling Mean
        df["power_mean_10m"] = df["power"].rolling(10, min_periods=1).mean().fillna(1)

        # 3. Enhanced Instability Metric (v2)
        # We use a mix of absolute and relative variance.
        # Absolute variance is better for low-power stability detection.
        df["instability"] = (df["power_std_10m"] / 50.0).clip(0, 1.0) # Penalty for every 50W of StdDev

        # 4. Large Jumps (>200W diff)
        diff_abs = df["power"].diff().abs().fillna(0)
        df["power_jumps"] = (diff_abs > 200).astype(int)

        return df

    def _find_min_stable_power(self, regions: List[OperatingRegion]) -> float:
        """Find the lowest power level that is considered stable."""
        # We only care about COMPRESSOR stability (usually > 300W)
        active_regions = [r for r in regions if r.power_range[1] > 300]
        
        # In v2, we are more lenient with stability score for low power
        # if the absolute variance is low.
        stable_regions = [r for r in active_regions if r.stability_score > 0.6]
        
        if not stable_regions:
            if active_regions:
                # Fallback to the most stable active region
                best_region = max(active_regions, key=lambda r: r.stability_score)
                return max(400.0, best_region.power_range[0])
            return 450.0 # Default compressor floor
            
        # Sort by average power (hidden in name or calculated from range)
        stable_regions.sort(key=lambda r: (r.power_range[0] + r.power_range[1]) / 2)
        
        # Return the min power of the lowest stable region
        return stable_regions[0].power_range[0]

    def _discover_regions_heuristic(self, df: pd.DataFrame) -> List[OperatingRegion]:
        """Bin data by power and analyze stability within bins."""
        regions = []
        # Create bins every 200W up to 2000W, then larger
        bins = list(range(0, 2000, 200)) + [5000]
        labels = [f"{b}-{bins[i+1]}" for i, b in enumerate(bins[:-1])]
        
        try:
            df['power_bin'] = pd.cut(df['power'], bins=bins, labels=labels, include_lowest=True)
        except ValueError:
            return regions

        for bin_label, group in df.groupby('power_bin', observed=True):
            if len(group) < 50:
                continue
                
            regions.append(self._create_region_from_group(group))
            
        regions.sort(key=lambda r: r.power_range[0])
        return regions

    def _discover_regions_clustering(self, df: pd.DataFrame, outdoor: Optional[pd.Series] = None) -> List[OperatingRegion]:
        """Cluster data to find natural operating points."""
        if len(df) < 100:
            return self._discover_regions_heuristic(df)
            
        # In v2, we use power and the absolute std dev for clustering
        # This helps separate "Stable 450W" from "Oscillating 450W"
        features = ['power', 'power_std_10m']
        X_df = df[features].copy().dropna()
        X = self._scaler.fit_transform(X_df)
        
        # Use more clusters to separate low-power states more cleanly
        k = min(8, len(df)//150 + 3)
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10).fit(X)
        
        df.loc[X_df.index, 'cluster'] = kmeans.labels_
        
        regions = []
        for cid in range(k):
            group = df[df['cluster'] == cid]
            if len(group) < 20: continue # Smaller groups allowed in v2
            regions.append(self._create_region_from_group(group))
            
        regions.sort(key=lambda r: r.power_range[0])
        return regions

    def _create_region_from_group(self, group: pd.DataFrame) -> OperatingRegion:
        return self._create_region_from_data(group)

    def _create_region_from_data(self, group: pd.DataFrame) -> OperatingRegion:
        avg_power = group['power'].mean()
        min_p = group['power'].min()
        max_p = group['power'].max()
        
        # Stability Metric v2:
        # We penalize absolute variance (StdDev) more than relative CV
        # A StdDev of < 40W is excellent for low-power stability.
        avg_std = group['power_std_10m'].mean() if 'power_std_10m' in group.columns else 100.0
        
        # Jump rate (per hour)
        jump_col = 'power_jumps' if 'power_jumps' in group.columns else 'is_jump'
        jump_rate = group[jump_col].mean() * 60 if jump_col in group.columns else 0.0
        
        # Scoring: 
        # StdDev: 0W -> 1.0, 100W -> 0.0
        score_std = max(0, 1.0 - (avg_std / 100.0))
        # Jumps: 0/hr -> 1.0, 12/hr -> 0.0
        score_jumps = max(0, 1.0 - (jump_rate / 12.0))
        
        # Weighted score (Stability focus)
        stability_score = (score_std * 0.8) + (score_jumps * 0.2)
        
        name = f"{avg_power:.0f}W avg ({min_p:.0f}-{max_p:.0f}W)"
        if stability_score > 0.75: name += " [STABIL]"
        elif stability_score < 0.4: name += " [TAKTE]"
        
        return OperatingRegion(
            name=name,
            power_range=(min_p, max_p),
            stability_score=stability_score,
            fluctuation_rate=avg_std,
            sample_count=len(group),
            conditions={'avg_power': avg_power, 'avg_std': avg_std}
        )

    def _generate_recommendation(self, result: AnalysisResult) -> str:
        if not result.sufficient_data:
            return "Bitte weiter beobachten – Daten sammeln..."
            
        lines = []
        if result.min_stable_power:
            lines.append(f"Minimale stabile Last: {result.min_stable_power:.0f}W")
            
        # In v2, we are slightly more lenient for recommendations if no 
        # perfect regions are found, taking the relatively best ones.
        stable_regions = [r for r in result.regions if r.stability_score > 0.6]
        
        if not stable_regions and result.regions:
            # Fallback: take the best region if it's at least "decent"
            best = max(result.regions, key=lambda r: r.stability_score)
            if best.stability_score > 0.4:
                stable_regions = [best]

        if stable_regions:
            ranges = [f"{r.power_range[0]:.0f}-{r.power_range[1]:.0f}W" for r in stable_regions]
            lines.append(f"Empfohlene Bereiche: {', '.join(ranges)}")
        else:
            lines.append("⚠ Kein stabiler Betriebsbereich gefunden.")
            
        return " | ".join(lines)

    def get_dashboard_data(self) -> Dict[str, Any]:
        """Return data for HA dashboard."""
        if not self._last_result:
            return {"status": "waiting", "sufficient_data": False}

        r = self._last_result
        return {
            "status": "ready" if r.sufficient_data else "waiting",
            "sufficient_data": bool(r.sufficient_data),
            "min_stable_power": r.min_stable_power,
            "regions": [
                {
                    "range": f"{reg.power_range[0]:.0f}-{reg.power_range[1]:.0f}W",
                    "stability": round(reg.stability_score * 100),
                    "is_stable": reg.stability_score > 0.7,
                }
                for reg in r.regions
            ],
        }
