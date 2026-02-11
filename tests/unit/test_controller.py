"""Tests for the Controller module."""

from datetime import UTC, datetime

import pytest

from climatiq.core.controller import ActionType, ControlAction, Controller
from climatiq.core.entities import OptimizerStatus, SystemMode, UnitStatus


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
def analysis_data():
    """Create analysis data."""
    return {"min_stable_power": 450, "sufficient_data": True}


class TestController:
    """Tests for Controller class."""

    def test_initialization(self, controller):
        """Test controller initializes correctly."""
        assert controller.stats["actions_taken"] == 0
        assert controller.stats["cycles_prevented"] == 0

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

    def test_decide_action_no_cycling_risk(self, controller, active_status, analysis_data):
        """Test no action when system is stable."""
        active_status.cycling_risk = 0.1
        prediction = {"cycling_predicted": False, "probability": 0.1}

        action = controller.decide_action(active_status, prediction, analysis_data)

        assert action.action_type == ActionType.NO_ACTION

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

    def test_decide_action_temp_modulation(
        self, controller, active_status, cycling_prediction, analysis_data
    ):
        """Test temperature modulation when load balancing not possible."""
        # Make all units active
        for unit in active_status.units.values():
            unit.is_on = True

        active_status.power_consumption = 500  # Above min stable

        action = controller.decide_action(active_status, cycling_prediction, analysis_data)

        # Should try temperature modulation
        assert action.action_type in (
            ActionType.ADJUST_TEMP,
            ActionType.ADJUST_FAN,
            ActionType.NO_ACTION,
        )

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

    def test_record_prevented_cycle(self, controller):
        """Test recording prevented cycles."""
        controller.record_prevented_cycle()
        controller.record_prevented_cycle()

        assert controller.stats["cycles_prevented"] == 2

    def test_get_dashboard_data(self, controller):
        """Test dashboard data generation."""
        controller.stats["actions_taken"] = 5
        controller.stats["cycles_prevented"] = 3

        data = controller.get_dashboard_data()

        assert data["stats"]["actions_taken"] == 5
        assert data["stats"]["cycles_prevented"] == 3
        assert "recent_actions" in data
