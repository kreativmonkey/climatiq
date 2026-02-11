"""Controller module for HVAC optimization actions.

Decides and executes actions to prevent cycling based on predictions
and current system state.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from hvac_optimizer.core.entities import OptimizerStatus, SystemMode

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
    """Decides and coordinates HVAC control actions.

    Strategies:
    1. Load Balancing: Distribute load across multiple units
    2. Temperature Modulation: Adjust setpoints to keep compressor stable
    3. Fan Control: Use fan speed to modulate heat transfer rate
    4. Buffer Heating: Use low-priority rooms as thermal buffers
    """

    # Safety limits
    MAX_TEMP_DEVIATION = 1.5  # Maximum deviation from user setpoint
    MIN_ACTION_INTERVAL = timedelta(minutes=5)  # Don't act too frequently

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._last_action_time: datetime | None = None
        self._action_history: list[ControlAction] = []
        self._action_callback: Callable | None = None

        # Statistics
        self.stats = {
            "actions_taken": 0,
            "cycles_prevented": 0,
            "load_balancing_count": 0,
            "temp_adjustments": 0,
        }

    def set_action_callback(self, callback: Callable[[ControlAction], bool]):
        """Set callback function to execute actions (e.g., HA service calls)."""
        self._action_callback = callback

    def should_act(self, status: OptimizerStatus) -> bool:
        """Determine if we should take action now."""
        # Don't act in observation or manual mode
        if status.mode in (SystemMode.OBSERVATION, SystemMode.MANUAL):
            return False

        # Respect minimum interval
        if self._last_action_time:
            elapsed = datetime.now(UTC) - self._last_action_time
            if elapsed < self.MIN_ACTION_INTERVAL:
                return False

        return True

    def decide_action(
        self, status: OptimizerStatus, prediction: dict[str, Any], analysis: dict[str, Any]
    ) -> ControlAction:
        """Decide what action to take based on current state and predictions.

        Args:
            status: Current system status from Observer
            prediction: Cycling prediction from Predictor
            analysis: Analysis results from Analyzer

        Returns:
            ControlAction to execute
        """
        # No action if cycling not predicted or risk is low
        cycling_predicted = prediction.get("cycling_predicted", False)
        cycling_prob = prediction.get("probability", 0)
        cycling_risk = status.cycling_risk

        if not cycling_predicted and cycling_risk < 0.5:
            return ControlAction(
                action_type=ActionType.NO_ACTION, reason="Kein Handlungsbedarf - System stabil"
            )

        # Get minimum stable power from analysis
        min_stable_power = analysis.get("min_stable_power", 400)
        current_power = status.power_consumption

        # Strategy 1: Load Balancing
        # If power is below stable threshold, try to add load
        if current_power < min_stable_power:
            action = self._strategy_load_balancing(status, min_stable_power)
            if action.action_type != ActionType.NO_ACTION:
                return action

        # Strategy 2: Temperature Modulation
        # Slightly lower setpoint to extend compressor runtime
        if cycling_prob > 0.7:
            action = self._strategy_temp_modulation(status)
            if action.action_type != ActionType.NO_ACTION:
                return action

        # Strategy 3: Fan Speed Reduction
        # Lower fan = slower heat transfer = longer runtime
        if cycling_prob > 0.6:
            action = self._strategy_fan_control(status)
            if action.action_type != ActionType.NO_ACTION:
                return action

        return ControlAction(
            action_type=ActionType.NO_ACTION, reason="Keine passende Strategie gefunden"
        )

    def _strategy_load_balancing(
        self, status: OptimizerStatus, target_power: float
    ) -> ControlAction:
        """Try to add load by enabling additional units."""
        # Find inactive units that could be enabled
        inactive_units = [(name, unit) for name, unit in status.units.items() if not unit.is_on]

        if not inactive_units:
            return ControlAction(
                action_type=ActionType.NO_ACTION, reason="Keine inaktiven Geräte verfügbar"
            )

        # Sort by priority (from config) - prefer low-priority rooms as buffers
        priorities = self.config.get("unit_priorities", {})
        inactive_units.sort(key=lambda x: priorities.get(x[0], 50))

        # Enable the lowest priority inactive unit
        target_name, target_unit = inactive_units[0]

        # Calculate a modest setpoint (slightly below comfort)
        base_temp = self.config.get("comfort", {}).get("target_temp", 21.0)
        buffer_temp = base_temp - 1.0  # 1 degree below comfort

        return ControlAction(
            action_type=ActionType.ENABLE_UNIT,
            target_unit=target_name,
            parameters={"temperature": buffer_temp, "fan_mode": "low"},
            reason=f"Lastverteilung: {target_name} als Puffer aktivieren ({target_power:.0f}W Ziel)",
        )

    def _strategy_temp_modulation(self, status: OptimizerStatus) -> ControlAction:
        """Adjust temperature setpoints to extend compressor runtime."""
        # Find active units where we can lower the setpoint
        active_units = [
            (name, unit)
            for name, unit in status.units.items()
            if unit.is_on and unit.target_temp is not None
        ]

        if not active_units:
            return ControlAction(
                action_type=ActionType.NO_ACTION, reason="Keine aktiven Geräte mit Sollwert"
            )

        # Find unit with highest setpoint (most room to reduce)
        target_name, target_unit = max(active_units, key=lambda x: x[1].target_temp or 0)

        current_setpoint = target_unit.target_temp
        new_setpoint = current_setpoint - 0.5  # Reduce by 0.5°C

        # Safety check: don't go below minimum comfort
        min_temp = self.config.get("comfort", {}).get("min_temp", 19.0)
        if new_setpoint < min_temp:
            return ControlAction(
                action_type=ActionType.NO_ACTION,
                reason=f"Kann Sollwert nicht weiter senken (Min: {min_temp}°C)",
            )

        return ControlAction(
            action_type=ActionType.ADJUST_TEMP,
            target_unit=target_name,
            parameters={"temperature": new_setpoint, "previous": current_setpoint},
            reason=f"Temperaturmodulation: {target_name} von {current_setpoint}°C auf {new_setpoint}°C",
        )

    def _strategy_fan_control(self, status: OptimizerStatus) -> ControlAction:
        """Reduce fan speed to slow heat transfer."""
        active_units = [
            (name, unit)
            for name, unit in status.units.items()
            if unit.is_on and unit.fan_mode not in ("low", "quiet", "silent")
        ]

        if not active_units:
            return ControlAction(
                action_type=ActionType.NO_ACTION,
                reason="Alle Geräte bereits auf niedriger Lüfterstufe",
            )

        target_name, target_unit = active_units[0]

        return ControlAction(
            action_type=ActionType.ADJUST_FAN,
            target_unit=target_name,
            parameters={"fan_mode": "low", "previous": target_unit.fan_mode},
            reason=f"Lüfterreduzierung: {target_name} auf 'low'",
        )

    def execute_action(self, action: ControlAction) -> ActionResult:
        """Execute the decided action."""
        if action.action_type == ActionType.NO_ACTION:
            return ActionResult(success=True, action=action, message="Keine Aktion nötig")

        if not self._action_callback:
            logger.warning("No action callback set - cannot execute action")
            return ActionResult(
                success=False,
                action=action,
                message="Keine Callback-Funktion für Aktionen konfiguriert",
            )

        try:
            success = self._action_callback(action)

            if success:
                self._last_action_time = datetime.now(UTC)
                self._action_history.append(action)
                self.stats["actions_taken"] += 1

                if action.action_type == ActionType.ENABLE_UNIT:
                    self.stats["load_balancing_count"] += 1
                elif action.action_type == ActionType.ADJUST_TEMP:
                    self.stats["temp_adjustments"] += 1

                logger.info(f"Action executed: {action.action_type.value} - {action.reason}")

            return ActionResult(
                success=success,
                action=action,
                message="Erfolgreich" if success else "Ausführung fehlgeschlagen",
            )

        except Exception as e:
            logger.error(f"Action execution failed: {e}")
            return ActionResult(success=False, action=action, message=f"Fehler: {str(e)}")

    def record_prevented_cycle(self):
        """Record that a cycle was successfully prevented."""
        self.stats["cycles_prevented"] += 1

    def get_dashboard_data(self) -> dict[str, Any]:
        """Get data for Home Assistant dashboard."""
        recent_actions = self._action_history[-10:]  # Last 10 actions

        return {
            "stats": self.stats,
            "last_action": self._action_history[-1].reason if self._action_history else None,
            "last_action_time": (
                self._last_action_time.isoformat() if self._last_action_time else None
            ),
            "recent_actions": [
                {
                    "type": a.action_type.value,
                    "target": a.target_unit,
                    "reason": a.reason,
                    "time": a.timestamp.isoformat(),
                }
                for a in recent_actions
            ],
        }
