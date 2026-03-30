"""Controller module for HVAC optimization actions v2.

Optimized for stability and power variance reduction. Targets minimum
stable energy consumption points discovered by the Analyzer.

Features added in v3.1:
- Temperature Hysteresis: Prevents oscillation in comfort holding
- Power Zone Hysteresis: Prevents rapid zone transitions
- Heat Demand Inference: Knows the difference between idle and not-enough-heat
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from climatiq.core.entities import OptimizerStatus, SystemMode

logger = logging.getLogger(__name__)


class ActionType(str, Enum):
    """Types of control actions."""

    ENABLE_UNIT = "enable_unit"
    DISABLE_UNIT = "disable_unit"
    ADJUST_TEMP = "adjust_temp"
    ADJUST_FAN = "adjust_fan"
    NO_ACTION = "no_action"


class ActionDirection(str, Enum):
    """Direction of last action for hysteresis tracking."""

    HEATING = "heating"
    COOLING = "cooling"
    NONE = "none"


@dataclass
class ControlAction:
    """Represents a control action to be executed."""

    action_type: ActionType
    target_unit: Optional[str] = None
    parameters: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


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

    # Hysteresis settings
    TEMP_HYSTERESIS_REVERSE = 0.5  # °C - must cross this before reversing direction
    POWER_HYSTERESIS_WATTS = 100  # Buffer around unstable zones

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._last_action_time: Optional[datetime] = None
        self._action_history: list[ControlAction] = []
        self._action_callback: Optional[Callable] = None

        # Temperature hysteresis tracking per unit
        self._unit_action_direction: dict[str, ActionDirection] = {}

        # Power zone hysteresis
        self._power_hysteresis_state: Optional[str] = None

        # Statistics
        self.stats = {
            "actions_taken": 0,
            "cycles_prevented": 0,
            "stability_actions": 0,
            "night_mode_actions": 0,
            "gradual_nudges": 0,
        }

        # Override hysteresis from config if present
        hyst = config.get("hysteresis", {})
        if "temp_hysteresis_reverse" in hyst:
            self.TEMP_HYSTERESIS_REVERSE = hyst["temp_hysteresis_reverse"]
        if "power_hysteresis_watts" in hyst:
            self.POWER_HYSTERESIS_WATTS = hyst["power_hysteresis_watts"]

    def set_action_callback(self, callback: Callable[[ControlAction], bool]):
        self._action_callback = callback

    def should_act(self, status: OptimizerStatus) -> bool:
        if status.mode in (SystemMode.OBSERVATION, SystemMode.MANUAL):
            return False

        if self._last_action_time:
            elapsed = datetime.now(timezone.utc) - self._last_action_time
            if elapsed < self.MIN_ACTION_INTERVAL:
                return False

        return True

    def is_night_mode(self) -> bool:
        """Check if we are in night hours (23:00 - 06:00)."""
        now = datetime.now(timezone.utc).astimezone()  # Use local time if possible
        return now.hour >= 23 or now.hour < 6

    def decide_action(
        self, status: OptimizerStatus, prediction: dict[str, Any], analysis: dict[str, Any]
    ) -> ControlAction:
        """v2 Decision Logic: Stabilize and Minimize."""

        # 1. Check unstable power zones with hysteresis
        unstable_zones = analysis.get("unstable_zones", [])
        in_unstable, zone_reason = self._check_unstable_zone_hysteresis(
            status.power_consumption, unstable_zones
        )
        if in_unstable:
            logger.warning(f"⚠️ Instabile Zone ({status.power_consumption}W) - {zone_reason}")
            return ControlAction(ActionType.NO_ACTION, reason=f"Power-Hysterese: {zone_reason}")

        # 2. Evaluate Stability Metrics
        cycling_risk = status.cycling_risk  # Our v2 score (0-1.0)
        power_std = analysis.get("power_std", 0.0)
        power_spread = analysis.get("power_spread", 0.0)
        current_power = status.power_consumption

        # Use dynamic threshold based on heat demand
        min_stable_power = self._calculate_min_stable_power(status)

        is_unstable = (
            cycling_risk > 0.6
            or power_std > self.STABLE_STD_THRESHOLD
            or power_spread > self.HIGH_SPREAD_THRESHOLD
        )

        # No action if stable and within efficient range
        if not is_unstable and current_power >= min_stable_power:
            return ControlAction(ActionType.NO_ACTION, reason="System stabil und effizient.")

        # 3. Check if power too low given heat demand (NEW: Heat Demand Inference)
        if self._is_power_too_low_for_heat_demand(status):
            return ControlAction(
                ActionType.NO_ACTION, reason="Power zu niedrig für Wärmebedarf (idle ist OK)"
            )

        # 4. Night Mode Strategy (Preemptive)
        if self.is_night_mode() and is_unstable:
            action = self._strategy_night_mode(status, min_stable_power)
            if action.action_type != ActionType.NO_ACTION:
                self._track_action_direction(action.target_unit, action)
                self.stats["night_mode_actions"] += 1
                return action

        # 5. Stability Targeting (Load Balancing)
        # If power is too low to be stable or variance is high
        if current_power < min_stable_power or is_unstable:
            action = self._strategy_stability_targeting(status, min_stable_power, power_std)
            if action.action_type != ActionType.NO_ACTION:
                self._track_action_direction(action.target_unit, action)
                self.stats["stability_actions"] += 1
                return action

        # 6. Gradual Nudge (Temperature)
        # If we just need a tiny bit more load to reach stability
        if is_unstable:
            action = self._strategy_gradual_nudge(status)
            if action.action_type != ActionType.NO_ACTION:
                self.stats["gradual_nudges"] += 1
                return action

        return ControlAction(ActionType.NO_ACTION, reason="Keine passende Intervention gefunden.")

    def _check_unstable_zone_hysteresis(
        self, power: float, unstable_zones: list[dict]
    ) -> tuple[bool, str]:
        """Check unstable zones with hysteresis - prevents rapid zone transitions."""
        buffer = self.POWER_HYSTERESIS_WATTS

        if self._power_hysteresis_state == "avoiding_low":
            for zone in unstable_zones:
                if power > zone.get("min", 0) + buffer:
                    self._power_hysteresis_state = None
                    return False, ""
            return True, "Hysterese: vorher low-avoid"

        if self._power_hysteresis_state == "avoiding_high":
            for zone in unstable_zones:
                if power < zone.get("max", float("inf")) - buffer:
                    self._power_hysteresis_state = None
                    return False, ""
            return True, "Hysterese: vorher high-avoid"

        for zone in unstable_zones:
            zone_min = zone.get("min", 0)
            zone_max = zone.get("max", float("inf"))

            if zone_min - buffer <= power <= zone_min + buffer:
                self._power_hysteresis_state = "avoiding_low"
                return True, f"Nahe unterer Grenze ({zone_min}W), Hysterese aktiv"

            if zone_max - buffer <= power <= zone_max + buffer:
                self._power_hysteresis_state = "avoiding_high"
                return True, f"Nahe oberer Grenze ({zone_max}W), Hysterese aktiv"

            if zone_min <= power <= zone_max:
                return True, f"In Zone ({zone_min}-{zone_max}W)"

        return False, ""

    def _calculate_min_stable_power(self, status: OptimizerStatus) -> float:
        """Calculate minimum stable power based on ACTUAL heat demand.

        CRITICAL: 3 units can be ON but only 60W = ALL IDLE (normal!)
        We must INFER heat demand from temperature delta:
        - delta >= -0.5°C: unit is IDLE (room satisfied)
        - delta < -0.5°C: unit is calling for heat
        """
        rooms_calling_for_heat = 0

        for name, unit in status.units.items():
            if not unit.is_on or unit.target_temp is None:
                continue

            # Get current temp from state
            current_temp = getattr(unit, "current_temp", None)
            if current_temp is None:
                continue

            delta = current_temp - unit.target_temp

            if delta >= -0.5:
                pass  # Room satisfied
            else:
                rooms_calling_for_heat += 1

        if rooms_calling_for_heat == 0:
            return 100.0  # Very low threshold

        return 250.0 * rooms_calling_for_heat

    def _is_power_too_low_for_heat_demand(self, status: OptimizerStatus) -> bool:
        """Check if power is abnormally low given heat demand.

        Returns True ONLY if:
        - Power is below minimum AND
        - At least one unit SHOULD be calling for heat

        Returns False (OK) if:
        - All rooms are satisfied (no heat needed, low power is normal)
        """
        current_power = status.power_consumption
        min_stable = self._calculate_min_stable_power(status)

        rooms_needing_heat = sum(
            1
            for name, unit in status.units.items()
            if unit.is_on
            and unit.target_temp is not None
            and getattr(unit, "current_temp", 0) - unit.target_temp < -0.5
        )

        if rooms_needing_heat == 0:
            logger.debug(f"Power {current_power:.0f}W OK: No rooms need heat (idle)")
            return False

        if current_power < min_stable:
            logger.warning(
                f"Power TOO LOW: {current_power:.0f}W < {min_stable:.0f}W "
                f"({rooms_needing_heat} rooms need heat)"
            )
            return True

        logger.debug(f"Power OK: {current_power:.0f}W >= {min_stable:.0f}W")
        return False

    def _track_action_direction(self, target_unit: Optional[str], action: ControlAction):
        """Track action direction for temperature hysteresis."""
        if target_unit is None:
            return

        if action.action_type == ActionType.ADJUST_TEMP:
            new_temp = action.parameters.get("temperature")
            prev_temp = action.parameters.get("previous")
            if new_temp is not None and prev_temp is not None:
                if new_temp > prev_temp:
                    self._unit_action_direction[target_unit] = ActionDirection.HEATING
                elif new_temp < prev_temp:
                    self._unit_action_direction[target_unit] = ActionDirection.COOLING
        elif action.action_type == ActionType.ENABLE_UNIT:
            self._unit_action_direction[target_unit] = ActionDirection.HEATING

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
        if current_temp is None:
            return ControlAction(ActionType.NO_ACTION)

        # Temperature hysteresis check
        current_dir = self._unit_action_direction.get(target_name, ActionDirection.NONE)
        target_comfort = self.config.get("comfort", {}).get("target_temp", 21.0)

        if current_dir == ActionDirection.HEATING:
            if current_temp > target_comfort + self.TEMP_HYSTERESIS_REVERSE:
                self._unit_action_direction[target_name] = ActionDirection.NONE
            else:
                logger.debug(f"Hysterese: {target_name} im Heating-Modus, warte auf Abkühlung")
                return ControlAction(ActionType.NO_ACTION)

        elif current_dir == ActionDirection.COOLING:
            if current_temp < target_comfort - self.TEMP_HYSTERESIS_REVERSE:
                self._unit_action_direction[target_name] = ActionDirection.NONE
            else:
                logger.debug(f"Hysterese: {target_name} im Cooling-Modus, warte auf Aufwärmung")
                return ControlAction(ActionType.NO_ACTION)

        new_temp = current_temp + 0.3  # Small nudge up to increase load slightly

        max_temp = target_comfort + self.MAX_TEMP_DEVIATION
        if new_temp > max_temp:
            new_temp = current_temp - 0.3  # Try nudging down if up is blocked
            if new_temp < (target_comfort - self.MAX_TEMP_DEVIATION):
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
                self._last_action_time = datetime.now(timezone.utc)
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
            "last_action_time": self._last_action_time.isoformat()
            if self._last_action_time
            else None,
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
