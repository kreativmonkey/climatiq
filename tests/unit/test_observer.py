"""Tests for the Observer module."""


import pytest

from hvac_optimizer.core.entities import SystemMode
from hvac_optimizer.core.observer import Observer


@pytest.fixture
def observer():
    """Create an Observer instance with default config."""
    config = {"cycling": {"power_on_threshold": 300, "power_off_threshold": 150}}
    return Observer(config)


class TestObserver:
    """Tests for Observer class."""

    def test_initialization(self, observer):
        """Test observer initializes correctly."""
        assert observer.status.mode == SystemMode.OBSERVATION
        assert observer.status.power_consumption == 0.0
        assert not observer.status.is_cycling
        assert observer.status.cycling_risk == 0.0

    def test_update_power(self, observer):
        """Test power update works."""
        observer.update_power(500.0)
        assert observer.status.power_consumption == 500.0
        assert observer.status.last_update is not None

    def test_update_unit(self, observer):
        """Test unit status update."""
        observer.update_unit(
            "living_room",
            {
                "entity_id": "climate.living_room",
                "is_on": True,
                "current_temp": 21.5,
                "target_temp": 22.0,
                "fan_mode": "auto",
            },
        )

        assert "living_room" in observer.status.units
        unit = observer.status.units["living_room"]
        assert unit.is_on is True
        assert unit.current_temp == 21.5
        assert unit.target_temp == 22.0

    def test_cycling_risk_low_power(self, observer):
        """Test cycling risk increases at low power."""
        # Simulate low power readings
        for i in range(15):
            observer.update_power(250.0)

        # Risk should be elevated at low power
        assert observer.status.cycling_risk > 0.5

    def test_cycling_risk_high_power(self, observer):
        """Test cycling risk is low at high power."""
        for i in range(15):
            observer.update_power(800.0)

        assert observer.status.cycling_risk < 0.3

    def test_get_summary(self, observer):
        """Test summary generation."""
        observer.update_power(500.0)
        observer.update_unit("room1", {"is_on": True, "entity_id": "climate.room1"})

        summary = observer.get_summary()

        assert "mode" in summary
        assert "power" in summary
        assert "active_units" in summary
        assert summary["power"] == 500.0
        assert summary["active_units"] == 1
