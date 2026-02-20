"""Observer module for gathering and tracking HVAC state.

Monitors real-time power consumption and detects instability patterns
including frequent large power fluctuations (Takten), not just on/off cycling.
"""

import logging
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from climatiq.analysis.cycling_detector import CyclingDetector
from climatiq.core.entities import OptimizerStatus, UnitStatus

logger = logging.getLogger(__name__)


class Observer:
    """Monitors the current state of the HVAC system and detects patterns.

    Uses a combination of traditional on/off cycle detection and fluctuation
    analysis to compute an instability score.  The ``cycling_risk`` is derived
    from that score instead of hard-coded power bands.
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.status = OptimizerStatus()

        cycling_cfg = config.get("cycling", {})
        self.detector = CyclingDetector(
            power_on_threshold=cycling_cfg.get("power_on_threshold", 300),
            power_off_threshold=cycling_cfg.get("power_off_threshold", 150),
            fluctuation_threshold_watts=cycling_cfg.get("fluctuation_threshold_watts", 200),
            fluctuation_threshold_pct=cycling_cfg.get("fluctuation_threshold_pct", 0.4),
            window_minutes=cycling_cfg.get("window_minutes", 10),
        )

        self._power_history: list[tuple[datetime, float]] = []
        self._max_history = 120  # Keep 2 hours of 1-min data

        # Cached analysis results
        self._instability_score: float = 0.0
        self._recent_jumps: list[tuple[pd.Timestamp, float]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_power(self, value: float, timestamp: datetime | None = None):
        """Update current power consumption and track history."""
        ts = timestamp or datetime.now(UTC)
        self.status.power_consumption = value
        self.status.last_update = ts

        self._power_history.append((ts, value))
        # Keep history within limits
        if len(self._power_history) > self._max_history:
            self._power_history.pop(0)

        self._analyze_cycling()

    def update_unit(self, name: str, data: dict[str, Any]):
        """Update status of an indoor unit."""
        if name not in self.status.units:
            self.status.units[name] = UnitStatus(name=name, entity_id=data.get("entity_id", ""))

        unit = self.status.units[name]
        unit.is_on = data.get("is_on", unit.is_on)
        unit.current_temp = data.get("current_temp", unit.current_temp)
        unit.target_temp = data.get("target_temp", unit.target_temp)
        unit.fan_mode = data.get("fan_mode", unit.fan_mode)
        unit.hvac_mode = data.get("hvac_mode", unit.hvac_mode)

    def get_summary(self) -> dict[str, Any]:
        """Get summary for Dashboard / HA UI.

        Includes the new ``instability_score`` and ``recent_jumps`` fields.
        """
        return {
            "mode": self.status.mode.value,
            "power": self.status.power_consumption,
            "is_cycling": self.status.is_cycling,
            "cycling_risk": self.status.cycling_risk,
            "instability_score": round(self._instability_score, 3),
            "recent_jumps": [
                {"time": t.isoformat(), "delta": round(d, 1)} for t, d in self._recent_jumps
            ],
            "base_load": self.status.base_load_detected,
            "active_units": sum(1 for u in self.status.units.values() if u.is_on),
            "avoided_cycles": self.status.avoided_cycles_count,
            "last_update": self.status.last_update.isoformat(),
        }

    # ------------------------------------------------------------------
    # Internal analysis
    # ------------------------------------------------------------------

    def _analyze_cycling(self):
        """Detect cycling using on/off cycles, fluctuations **and** power jumps.

        Optimized for performance: uses pre-calculated window metrics.
        """
        if len(self._power_history) < 5:
            return

        # Optimization: use pre-converted numpy array for metrics if possible
        # or limit pandas conversion to the actual window we need
        recent_values = [v for _, v in self._power_history[-20:]]

        # Fast metrics calculation using numpy
        vals = np.array(recent_values)
        std_p = np.std(vals)
        spread = np.max(vals) - np.min(vals)

        # Fast jump detection
        diffs = np.abs(np.diff(vals))
        jumps = np.sum(diffs > 200)

        # Compute Risk Score v2 (Variance-based)
        # 1. StdDev contribution: 50W std -> 40% risk
        risk_std = std_p / 125.0
        # 2. Spread contribution: 400W spread -> 40% risk
        risk_spread = spread / 1000.0
        # 3. Jump contribution: 2 jumps -> 20% risk
        risk_jumps = jumps / 10.0

        total_risk = (risk_std * 0.4) + (risk_spread * 0.4) + (risk_jumps * 0.2)

        self._instability_score = float(np.clip(total_risk, 0.0, 1.0))
        self.status.is_cycling = self._instability_score > 0.6
        self.status.cycling_risk = round(self._instability_score, 2)

        # Update jumps list for dashboard (maintain backward compatibility)
        ts_last = self._power_history[-1][0]
        if diffs.size > 0 and diffs[-1] > 200:
            self._recent_jumps.append((ts_last, diffs[-1]))
            if len(self._recent_jumps) > 10:
                self._recent_jumps.pop(0)

    @staticmethod
    def _compute_instability_score(
        series: pd.Series,
        recent_jumps: list[tuple[pd.Timestamp, float]],
    ) -> float:
        """Compute a 0.0–1.0 instability score.

        Components (each normalised to 0–1, then averaged):
        1. **rolling_std_ratio** – rolling standard deviation (window=10) relative
           to the mean power.  High std relative to mean → unstable.
        2. **jump_frequency** – number of large power jumps in the last 10 min,
           normalised so that ≥6 jumps → 1.0.
        3. **amplitude_ratio** – (max - min) of recent power relative to mean.
           Captures the overall swing range.
        """
        if len(series) < 3:
            return 0.0

        mean_power = series.mean()
        if mean_power < 1.0:
            # Essentially off – no meaningful instability
            return 0.0

        # 1. Rolling std component
        window = min(10, len(series))
        rolling_std = series.rolling(window=window, min_periods=1).std()
        avg_rolling_std = float(rolling_std.mean())
        rolling_std_ratio = min(1.0, avg_rolling_std / mean_power)

        # 2. Jump frequency component (≥6 jumps in 10 min → score 1.0)
        jump_freq = min(1.0, len(recent_jumps) / 6.0)

        # 3. Amplitude ratio component
        amplitude = float(series.max() - series.min())
        amplitude_ratio = min(1.0, amplitude / mean_power)

        # Weighted average
        score = 0.4 * rolling_std_ratio + 0.35 * jump_freq + 0.25 * amplitude_ratio
        return float(min(1.0, max(0.0, score)))
