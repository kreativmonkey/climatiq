"""
Unit tests for Multi-Device Support (V3)
Tests backward compatibility and new multi-device features.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add appdaemon/apps to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "appdaemon" / "apps"))

# Mock appdaemon before importing the controller
sys.modules["appdaemon"] = MagicMock()
sys.modules["appdaemon.plugins"] = MagicMock()
sys.modules["appdaemon.plugins.hass"] = MagicMock()
sys.modules["appdaemon.plugins.hass.hassapi"] = MagicMock()


# Create a mock Hass base class
class MockHass:
    """Mock hassapi.Hass for testing"""

    def __init__(self):
        self.args = {}
        self.states = {}
        self.services_called = []
        self.logs = []

    def log(self, message, level="INFO"):
        self.logs.append({"message": message, "level": level})

    def get_state(self, entity_id, attribute=None):
        if entity_id not in self.states:
            return "unavailable"
        if attribute:
            return self.states[entity_id].get("attributes", {}).get(attribute)
        return self.states[entity_id].get("state")

    def call_service(self, service, **kwargs):
        self.services_called.append({"service": service, "kwargs": kwargs})

    def run_every(self, callback, start_time, interval):
        pass

    def run_daily(self, callback, time):
        pass

    def get_history(self, entity_id, start_time, end_time):
        return []


# Patch hass.Hass before importing controller
sys.modules["appdaemon.plugins.hass.hassapi"].Hass = MockHass

# Now import the controller
import climatiq_controller  # noqa: E402


@pytest.fixture
def single_unit_config():
    """Single outdoor unit config (backward compatible)"""
    return {
        "controller": {"operating_mode": "heat"},
        "sensors": {
            "power": "sensor.ac_current_energy",
            "outdoor_temp": "sensor.outdoor_temp",
        },
        "rooms": {
            "wohnzimmer": {
                "temp_sensor": "sensor.temp_wz",
                "climate_entity": "climate.wz",
            },
            "schlafzimmer": {
                "temp_sensor": "sensor.temp_sz",
                "climate_entity": "climate.sz",
            },
        },
        "rules": {
            "comfort": {"temp_tolerance_cold": 1.5, "temp_tolerance_warm": 1.0},
            "adjustments": {"target_step": 0.5, "target_min": 16.0, "target_max": 24.0},
            "hysteresis": {"min_action_interval_minutes": 15},
            "stability": {"max_actions_per_cycle": 2},
        },
    }


@pytest.fixture
def multi_unit_config():
    """Multiple outdoor units config"""
    return {
        "outdoor_units": {
            "unit_1": {
                "operating_mode": "heat",
                "power_sensor": "sensor.ac_unit1_power",
            },
            "unit_2": {
                "operating_mode": "cool",
                "power_sensor": "sensor.ac_unit2_power",
            },
        },
        "sensors": {"outdoor_temp": "sensor.outdoor_temp"},
        "rooms": {
            "erdgeschoss": {
                "outdoor_unit": "unit_1",
                "temp_sensor": "sensor.temp_eg",
                "climate_entity": "climate.eg",
            },
            "kinderzimmer": {
                "outdoor_unit": "unit_2",
                "temp_sensor": "sensor.temp_kz",
                "climate_entity": "climate.kz",
            },
        },
        "rules": {
            "comfort": {"temp_tolerance_cold": 1.5, "temp_tolerance_warm": 1.0},
            "adjustments": {"target_step": 0.5, "target_min": 16.0, "target_max": 24.0},
            "hysteresis": {"min_action_interval_minutes": 15},
            "stability": {"max_actions_per_cycle": 2},
        },
    }


def create_controller(config):
    """Helper to create a controller without full initialization"""
    controller = climatiq_controller.ClimatIQController()
    controller.args = config
    controller.rooms = config.get("rooms", {})
    controller.sensors = config.get("sensors", {})
    controller.rules = config.get("rules", {})
    controller.influx_config = config.get("influxdb", {})
    controller.last_action_time = {}
    controller.unstable_zones = []
    controller.stable_zones = []

    # Parse outdoor units
    controller.outdoor_units = controller.parse_outdoor_units()

    return controller


def test_backward_compatible_single_unit(single_unit_config):
    """Test that single-unit config (old format) still works"""
    controller = create_controller(single_unit_config)

    outdoor_units = controller.outdoor_units

    assert "default" in outdoor_units
    assert outdoor_units["default"]["operating_mode"] == "heat"
    assert outdoor_units["default"]["power_sensor"] == "sensor.ac_current_energy"


def test_multi_unit_config_parsing(multi_unit_config):
    """Test parsing of multi-unit config"""
    controller = create_controller(multi_unit_config)

    outdoor_units = controller.outdoor_units

    assert len(outdoor_units) == 2
    assert "unit_1" in outdoor_units
    assert "unit_2" in outdoor_units
    assert outdoor_units["unit_1"]["operating_mode"] == "heat"
    assert outdoor_units["unit_2"]["operating_mode"] == "cool"


def test_get_outdoor_unit_for_room(multi_unit_config):
    """Test room-to-unit assignment"""
    controller = create_controller(multi_unit_config)

    # Test explicit assignment
    unit_id, unit_cfg = controller.get_outdoor_unit_for_room("erdgeschoss")
    assert unit_id == "unit_1"
    assert unit_cfg["operating_mode"] == "heat"

    unit_id, unit_cfg = controller.get_outdoor_unit_for_room("kinderzimmer")
    assert unit_id == "unit_2"
    assert unit_cfg["operating_mode"] == "cool"


def test_power_aggregation_single_unit(single_unit_config):
    """Test power aggregation with single unit"""
    controller = create_controller(single_unit_config)

    # Mock get_state
    controller.get_state = lambda entity_id: "1500" if "power" in entity_id else None

    power = controller.get_total_power()
    assert power == 1500.0


def test_power_aggregation_multi_unit(multi_unit_config):
    """Test power aggregation across multiple units"""
    controller = create_controller(multi_unit_config)

    # Mock state - different power per unit
    def mock_get_state(entity_id):
        if entity_id == "sensor.ac_unit1_power":
            return "800"
        elif entity_id == "sensor.ac_unit2_power":
            return "600"
        return None

    controller.get_state = mock_get_state

    power = controller.get_total_power()
    assert power == 1400.0  # 800 + 600


def test_turn_room_on_with_correct_mode(multi_unit_config):
    """Test that turning on a room uses the correct operating mode"""
    controller = create_controller(multi_unit_config)

    services_called = []
    controller.call_service = lambda service, **kwargs: services_called.append(
        {"service": service, "kwargs": kwargs}
    )

    # Turn on room on unit_1 (heat mode)
    controller.turn_room_on("erdgeschoss")

    # Check service call
    assert len(services_called) == 1
    call = services_called[0]
    assert call["service"] == "climate/set_hvac_mode"
    assert call["kwargs"]["entity_id"] == "climate.eg"
    assert call["kwargs"]["hvac_mode"] == "heat"

    # Clear and test unit_2 (cool mode)
    services_called.clear()
    controller.turn_room_on("kinderzimmer")

    assert len(services_called) == 1
    call = services_called[0]
    assert call["kwargs"]["hvac_mode"] == "cool"


def test_turn_room_off(multi_unit_config):
    """Test turning off a room"""
    controller = create_controller(multi_unit_config)

    services_called = []
    controller.call_service = lambda service, **kwargs: services_called.append(
        {"service": service, "kwargs": kwargs}
    )

    controller.turn_room_off("erdgeschoss")

    assert len(services_called) == 1
    call = services_called[0]
    assert call["service"] == "climate/turn_off"
    assert call["kwargs"]["entity_id"] == "climate.eg"


def test_night_mode_turns_off_rooms(multi_unit_config):
    """Test that night mode triggers turn_off actions"""
    controller = create_controller(multi_unit_config)

    # Mock current time to be in night mode (23:00)
    with patch("climatiq_controller.datetime") as mock_datetime:
        mock_datetime.now.return_value.hour = 23

        state = {
            "power": 1000,
            "outdoor_temp": 5.0,
            "rooms": {
                "erdgeschoss": {
                    "current_temp": 21.0,
                    "target_temp": 21.5,
                    "delta": -0.5,  # Slightly below target, ok to turn off
                    "is_on": True,
                }
            },
            "total_delta_abs": 0.5,
        }

        actions = controller.decide_actions(state)

        # Should decide to turn off room
        assert len(actions) > 0
        assert actions[0]["action_type"] == "turn_off"
        assert "Night mode" in actions[0]["reason"]


def test_overheating_prevention(multi_unit_config):
    """Test that overheating triggers turn_off"""
    controller = create_controller(multi_unit_config)

    state = {
        "power": 1500,
        "outdoor_temp": 5.0,
        "rooms": {
            "erdgeschoss": {
                "current_temp": 23.5,
                "target_temp": 21.0,
                "delta": 2.5,  # Much too warm
                "is_on": True,
            }
        },
        "total_delta_abs": 2.5,
    }

    actions = controller.decide_actions(state)

    # Should turn off due to overheating
    assert len(actions) > 0
    assert actions[0]["action_type"] == "turn_off"
    assert "Overheating" in actions[0]["reason"]


def test_too_cold_turns_on_room(multi_unit_config):
    """Test that too cold triggers turn_on when room is off"""
    controller = create_controller(multi_unit_config)

    state = {
        "power": 800,
        "outdoor_temp": 5.0,
        "rooms": {
            "erdgeschoss": {
                "current_temp": 18.0,
                "target_temp": 21.0,
                "delta": -3.0,  # Much too cold
                "is_on": False,
            }
        },
        "total_delta_abs": 3.0,
    }

    actions = controller.decide_actions(state)

    # Should turn on room
    assert len(actions) > 0
    assert actions[0]["action_type"] == "turn_on"
    assert actions[0]["unit_id"] == "unit_1"
    assert "Too cold" in actions[0]["reason"]


def test_stability_targeting_turns_on_room(multi_unit_config):
    """Test that low power triggers turn_on for stability"""
    controller = create_controller(multi_unit_config)

    state = {
        "power": 450,  # Below 500W threshold
        "outdoor_temp": 5.0,
        "rooms": {
            "erdgeschoss": {
                "current_temp": 20.0,
                "target_temp": 21.0,
                "delta": -1.0,  # Slightly cold
                "is_on": False,
            }
        },
        "total_delta_abs": 1.0,
    }

    actions = controller.decide_actions(state)

    # Should turn on for stability
    assert len(actions) > 0
    assert actions[0]["action_type"] == "turn_on"
    assert "Stability targeting" in actions[0]["reason"]


def test_cooldown_prevents_rapid_changes(multi_unit_config):
    """Test that cooldown prevents actions too soon"""
    controller = create_controller(multi_unit_config)

    # Set last action time to 5 minutes ago (within 15min cooldown)
    controller.last_action_time = {"erdgeschoss": datetime.now() - timedelta(minutes=5)}

    state = {
        "power": 800,
        "outdoor_temp": 5.0,
        "rooms": {
            "erdgeschoss": {
                "current_temp": 18.0,
                "target_temp": 21.0,
                "delta": -3.0,
                "is_on": True,
            }
        },
        "total_delta_abs": 3.0,
    }

    actions = controller.decide_actions(state)

    # Should not create action due to cooldown
    assert len(actions) == 0


def test_validate_outdoor_unit_modes(multi_unit_config):
    """Test outdoor unit mode validation"""
    controller = create_controller(multi_unit_config)

    # Should be valid (different modes across different units is OK)
    is_valid = controller.validate_outdoor_unit_modes()
    assert is_valid is True
