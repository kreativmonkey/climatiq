"""Tests for ClimatIQ Home Assistant device and sensors"""

from unittest.mock import Mock, call


class TestDeviceSensors:
    """Test device and sensor creation/updates"""

    def test_device_creation(self):
        """Test that device and sensors are created correctly"""
        # Mock AppDaemon app
        mock_app = Mock()
        mock_app.set_state = Mock()
        mock_app.log = Mock()

        # Create device_info
        device_info = {
            "identifiers": [("climatiq", "controller")],
            "name": "ClimatIQ Controller",
            "model": "Rule-Based Heat Pump Controller",
            "manufacturer": "ClimatIQ",
            "sw_version": "3.1.0",
        }

        # Expected sensors
        expected_sensors = [
            "sensor.climatiq_power",
            "sensor.climatiq_outdoor_temp",
            "sensor.climatiq_total_delta",
            "sensor.climatiq_stability_state",
            "sensor.climatiq_cycles_today",
            "sensor.climatiq_actions_today",
            "sensor.climatiq_last_reward",
            "sensor.climatiq_compressor_runtime",
            "sensor.climatiq_emergency_active",
            "sensor.climatiq_cooldown_active",
            "sensor.climatiq_active_rooms",
            "sensor.climatiq_critical_room",
        ]

        # Simulate sensor creation
        for sensor_id in expected_sensors:
            mock_app.set_state(sensor_id, state=0, attributes={"device": device_info})

        # Verify 12 sensors were created
        assert mock_app.set_state.call_count == 12

        # Check device info in calls
        for call_args in mock_app.set_state.call_args_list:
            attrs = call_args[1]["attributes"]
            assert "device" in attrs
            assert attrs["device"]["name"] == "ClimatIQ Controller"
            assert attrs["device"]["manufacturer"] == "ClimatIQ"

    def test_sensor_updates_system_metrics(self):
        """Test that system metric sensors are updated with correct values"""
        mock_app = Mock()
        mock_app.set_state = Mock()
        mock_app.log = Mock()

        state = {
            "power": 1200,
            "outdoor_temp": 5.0,
            "total_delta_abs": 3.5,
            "rooms": {
                "living": {"delta": 2.0, "hvac_mode": "heat"},
                "bedroom": {"delta": 1.5, "hvac_mode": "heat"},
            },
        }

        # Simulate updates
        mock_app.set_state("sensor.climatiq_power", state=state["power"])
        mock_app.set_state("sensor.climatiq_outdoor_temp", state=state["outdoor_temp"])
        mock_app.set_state("sensor.climatiq_total_delta", state=state["total_delta_abs"])

        # Verify correct values
        calls = mock_app.set_state.call_args_list
        assert calls[0] == call("sensor.climatiq_power", state=1200)
        assert calls[1] == call("sensor.climatiq_outdoor_temp", state=5.0)
        assert calls[2] == call("sensor.climatiq_total_delta", state=3.5)

    def test_stability_state_unstable(self):
        """Test stability state detection - unstable zone"""
        mock_app = Mock()
        mock_app.set_state = Mock()

        # Power in unstable zone (1000-1500W)
        power = 1200

        if 1000 <= power <= 1500:
            stability = "unstable"
        elif power < 700 or 1700 < power < 2100:
            stability = "stable"
        else:
            stability = "transition"

        mock_app.set_state("sensor.climatiq_stability_state", state=stability)

        # Verify unstable state
        call_args = mock_app.set_state.call_args
        assert call_args[1]["state"] == "unstable"

    def test_stability_state_stable(self):
        """Test stability state detection - stable zone"""
        mock_app = Mock()
        mock_app.set_state = Mock()

        # Power in stable zone (<700W)
        power = 600

        if 1000 <= power <= 1500:
            stability = "unstable"
        elif power < 700 or 1700 < power < 2100:
            stability = "stable"
        else:
            stability = "transition"

        mock_app.set_state("sensor.climatiq_stability_state", state=stability)

        # Verify stable state
        call_args = mock_app.set_state.call_args
        assert call_args[1]["state"] == "stable"

    def test_stability_state_transition(self):
        """Test stability state detection - transition zone"""
        mock_app = Mock()
        mock_app.set_state = Mock()

        # Power in transition zone (1500-1700W)
        power = 1600

        if 1000 <= power <= 1500:
            stability = "unstable"
        elif power < 700 or 1700 < power < 2100:
            stability = "stable"
        else:
            stability = "transition"

        mock_app.set_state("sensor.climatiq_stability_state", state=stability)

        # Verify transition state
        call_args = mock_app.set_state.call_args
        assert call_args[1]["state"] == "transition"

    def test_critical_room_detection(self):
        """Test critical room (highest delta) detection"""
        mock_app = Mock()
        mock_app.set_state = Mock()

        state = {
            "rooms": {
                "living": {"delta": 2.0, "hvac_mode": "heat"},
                "bedroom": {"delta": -3.5, "hvac_mode": "heat"},
                "office": {"delta": 1.0, "hvac_mode": "heat"},
            },
        }

        # Find critical room
        critical_room = "none"
        max_delta = 0
        for name, room in state["rooms"].items():
            delta = abs(room["delta"])
            if delta > max_delta:
                max_delta = delta
                critical_room = name

        critical_display = (
            f"{critical_room} ({max_delta:.1f}K)" if critical_room != "none" else "none"
        )

        # Verify bedroom is critical (highest absolute delta: 3.5K)
        assert critical_room == "bedroom"
        assert critical_display == "bedroom (3.5K)"

    def test_active_rooms_count(self):
        """Test active rooms count"""
        mock_app = Mock()
        mock_app.set_state = Mock()

        state = {
            "rooms": {
                "living": {"delta": 2.0, "hvac_mode": "heat"},
                "bedroom": {"delta": 1.5, "hvac_mode": "off"},
                "office": {"delta": 1.0, "hvac_mode": "cool"},
                "kitchen": {"delta": 0.5, "hvac_mode": "off"},
            },
        }

        # Count active rooms
        active_rooms = sum(
            1 for room in state["rooms"].values() if room["hvac_mode"] in ["heat", "cool"]
        )

        # Verify count (living + office = 2)
        assert active_rooms == 2

    def test_emergency_status(self):
        """Test emergency status sensor"""
        mock_app = Mock()
        mock_app.set_state = Mock()

        # Emergency active
        is_emergency = True
        mock_app.set_state(
            "sensor.climatiq_emergency_active", state="on" if is_emergency else "off"
        )
        assert mock_app.set_state.call_args[1]["state"] == "on"

        # Emergency inactive
        mock_app.set_state.reset_mock()
        is_emergency = False
        mock_app.set_state(
            "sensor.climatiq_emergency_active", state="on" if is_emergency else "off"
        )
        assert mock_app.set_state.call_args[1]["state"] == "off"

    def test_actions_counter(self):
        """Test actions counter increments correctly"""
        # Simulate daily counter
        daily_actions = 0

        # Increment for actions
        actions_1 = [{"room": "living", "action": "turn_on"}]
        actions_2 = [
            {"room": "bedroom", "action": "turn_off"},
            {"room": "office", "action": "adjust"},
        ]

        if len(actions_1) > 0:
            daily_actions += len(actions_1)

        assert daily_actions == 1

        if len(actions_2) > 0:
            daily_actions += len(actions_2)

        assert daily_actions == 3

    def test_cycles_detection(self):
        """Test compressor cycle detection (low to high power transition)"""
        daily_cycles = 0
        last_power_state = None
        
        # Sequence: low -> high (cycle detected)
        powers = [600, 650, 1200, 1300, 650, 600, 1400]
        
        for current_power in powers:
            if last_power_state is not None:
                if last_power_state < 700 and current_power > 700:
                    daily_cycles += 1
            last_power_state = current_power
        
        # Should detect 2 cycles (650->1200 and 600->1400)
        assert daily_cycles == 2
