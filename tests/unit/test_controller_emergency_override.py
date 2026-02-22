"""
Unit tests for emergency override logic in ClimatIQ Controller

Tests TWO types of emergencies:
1. Comfort Emergency: Individual room outside tolerance zone
2. Stability Emergency: Power oscillating (high fluctuation)
"""

import statistics
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch


def _setup_mocks():
    """Setup appdaemon mocks before importing controller"""
    sys.modules["appdaemon"] = MagicMock()
    sys.modules["appdaemon.plugins"] = MagicMock()
    sys.modules["appdaemon.plugins.hass"] = MagicMock()
    sys.modules["appdaemon.plugins.hass.hassapi"] = MagicMock()


# Setup mocks once at module level
_setup_mocks()

# Import after mocking (ruff: noqa: E402)
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
                "living": {"delta": -2.0, "target": 21.0, "current": 19.0},  # -2K < -1.5K
            }
        }

        # Should trigger comfort emergency
        result = controller._check_comfort_emergency(state)
        assert result is True

        # Check that warning was logged
        assert controller.log.called
        log_message = str(controller.log.call_args)
        assert "Too cold" in log_message
        assert "living" in log_message

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

        # State with room too warm
        state = {
            "rooms": {
                "living": {"delta": 1.5, "target": 21.0, "current": 22.5},  # +1.5K > +1.0K
            }
        }

        # Should trigger comfort emergency
        result = controller._check_comfort_emergency(state)
        assert result is True

        # Check that warning was logged
        assert controller.log.called
        log_message = str(controller.log.call_args)
        assert "Too warm" in log_message
        assert "living" in log_message

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

        # State with all rooms within tolerance
        state = {
            "rooms": {
                "living": {"delta": 0.5, "target": 21.0, "current": 21.5},
                "bedroom": {"delta": -0.8, "target": 20.0, "current": 19.2},
            }
        }

        # Should NOT trigger emergency
        result = controller._check_comfort_emergency(state)
        assert result is False

    def test_comfort_emergency_multi_room_one_violates(self):
        """Test emergency triggered when only one room violates tolerance"""
        controller = ClimatIQController(None, None, None, None, None, None, None, None)
        controller.log = MagicMock()

        controller.rules = {
            "comfort": {
                "temp_tolerance_cold": 1.5,
                "temp_tolerance_warm": 1.0,
            }
        }

        # Multiple rooms, only one too cold
        state = {
            "rooms": {
                "living": {"delta": 0.3, "target": 21.0, "current": 21.3},
                "bedroom": {"delta": -1.8, "target": 20.0, "current": 18.2},  # Too cold!
                "office": {"delta": 0.5, "target": 19.0, "current": 19.5},
            }
        }

        # Should trigger emergency due to bedroom
        result = controller._check_comfort_emergency(state)
        assert result is True


class TestStabilityEmergency:
    """Test stability emergency detection (power oscillation checks)"""

    def test_stability_emergency_high_oscillation(self):
        """Test stability emergency when power oscillates heavily"""
        # Oscillating power values
        power_values = [500, 1200, 600, 1400, 550, 1300, 580]  # High range & StdDev

        # Calculate metrics
        std = statistics.stdev(power_values)  # Should be ~370W
        range_val = max(power_values) - min(power_values)  # 900W

        # With thresholds: std_threshold=300W, range_threshold=800W
        # Both exceeded → emergency
        assert std > 300
        assert range_val > 800

    def test_stability_no_emergency_stable_power(self):
        """Test no emergency when power is stable"""
        # Stable power values
        power_values = [1500, 1520, 1480, 1510, 1490, 1505]  # Low fluctuation

        # Calculate metrics
        std = statistics.stdev(power_values)  # Should be ~17W
        range_val = max(power_values) - min(power_values)  # 40W

        # With thresholds: std_threshold=300W, range_threshold=800W
        # Neither exceeded → no emergency
        assert std < 300
        assert range_val < 800

    @patch("appdaemon.apps.climatiq_controller.InfluxDBClient")
    def test_stability_emergency_with_influxdb(self, mock_influx_client):
        """Test stability emergency check with InfluxDB integration"""
        controller = ClimatIQController(None, None, None, None, None, None, None, None)
        controller.log = MagicMock()

        # Setup config
        controller.rules = {
            "stability": {
                "power_std_threshold": 300,
                "power_range_threshold": 800,
            }
        }

        controller.outdoor_units = {"default": {"power_sensor": "sensor.ac_current_energy"}}

        controller.influx_config = {
            "host": "localhost",
            "port": 8086,
            "database": "homeassistant",
            "measurement": "W",
        }

        # Mock InfluxDB response with oscillating data
        mock_client_instance = MagicMock()
        mock_influx_client.return_value = mock_client_instance

        # Oscillating power data
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

        # Should detect oscillation
        result = controller._check_stability_emergency(state)
        assert result is True

        # Check that oscillation was logged
        assert controller.log.called
        log_message = str(controller.log.call_args)
        assert "Power oscillating" in log_message or "oscillating" in log_message.lower()

    @patch("appdaemon.apps.climatiq_controller.InfluxDBClient")
    def test_stability_no_emergency_with_stable_data(self, mock_influx_client):
        """Test no stability emergency when power is stable"""
        controller = ClimatIQController(None, None, None, None, None, None, None, None)
        controller.log = MagicMock()

        controller.rules = {
            "stability": {
                "power_std_threshold": 300,
                "power_range_threshold": 800,
            }
        }

        controller.outdoor_units = {"default": {"power_sensor": "sensor.ac_current_energy"}}

        controller.influx_config = {
            "host": "localhost",
            "port": 8086,
            "database": "homeassistant",
            "measurement": "W",
        }

        # Mock InfluxDB response with stable data
        mock_client_instance = MagicMock()
        mock_influx_client.return_value = mock_client_instance

        # Stable power data
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

        # Should NOT detect emergency
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

        # No InfluxDB configured
        controller.influx_config = {}
        controller.outdoor_units = {"default": {"power_sensor": "sensor.power"}}

        state = {"power": 1000}

        # Should return False (not emergency) when no InfluxDB
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
                "min_action_interval_minutes": 15,  # Normal cooldown
                "emergency_action_interval_minutes": 7,  # Emergency cooldown (shorter!)
            },
            "stability": {"max_actions_per_cycle": 2},
        }

        controller.get_outdoor_unit_for_room = MagicMock(
            return_value=("default", {"operating_mode": "heat"})
        )

        # State with room needing action
        state = {
            "power": 1000,
            "rooms": {
                "living": {
                    "delta": -2.0,  # Too cold
                    "target": 21.0,
                    "current": 19.0,
                    "is_on": False,
                }
            },
        }

        # Normal mode - no actions due to no recent action
        actions_normal = controller.decide_actions(state, is_emergency=False)
        # Should have action since no cooldown active
        assert len(actions_normal) > 0

        # Set last action time to 10 minutes ago
        controller.last_action_time["living"] = datetime.now() - timedelta(minutes=10)

        # Normal mode - should be blocked by 15min cooldown
        actions_normal_blocked = controller.decide_actions(state, is_emergency=False)
        assert len(actions_normal_blocked) == 0  # Blocked by normal cooldown

        # Emergency mode - 7min cooldown, so 10 minutes ago is OK!
        actions_emergency = controller.decide_actions(state, is_emergency=True)
        assert len(actions_emergency) > 0  # Allowed by shorter emergency cooldown
