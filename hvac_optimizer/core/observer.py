"""Observer module for gathering and tracking HVAC state."""

import logging
from datetime import UTC, datetime
from typing import Any

from hvac_optimizer.analysis.cycling_detector import CyclingDetector
from hvac_optimizer.core.entities import OptimizerStatus, UnitStatus

logger = logging.getLogger(__name__)


class Observer:
    """Monitors the current state of the HVAC system and detects patterns."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.status = OptimizerStatus()
        self.detector = CyclingDetector(
            power_on_threshold=config.get("cycling", {}).get("power_on_threshold", 300),
            power_off_threshold=config.get("cycling", {}).get("power_off_threshold", 150),
        )
        self._power_history: list[tuple[datetime, float]] = []
        self._max_history = 120  # Keep 2 hours of 1-min data

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
            # Initialize if new
            self.status.units[name] = UnitStatus(name=name, entity_id=data.get("entity_id", ""))

        unit = self.status.units[name]
        unit.is_on = data.get("is_on", unit.is_on)
        unit.current_temp = data.get("current_temp", unit.current_temp)
        unit.target_temp = data.get("target_temp", unit.target_temp)
        unit.fan_mode = data.get("fan_mode", unit.fan_mode)
        unit.hvac_mode = data.get("hvac_mode", unit.hvac_mode)

    def _analyze_cycling(self):
        """Internal check for current cycling status."""
        if len(self._power_history) < 10:
            return

        import pandas as pd

        series = pd.Series(
            [v for _, v in self._power_history], index=[t for t, _ in self._power_history]
        )

        analysis = self.detector.analyze_cycling(series)
        self.status.is_cycling = analysis["short_cycle_count"] > 0

        # Simple risk heuristic for now: if power is near threshold and falling
        if 150 < self.status.power_consumption < 450:
            self.status.cycling_risk = 0.7
        else:
            self.status.cycling_risk = 0.1

    def get_summary(self) -> dict[str, Any]:
        """Get summary for Dashboard/HA UI."""
        return {
            "mode": self.status.mode.value,
            "power": self.status.power_consumption,
            "is_cycling": self.status.is_cycling,
            "cycling_risk": self.status.cycling_risk,
            "base_load": self.status.base_load_detected,
            "active_units": sum(1 for u in self.status.units.values() if u.is_on),
            "avoided_cycles": self.status.avoided_cycles_count,
            "last_update": self.status.last_update.isoformat(),
        }
