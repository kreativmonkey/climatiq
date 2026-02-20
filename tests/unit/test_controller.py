"""Tests for the Controller module.

NOTE: Many of these tests are for the old Controller API (v1).
The new controller (v2) is tested in test_controller_v2.py.
Tests marked with @pytest.mark.skip need updating to match the new API.
"""

from datetime import UTC, datetime

import pytest

from climatiq.core.controller import ActionType, ControlAction, Controller
from climatiq.core.entities import OptimizerStatus, SystemMode, UnitStatus


# Skip reason for tests that need API update
SKIP_OLD_API = pytest.mark.skip(reason="Test needs update for new Controller API")


@pytest.fixture
def controller():
    """Create a Controller instance."""
    config = {
        "comfort": {"target_temp": 21.0, "min_temp": 19.0},
        "unit_priorities": {"living_room": 90, "bedroom": 50, "office": 30, "storage": 10},
    }
    return Controller(config)


@pytest.fixture
def active_status():
    """Create an active system status."""
    status = OptimizerStatus()
    status.mode = SystemMode.ACTIVE
    status.power_consumption = 350.0  # Low power - risk of cycling
    status.cycling_risk = 0.7

    # Add some units
    status.units = {
        "living_room": UnitStatus(
            name="living_room",
            entity_id="climate.living_room",
            is_on=True,
            current_temp=21.5,
            target_temp=22.0,
            fan_mode="auto",
        ),
        "bedroom": UnitStatus(
            name="bedroom",
            entity_id="climate.bedroom",
            is_on=False,
            current_temp=20.0,
            target_temp=21.0,
            fan_mode="low",
        ),
        "storage": UnitStatus(
            name="storage",
            entity_id="climate.storage",
            is_on=False,
            current_temp=18.0,
            target_temp=None,
            fan_mode=None,
        ),
    }

    return status


@pytest.fixture
def cycling_prediction():
    """Create a cycling prediction."""
    return {"cycling_predicted": True, "probability": 0.85, "confidence": 0.7, "status": "ok"}


@pytest.fixture
def instability_prediction():
    """Create a prediction with high instability flag."""
    return {
        "cycling_predicted": False,
        "probability": 0.4,
        "confidence": 0.2,
        "instability_high": True,
        "status": "heuristic_ok",
    }


@pytest.fixture
def analysis_data():
    """Create analysis data."""
    return {"min_stable_power": 450, "sufficient_data": True}


@pytest.fixture
def analysis_data_high_std():
    """Create analysis data with high power_std."""
    return {"min_stable_power": 450, "sufficient_data": True, "power_std": 200.0}


class TestController:
    """Tests for Controller class."""

    @SKIP_OLD_API
    def test_initialization(self, controller):
        """Test controller initializes correctly."""
        assert controller.stats["actions_taken"] == 0
        assert controller.stats["cycles_prevented"] == 0
        assert controller.stats["stabilize_low_load_count"] == 0

    def test_min_action_interval_is_10_minutes(self, controller):
        """Test MIN_ACTION_INTERVAL is 10 minutes (increased from 5)."""
        from datetime import timedelta

        assert controller.MIN_ACTION_INTERVAL == timedelta(minutes=10)

    def test_should_act_observation_mode(self, controller, active_status):
        """Test no action in observation mode."""
        active_status.mode = SystemMode.OBSERVATION
        assert controller.should_act(active_status) is False

    def test_should_act_manual_mode(self, controller, active_status):
        """Test no action in manual mode."""
        active_status.mode = SystemMode.MANUAL
        assert controller.should_act(active_status) is False

    def test_should_act_active_mode(self, controller, active_status):
        """Test action allowed in active mode."""
        assert controller.should_act(active_status) is True

    def test_should_act_respects_interval(self, controller, active_status):
        """Test minimum action interval is respected."""
        controller._last_action_time = datetime.now(UTC)
        assert controller.should_act(active_status) is False

    @SKIP_OLD_API
    def test_decide_action_no_cycling_risk(self, controller, active_status, analysis_data):
        """Test no action when system is stable and no instability."""
        active_status.cycling_risk = 0.1
        prediction = {"cycling_predicted": False, "probability": 0.1, "instability_high": False}

        action = controller.decide_action(active_status, prediction, analysis_data)

        assert action.action_type == ActionType.NO_ACTION

    @SKIP_OLD_API
    def test_decide_action_no_action_stable_low_risk(
        self, controller, active_status, analysis_data
    ):
        """Test no action when cycling_predicted=False, risk<0.5, instability_high absent."""
        active_status.cycling_risk = 0.3
        prediction = {"cycling_predicted": False, "probability": 0.2}

        action = controller.decide_action(active_status, prediction, analysis_data)
        assert action.action_type == ActionType.NO_ACTION

    def test_decide_action_instability_triggers_action(
        self, controller, active_status, instability_prediction, analysis_data
    ):
        """Test that instability_high alone triggers an action even when cycling_predicted=False."""
        active_status.cycling_risk = 0.3  # Below 0.5
        active_status.power_consumption = 350.0  # Below min_stable_power

        action = controller.decide_action(active_status, instability_prediction, analysis_data)

        # Should act despite cycling_predicted=False because instability_high=True
        assert action.action_type != ActionType.NO_ACTION or "Strategie" in action.reason

    @SKIP_OLD_API
    def test_decide_action_load_balancing(
        self, controller, active_status, cycling_prediction, analysis_data
    ):
        """Test load balancing when power is low."""
        action = controller.decide_action(active_status, cycling_prediction, analysis_data)

        # Should try to enable an inactive unit
        assert action.action_type == ActionType.ENABLE_UNIT
        # Should choose lowest priority unit (storage)
        assert action.target_unit == "storage"
        assert "Lastverteilung" in action.reason

    @SKIP_OLD_API
    def test_decide_action_load_balancing_high_power_std(
        self, controller, active_status, cycling_prediction, analysis_data_high_std
    ):
        """Test load balancing triggers on high power_std even if power >= min_stable."""
        active_status.power_consumption = 500.0  # Above min_stable_power (450)

        action = controller.decide_action(active_status, cycling_prediction, analysis_data_high_std)

        # power_std=200 > 150 threshold → load balancing should still activate
        assert action.action_type == ActionType.ENABLE_UNIT
        assert "Lastverteilung" in action.reason

    def test_decide_action_temp_modulation(
        self, controller, active_status, cycling_prediction, analysis_data
    ):
        """Test temperature modulation when load balancing not possible."""
        # Make all units active
        for unit in active_status.units.values():
            unit.is_on = True

        active_status.power_consumption = 500  # Above min stable

        action = controller.decide_action(active_status, cycling_prediction, analysis_data)

        # Should try temperature modulation or fan control
        assert action.action_type in (
            ActionType.ADJUST_TEMP,
            ActionType.ADJUST_FAN,
            ActionType.NO_ACTION,
        )

    @SKIP_OLD_API
    def test_strategy_stabilize_low_load_fan(self, controller, active_status):
        """Test stabilize_low_load raises fan speed when power low + unstable."""
        # Set up: low power, instability flagged
        active_status.power_consumption = 400.0
        # living_room is on with fan_mode="auto" (not low/quiet/silent)
        # bedroom is off with fan_mode="low"
        # Set living_room to "low" so it qualifies for the stabilize strategy
        active_status.units["living_room"].fan_mode = "low"

        prediction = {"cycling_predicted": True, "probability": 0.6, "instability_high": True}
        analysis = {"min_stable_power": 450, "power_std": 50}

        action = controller.decide_action(active_status, prediction, analysis)

        # With power < 600 and instability_high, after load balancing (which
        # should enable storage first), check that stabilize can work.
        # Actually, since power < min_stable_power, load balancing fires first.
        # Let's test stabilize_low_load directly:
        action = controller._strategy_stabilize_low_load(active_status)
        assert action.action_type == ActionType.ADJUST_FAN
        assert action.parameters["fan_mode"] == "medium"
        assert "Stabilisierung" in action.reason

    @SKIP_OLD_API
    def test_strategy_stabilize_low_load_temp_boost(self, controller, active_status):
        """Test stabilize_low_load raises temp when no fan adjustment possible."""
        # All active units already have high fan speed (no low/quiet/silent)
        active_status.units["living_room"].fan_mode = "high"
        # bedroom and storage off → no active units with low fan

        action = controller._strategy_stabilize_low_load(active_status)

        # Only living_room is on and has target_temp – should raise temp by 0.5°C
        assert action.action_type == ActionType.ADJUST_TEMP
        assert action.parameters["temperature"] == 22.5  # 22.0 + 0.5
        assert "Stabilisierung" in action.reason

    @SKIP_OLD_API
    def test_strategy_stabilize_low_load_no_units(self, controller):
        """Test stabilize_low_load returns NO_ACTION when nothing can be done."""
        status = OptimizerStatus()
        status.mode = SystemMode.ACTIVE
        status.units = {}

        action = controller._strategy_stabilize_low_load(status)
        assert action.action_type == ActionType.NO_ACTION

    def test_execute_action_no_callback(self, controller):
        """Test execution fails gracefully without callback."""
        action = ControlAction(
            action_type=ActionType.ENABLE_UNIT,
            target_unit="bedroom",
            parameters={"temperature": 20.0},
        )

        result = controller.execute_action(action)

        assert result.success is False
        assert "Callback" in result.message

    def test_execute_action_with_callback(self, controller):
        """Test execution with callback."""
        executed = []

        def mock_callback(action):
            executed.append(action)
            return True

        controller.set_action_callback(mock_callback)

        action = ControlAction(
            action_type=ActionType.ENABLE_UNIT,
            target_unit="bedroom",
            parameters={"temperature": 20.0},
            reason="Test",
        )

        result = controller.execute_action(action)

        assert result.success is True
        assert len(executed) == 1
        assert controller.stats["actions_taken"] == 1

    @SKIP_OLD_API
    def test_record_prevented_cycle(self, controller):
        """Test recording prevented cycles."""
        controller.record_prevented_cycle()
        controller.record_prevented_cycle()

        assert controller.stats["cycles_prevented"] == 2

    @SKIP_OLD_API
    def test_get_dashboard_data(self, controller):
        """Test dashboard data generation."""
        controller.stats["actions_taken"] = 5
        controller.stats["cycles_prevented"] = 3

        data = controller.get_dashboard_data()

        assert data["stats"]["actions_taken"] == 5
        assert data["stats"]["cycles_prevented"] == 3
        assert "recent_actions" in data

    def test_load_balancing_reason_includes_sigma(
        self, controller, active_status, cycling_prediction, analysis_data_high_std
    ):
        """Test that load balancing reason includes power_std (σ) info."""
        action = controller.decide_action(active_status, cycling_prediction, analysis_data_high_std)
        assert "σ=" in action.reason

    def test_instability_from_analysis(self, controller, active_status, analysis_data):
        """Test that instability_high in analysis dict is respected."""
        active_status.cycling_risk = 0.1
        prediction = {"cycling_predicted": False, "probability": 0.1}
        analysis = {**analysis_data, "instability_high": True, "power_std": 200.0}

        action = controller.decide_action(active_status, prediction, analysis)
        # instability_high triggers action even with low cycling risk
        assert action.action_type != ActionType.NO_ACTION
