"""Controller module for HVAC optimization actions v2.

Optimized for stability and power variance reduction. Targets minimum
stable energy consumption points discovered by the Analyzer.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from climatiq.core.entities import OptimizerStatus, SystemMode

logger = logging.getLogger(__name__)


class ActionType(str, Enum):
    """Types of control actions."""

    ENABLE_UNIT = "enable_unit"
    DISABLE_UNIT = "disable_unit"
    ADJUST_TEMP = "adjust_temp"
    ADJUST_FAN = "adjust_fan"
    NO_ACTION = "no_action"


@dataclass
class ControlAction:
    """Represents a control action to be executed."""

    action_type: ActionType
    target_unit: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ActionResult:
    """Result of executing an action."""

    success: bool
    action: ControlAction
    message: str = ""
    prevented_cycling: bool = False


class Controller:
    """Decides and coordinates HVAC control actions (v2).

    Strategies:
    1. Stability Targeting: Target learned minimum stable power zones (400-600W).
    2. Gradual Modulation: Use small temp steps (0.2°C) to nudge the system.
    3. Night Mode: Preemptive buffering during quiet hours.
    4. Variance Dampening: React to power_std and spread to stop fluctuations.
    """

    # Safety limits
    MAX_TEMP_DEVIATION = 1.5
    MIN_ACTION_INTERVAL = timedelta(minutes=10)

    # v2 Stability Thresholds
    STABLE_STD_THRESHOLD = 50.0  # Watts
    HIGH_SPREAD_THRESHOLD = 300.0  # Watts

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._last_action_time: datetime | None = None
        self._action_history: list[ControlAction] = []
        self._action_callback: Callable | None = None

        # Statistics
        self.stats = {
            "actions_taken": 0,
            "cycles_prevented": 0,
            "stability_actions": 0,
            "night_mode_actions": 0,
            "gradual_nudges": 0,
        }

    def set_action_callback(self, callback: Callable[[ControlAction], bool]):
        self._action_callback = callback

    def should_act(self, status: OptimizerStatus) -> bool:
        if status.mode in (SystemMode.OBSERVATION, SystemMode.MANUAL):
            return False

        if self._last_action_time:
            elapsed = datetime.now(UTC) - self._last_action_time
            if elapsed < self.MIN_ACTION_INTERVAL:
                return False

        return True

    def is_night_mode(self) -> bool:
        """Check if we are in night hours (23:00 - 06:00)."""
        now = datetime.now(UTC).astimezone()  # Use local time if possible
        return now.hour >= 23 or now.hour < 6

    def decide_action(
        self, status: OptimizerStatus, prediction: dict[str, Any], analysis: dict[str, Any]
    ) -> ControlAction:
        """v2 Decision Logic: Stabilize and Minimize."""

        # 1. Evaluate Stability Metrics
        cycling_risk = status.cycling_risk  # Our v2 score (0-1.0)
        power_std = analysis.get("power_std", 0.0)
        power_spread = analysis.get("power_spread", 0.0)
        current_power = status.power_consumption
        min_stable_power = analysis.get("min_stable_power", 450.0)

        is_unstable = (
            cycling_risk > 0.6
            or power_std > self.STABLE_STD_THRESHOLD
            or power_spread > self.HIGH_SPREAD_THRESHOLD
        )

        # No action if stable and within efficient range
        if not is_unstable and current_power >= min_stable_power:
            return ControlAction(ActionType.NO_ACTION, reason="System stabil und effizient.")

        # 2. Night Mode Strategy (Preemptive)
        if self.is_night_mode() and is_unstable:
            action = self._strategy_night_mode(status, min_stable_power)
            if action.action_type != ActionType.NO_ACTION:
                self.stats["night_mode_actions"] += 1
                return action

        # 3. Stability Targeting (Load Balancing)
        # If power is too low to be stable or variance is high
        if current_power < min_stable_power or is_unstable:
            action = self._strategy_stability_targeting(status, min_stable_power, power_std)
            if action.action_type != ActionType.NO_ACTION:
                self.stats["stability_actions"] += 1
                return action

        # 4. Gradual Nudge (Temperature)
        # If we just need a tiny bit more load to reach stability
        if is_unstable:
            action = self._strategy_gradual_nudge(status)
            if action.action_type != ActionType.NO_ACTION:
                self.stats["gradual_nudges"] += 1
                return action

        return ControlAction(ActionType.NO_ACTION, reason="Keine passende Intervention gefunden.")

    # --- Strategies ---

    def _strategy_night_mode(self, status: OptimizerStatus, min_stable: float) -> ControlAction:
        """Night Mode: Use low-priority units as thermal buffers with lower temps."""
        inactive_units = [(n, u) for n, u in status.units.items() if not u.is_on]
        if not inactive_units:
            return ControlAction(ActionType.NO_ACTION)

        # Prefer low priority units
        priorities = self.config.get("unit_priorities", {})
        inactive_units.sort(key=lambda x: priorities.get(x[0], 50))
        target_name, _ = inactive_units[0]

        # Night temp is lower to avoid waking people but provide load
        night_temp = self.config.get("comfort", {}).get("night_temp", 19.0)

        return ControlAction(
            ActionType.ENABLE_UNIT,
            target_unit=target_name,
            parameters={"temperature": night_temp, "fan_mode": "low"},
            reason=f"Night Mode: {target_name} als Puffer aktiviert ({night_temp}°C) für Stabilität.",
        )

    def _strategy_stability_targeting(
        self, status: OptimizerStatus, target: float, std: float
    ) -> ControlAction:
        """Target the learned minimum stable power zone."""
        inactive_units = [(n, u) for n, u in status.units.items() if not u.is_on]

        if inactive_units:
            # Activate additional unit to reach stable floor
            priorities = self.config.get("unit_priorities", {})
            inactive_units.sort(key=lambda x: priorities.get(x[0], 50))
            target_name, _ = inactive_units[0]

            base_temp = self.config.get("comfort", {}).get("target_temp", 21.0)

            return ControlAction(
                ActionType.ENABLE_UNIT,
                target_unit=target_name,
                parameters={"temperature": base_temp - 0.5, "fan_mode": "auto"},
                reason=f"Stabilitäts-Targeting: {target_name} aktiviert (Ziel >{target:.0f}W, σ={std:.0f}W).",
            )

        return ControlAction(ActionType.NO_ACTION)

    def _strategy_gradual_nudge(self, status: OptimizerStatus) -> ControlAction:
        """Smallest possible intervention: adjust setpoint by 0.2-0.3°C."""
        active_units = [
            (n, u) for n, u in status.units.items() if u.is_on and u.target_temp is not None
        ]
        if not active_units:
            return ControlAction(ActionType.NO_ACTION)

        # Pick unit with highest priority (most important room) or most room for change
        target_name, target_unit = active_units[0]

        current_temp = target_unit.target_temp
        new_temp = current_temp + 0.3  # Small nudge up to increase load slightly

        max_temp = self.config.get("comfort", {}).get("target_temp", 21.0) + self.MAX_TEMP_DEVIATION
        if new_temp > max_temp:
            new_temp = current_temp - 0.3  # Try nudging down if up is blocked
            if new_temp < (
                self.config.get("comfort", {}).get("target_temp", 21.0) - self.MAX_TEMP_DEVIATION
            ):
                return ControlAction(ActionType.NO_ACTION)

        return ControlAction(
            ActionType.ADJUST_TEMP,
            target_unit=target_name,
            parameters={"temperature": new_temp, "previous": current_temp},
            reason=f"Gradual Nudge: {target_name} um 0.3°C angepasst zur Stabilisierung.",
        )

    # --- Execution ---

    def execute_action(self, action: ControlAction) -> ActionResult:
        if action.action_type == ActionType.NO_ACTION:
            return ActionResult(True, action, "Keine Aktion nötig.")

        if not self._action_callback:
            return ActionResult(False, action, "Kein Action-Callback gesetzt.")

        try:
            success = self._action_callback(action)
            if success:
                self._last_action_time = datetime.now(UTC)
                self._action_history.append(action)
                self.stats["actions_taken"] += 1
                logger.info(f"Executed: {action.reason}")

            return ActionResult(
                success, action, "Erfolgreich" if success else "Fehler bei Ausführung"
            )
        except Exception as e:
            logger.error(f"Action execution error: {e}")
            return ActionResult(False, action, str(e))

    def get_dashboard_data(self) -> dict[str, Any]:
        return {
            "stats": self.stats,
            "last_action": self._action_history[-1].reason if self._action_history else None,
            "last_action_time": (
                self._last_action_time.isoformat() if self._last_action_time else None
            ),
            "history": [
                {
                    "type": a.action_type.value,
                    "target": a.target_unit,
                    "reason": a.reason,
                    "time": a.timestamp.isoformat(),
                }
                for a in self._action_history[-5:]
            ],
        }
