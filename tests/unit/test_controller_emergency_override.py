"""
Unit tests for emergency override logic in ClimatIQ Controller

Tests TWO types of emergencies:
1. Comfort Emergency: Individual room outside tolerance zone
2. Stability Emergency: Power oscillating (high fluctuation)
"""

import statistics
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock


# Mock appdaemon dependencies BEFORE importing controller
class MockHass:
    """Mock Hass base class for controller inheritance"""

    def __init__(self, *args, **kwargs):
        pass


# Create mock module structure
mock_hassapi = type(sys)("appdaemon.plugins.hass.hassapi")
mock_hassapi.Hass = MockHass

mock_hass = type(sys)("appdaemon.plugins.hass")
mock_hass.hassapi = mock_hassapi

mock_plugins = type(sys)("appdaemon.plugins")
mock_plugins.hass = mock_hass

sys.modules["appdaemon.plugins.hass.hassapi"] = mock_hassapi
sys.modules["appdaemon.plugins.hass"] = mock_hass
sys.modules["appdaemon.plugins"] = mock_plugins

# Mock numpy and influxdb dependencies
sys.modules["numpy"] = MagicMock()
mock_influxdb = MagicMock()
sys.modules["influxdb"] = mock_influxdb

# Import controller after mocking dependencies
from appdaemon.apps.climatiq_controller import ClimatIQController  # noqa: E402


class TestComfortEmergency:
    """Test comfort emergency detection (per-room tolerance checks)"""

    def test_comfort_emergency_too_cold(self):
        """Test comfort emergency when room is too cold"""
        controller = ClimatIQController(None, None, None, None, None, None, None, None)
        controller.log = MagicMock()

        # Setup config
        controller.rules = {
            "comfort": {
                "temp_tolerance_cold": 1.5,
                "temp_tolerance_warm": 1.0,
            }
        }

        # State with room too cold
        state = {
            "rooms": {
                "living": {"delta": -2.0, "target_temp": 21.0, "current": 19.0},
            }
        }

        result = controller._check_comfort_emergency(state)
        assert result is True

    def test_comfort_emergency_too_warm(self):
        """Test comfort emergency when room is too warm"""
        controller = ClimatIQController(None, None, None, None, None, None, None, None)
        controller.log = MagicMock()

        controller.rules = {
            "comfort": {
                "temp_tolerance_cold": 1.5,
                "temp_tolerance_warm": 1.0,
            }
        }

        state = {
            "rooms": {
                "living": {"delta": 1.5, "target_temp": 21.0, "current": 22.5},
            }
        }

        result = controller._check_comfort_emergency(state)
        assert result is True

    def test_comfort_no_emergency_within_tolerance(self):
        """Test no emergency when all rooms within tolerance"""
        controller = ClimatIQController(None, None, None, None, None, None, None, None)
        controller.log = MagicMock()

        controller.rules = {
            "comfort": {
                "temp_tolerance_cold": 1.5,
                "temp_tolerance_warm": 1.0,
            }
        }

        state = {
            "rooms": {
                "living": {"delta": 0.5},
                "bedroom": {"delta": -0.8},
            }
        }

        result = controller._check_comfort_emergency(state)
        assert result is False

    def test_comfort_emergency_multi_room_one_violates(self):
        """Test emergency when one room violates tolerance"""
        controller = ClimatIQController(None, None, None, None, None, None, None, None)
        controller.log = MagicMock()

        controller.rules = {
            "comfort": {
                "temp_tolerance_cold": 1.5,
                "temp_tolerance_warm": 1.0,
            }
        }

        state = {
            "rooms": {
                "living": {"delta": 0.3},
                "bedroom": {"delta": -1.8},
                "office": {"delta": 0.5},
            }
        }

        result = controller._check_comfort_emergency(state)
        assert result is True


class TestStabilityEmergency:
    """Test stability emergency detection (power oscillation checks)"""

    def test_stability_emergency_high_oscillation(self):
        """Test stability emergency when power oscillates heavily"""
        power_values = [500, 1200, 600, 1400, 550, 1300, 580]

        std = statistics.stdev(power_values)
        range_val = max(power_values) - min(power_values)

        assert std > 300
        assert range_val > 800

    def test_stability_no_emergency_stable_power(self):
        """Test no emergency when power is stable"""
        power_values = [1500, 1520, 1480, 1510, 1490, 1505]

        std = statistics.stdev(power_values)
        range_val = max(power_values) - min(power_values)

        assert std < 300
        assert range_val < 800

    def test_stability_emergency_with_influxdb(self):
        """Test stability emergency check with InfluxDB integration"""
        controller = ClimatIQController(None, None, None, None, None, None, None, None)
        controller.log = MagicMock()

        controller.rules = {
            "stability": {
                "power_std_threshold": 300,
                "power_range_threshold": 800,
            }
        }

        controller.outdoor_units = {"default": {"power_sensor": "sensor.ac_power"}}
        controller.influx_config = {
            "host": "localhost",
            "port": 8086,
            "database": "homeassistant",
            "measurement": "W",
        }

        # Mock the InfluxDBClient that gets imported inside the method
        mock_client_instance = MagicMock()
        mock_influxdb.InfluxDBClient.return_value = mock_client_instance

        mock_points = [
            {"power": 500},
            {"power": 1200},
            {"power": 600},
            {"power": 1400},
            {"power": 550},
            {"power": 1300},
            {"power": 580},
        ]

        mock_result = Mock()
        mock_result.get_points.return_value = iter(mock_points)
        mock_client_instance.query.return_value = mock_result

        state = {"power": 800}

        result = controller._check_stability_emergency(state)
        assert result is True

    def test_stability_no_emergency_with_stable_data(self):
        """Test no stability emergency when power is stable"""
        controller = ClimatIQController(None, None, None, None, None, None, None, None)
        controller.log = MagicMock()

        controller.rules = {
            "stability": {
                "power_std_threshold": 300,
                "power_range_threshold": 800,
            }
        }

        controller.outdoor_units = {"default": {"power_sensor": "sensor.ac_power"}}
        controller.influx_config = {
            "host": "localhost",
            "port": 8086,
            "database": "homeassistant",
            "measurement": "W",
        }

        # Mock the InfluxDBClient
        mock_client_instance = MagicMock()
        mock_influxdb.InfluxDBClient.return_value = mock_client_instance

        mock_points = [
            {"power": 1500},
            {"power": 1520},
            {"power": 1480},
            {"power": 1510},
            {"power": 1490},
            {"power": 1505},
        ]

        mock_result = Mock()
        mock_result.get_points.return_value = iter(mock_points)
        mock_client_instance.query.return_value = mock_result

        state = {"power": 1500}

        result = controller._check_stability_emergency(state)
        assert result is False

    def test_stability_emergency_insufficient_data(self):
        """Test no emergency when insufficient data available"""
        controller = ClimatIQController(None, None, None, None, None, None, None, None)
        controller.log = MagicMock()

        controller.rules = {
            "stability": {
                "power_std_threshold": 300,
                "power_range_threshold": 800,
            }
        }

        controller.influx_config = {}
        controller.outdoor_units = {"default": {"power_sensor": "sensor.power"}}

        state = {"power": 1000}

        result = controller._check_stability_emergency(state)
        assert result is False


class TestEmergencyCooldown:
    """Test that emergency situations use shorter cooldown"""

    def test_emergency_cooldown_shorter_than_normal(self):
        """Test that emergency cooldown is shorter than normal"""
        controller = ClimatIQController(None, None, None, None, None, None, None, None)
        controller.log = MagicMock()
        controller.last_action_time = {}
        controller.outdoor_units = {"default": {"operating_mode": "heat"}}
        controller.rooms = {"living": {}}

        controller.rules = {
            "comfort": {"temp_tolerance_cold": 1.5, "temp_tolerance_warm": 1.0},
            "adjustments": {"target_step": 0.5, "target_min": 16.0, "target_max": 24.0},
            "hysteresis": {
                "min_action_interval_minutes": 15,
                "emergency_action_interval_minutes": 7,
            },
            "stability": {"max_actions_per_cycle": 2},
        }

        controller.get_outdoor_unit_for_room = MagicMock(
            return_value=("default", {"operating_mode": "heat"})
        )

        # Use target_temp (not target) to match controller expectation
        state = {
            "power": 1000,
            "rooms": {
                "living": {
                    "delta": -2.0,
                    "target_temp": 21.0,
                    "current": 19.0,
                    "is_on": False,
                }
            },
        }

        actions_normal = controller.decide_actions(state, is_emergency=False)
        assert len(actions_normal) > 0

        controller.last_action_time["living"] = datetime.now() - timedelta(minutes=10)

        actions_normal_blocked = controller.decide_actions(state, is_emergency=False)
        assert len(actions_normal_blocked) == 0

        actions_emergency = controller.decide_actions(state, is_emergency=True)
        assert len(actions_emergency) > 0
