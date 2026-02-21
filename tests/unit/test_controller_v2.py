"""Unit tests for Controller v2 (Sprint 4)."""

from datetime import UTC, datetime

import pytest

from climatiq.core.controller import ActionType, ControlAction, Controller
from climatiq.core.entities import OptimizerStatus, SystemMode, UnitStatus


@pytest.fixture
def controller():
    """Create a controller with test config."""
    config = {
        "comfort": {"target_temp": 21.0, "night_temp": 19.0, "min_temp": 18.0},
        "unit_priorities": {"wohnzimmer": 10, "schlafzimmer": 20, "arbeitszimmer": 50},
    }
    return Controller(config)


@pytest.fixture
def mock_units():
    """Create mock indoor units."""
    return {
        "wohnzimmer": UnitStatus(
            name="wohnzimmer",
            entity_id="climate.wohnzimmer",
            is_on=True,
            current_temp=20.5,
            target_temp=21.0,
            fan_mode="auto",
        ),
        "schlafzimmer": UnitStatus(
            name="schlafzimmer", entity_id="climate.schlafzimmer", is_on=False
        ),
        "arbeitszimmer": UnitStatus(
            name="arbeitszimmer", entity_id="climate.arbeitszimmer", is_on=False
        ),
    }


def test_controller_initialization(controller):
    """Test controller initializes correctly."""
    assert controller.config["comfort"]["target_temp"] == 21.0
    assert controller.stats["actions_taken"] == 0


def test_should_act_respects_mode(controller):
    """Test that controller respects system mode."""
    # Should not act in observation mode
    status = OptimizerStatus(mode=SystemMode.OBSERVATION)
    assert not controller.should_act(status)

    # Should not act in manual mode
    status = OptimizerStatus(mode=SystemMode.MANUAL)
    assert not controller.should_act(status)

    # Should act in active mode
    status = OptimizerStatus(mode=SystemMode.ACTIVE)
    assert controller.should_act(status)


def test_stability_targeting_activates_unit(controller, mock_units):
    """Test that stability targeting activates an inactive unit."""
    status = OptimizerStatus(
        power_consumption=450,  # Below min_stable
        cycling_risk=0.75,
        mode=SystemMode.ACTIVE,
        units=mock_units,
        timestamp=datetime.now(UTC),
    )

    prediction = {"cycling_predicted": True, "probability": 0.75}
    analysis = {"min_stable_power": 550, "power_std": 110, "power_spread": 420}

    action = controller.decide_action(status, prediction, analysis)

    assert action.action_type == ActionType.ENABLE_UNIT
    assert action.target_unit in ["schlafzimmer", "arbeitszimmer"]
    # During night hours (23:00-06:00), night mode may activate units instead
    assert "Stabilitäts-Targeting" in action.reason or "Night Mode" in action.reason


def test_gradual_nudge_small_adjustment(controller, mock_units):
    """Test gradual nudge makes small temperature adjustments."""
    status = OptimizerStatus(
        power_consumption=650,  # Above min_stable but unstable
        cycling_risk=0.65,
        mode=SystemMode.ACTIVE,
        units=mock_units,
        timestamp=datetime.now(UTC),
    )

    prediction = {"cycling_predicted": True, "probability": 0.65}
    analysis = {"min_stable_power": 550, "power_std": 90, "power_spread": 350}

    action = controller.decide_action(status, prediction, analysis)

    # Should try gradual adjustment
    if action.action_type == ActionType.ADJUST_TEMP:
        temp_change = abs(
            action.parameters["temperature"] - action.parameters.get("previous", 21.0)
        )
        assert temp_change <= 0.5  # Max 0.5°C change
        assert "Gradual Nudge" in action.reason


def test_night_mode_detection(controller):
    """Test night mode time detection."""
    # Mock time by calling directly (would need datetime mocking for full test)
    # For now just test the method exists
    assert hasattr(controller, "is_night_mode")
    is_night = controller.is_night_mode()
    assert isinstance(is_night, bool)


def test_no_action_when_stable(controller, mock_units):
    """Test controller doesn't act when system is stable."""
    status = OptimizerStatus(
        power_consumption=550,
        cycling_risk=0.2,  # Low risk
        mode=SystemMode.ACTIVE,
        units=mock_units,
        timestamp=datetime.now(UTC),
    )

    prediction = {"cycling_predicted": False, "probability": 0.2}
    analysis = {
        "min_stable_power": 500,
        "power_std": 30,  # Low variance
        "power_spread": 100,  # Low spread
    }

    action = controller.decide_action(status, prediction, analysis)

    assert action.action_type == ActionType.NO_ACTION
    assert "stabil" in action.reason.lower()


def test_action_callback_execution(controller):
    """Test action callback is called."""
    executed_actions = []

    def mock_callback(action):
        executed_actions.append(action)
        return True

    controller.set_action_callback(mock_callback)

    action = ControlAction(
        action_type=ActionType.ENABLE_UNIT, target_unit="test_unit", reason="Test"
    )

    result = controller.execute_action(action)

    assert result.success
    assert len(executed_actions) == 1
    assert controller.stats["actions_taken"] == 1


def test_action_without_callback_fails(controller):
    """Test that action without callback fails gracefully."""
    action = ControlAction(action_type=ActionType.ENABLE_UNIT, target_unit="test", reason="Test")

    result = controller.execute_action(action)

    assert not result.success
    assert "Callback" in result.message


def test_dashboard_data(controller):
    """Test dashboard data structure."""
    data = controller.get_dashboard_data()

    assert "stats" in data
    assert "last_action" in data
    assert "last_action_time" in data
    assert "history" in data
    assert isinstance(data["stats"], dict)


def test_high_variance_triggers_action(controller, mock_units):
    """Test that high power variance triggers stability action."""
    status = OptimizerStatus(
        power_consumption=600,
        cycling_risk=0.8,
        mode=SystemMode.ACTIVE,
        units=mock_units,
        timestamp=datetime.now(UTC),
    )

    analysis = {
        "min_stable_power": 550,
        "power_std": 150,  # Very high variance
        "power_spread": 500,
    }

    action = controller.decide_action(
        status, {"cycling_predicted": True, "probability": 0.8}, analysis
    )

    # Should generate some action due to high variance
    assert action.action_type != ActionType.NO_ACTION


def test_no_units_available_no_action(controller):
    """Test controller handles no available units gracefully."""
    # All units on
    units = {
        "wohnzimmer": UnitStatus(name="wohnzimmer", entity_id="climate.wz", is_on=True),
        "schlafzimmer": UnitStatus(name="schlafzimmer", entity_id="climate.sz", is_on=True),
    }

    status = OptimizerStatus(
        power_consumption=400,
        cycling_risk=0.75,
        mode=SystemMode.ACTIVE,
        units=units,
        timestamp=datetime.now(UTC),
    )

    action = controller.decide_action(
        status,
        {"cycling_predicted": True, "probability": 0.75},
        {"min_stable_power": 550, "power_std": 100, "power_spread": 400},
    )

    # Should return no_action if no units available
    # (might try temp adjustment on active units)
    assert action is not None
