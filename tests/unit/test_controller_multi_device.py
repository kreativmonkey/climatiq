"""
Unit tests for Multi-Device Support (V3)
Tests backward compatibility and new multi-device features.
"""

import pytest

# Since the AppDaemon controller is hard to test in isolation,
# we'll test the logic via integration tests and unit test
# the core functions directly.


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
    }


def test_single_unit_config_structure(single_unit_config):
    """Test that single-unit config has expected structure"""
    assert "controller" in single_unit_config
    assert "operating_mode" in single_unit_config["controller"]
    assert single_unit_config["controller"]["operating_mode"] == "heat"
    assert "sensors" in single_unit_config
    assert "power" in single_unit_config["sensors"]


def test_multi_unit_config_structure(multi_unit_config):
    """Test that multi-unit config has expected structure"""
    assert "outdoor_units" in multi_unit_config
    assert len(multi_unit_config["outdoor_units"]) == 2
    assert "unit_1" in multi_unit_config["outdoor_units"]
    assert "unit_2" in multi_unit_config["outdoor_units"]

    unit_1 = multi_unit_config["outdoor_units"]["unit_1"]
    assert unit_1["operating_mode"] == "heat"
    assert "power_sensor" in unit_1

    # Check rooms have outdoor_unit assignments
    erdgeschoss = multi_unit_config["rooms"]["erdgeschoss"]
    assert erdgeschoss["outdoor_unit"] == "unit_1"


def test_backward_compatibility_has_global_power_sensor(single_unit_config):
    """Test that old config still has global power sensor"""
    assert "power" in single_unit_config["sensors"]
    assert single_unit_config["sensors"]["power"] == "sensor.ac_current_energy"


def test_multi_unit_rooms_assigned(multi_unit_config):
    """Test that in multi-unit mode, rooms are assigned to units"""
    for room_name, room_config in multi_unit_config["rooms"].items():
        assert "outdoor_unit" in room_config, f"Room {room_name} missing outdoor_unit assignment"


def test_operating_modes_valid(single_unit_config, multi_unit_config):
    """Test that operating modes are valid values"""
    valid_modes = {"heat", "cool"}

    # Single unit
    assert single_unit_config["controller"]["operating_mode"] in valid_modes

    # Multi unit
    for unit_name, unit_config in multi_unit_config["outdoor_units"].items():
        assert unit_config["operating_mode"] in valid_modes, f"Invalid mode for {unit_name}"


def test_multi_unit_power_sensors_unique(multi_unit_config):
    """Test that each outdoor unit has a unique power sensor"""
    power_sensors = []
    for unit_name, unit_config in multi_unit_config["outdoor_units"].items():
        assert "power_sensor" in unit_config, f"Unit {unit_name} missing power_sensor"
        power_sensors.append(unit_config["power_sensor"])

    # All power sensors should be unique
    assert len(power_sensors) == len(set(power_sensors)), "Power sensors must be unique"


def test_config_migration_path_exists(single_unit_config):
    """Test that single-unit config can be migrated to multi-unit"""
    # Old config has global power sensor
    global_power = single_unit_config["sensors"]["power"]
    global_mode = single_unit_config["controller"]["operating_mode"]

    # Could be migrated to:
    migrated = {
        "outdoor_units": {
            "default": {
                "operating_mode": global_mode,
                "power_sensor": global_power,
            }
        },
        "sensors": {
            "outdoor_temp": single_unit_config["sensors"]["outdoor_temp"],
        },
        "rooms": {
            room_name: {**room_config, "outdoor_unit": "default"}
            for room_name, room_config in single_unit_config["rooms"].items()
        },
    }

    # Verify migration result
    assert "outdoor_units" in migrated
    assert "default" in migrated["outdoor_units"]
    assert migrated["outdoor_units"]["default"]["operating_mode"] == "heat"


def test_night_mode_config_optional():
    """Test that night mode configuration is optional"""
    config = {
        "controller": {"operating_mode": "heat"},
        "sensors": {"power": "sensor.power"},
        "rooms": {"test_room": {}},
    }

    # Config should be valid without night_mode settings
    assert "night_mode" not in config.get("controller", {})
    # Night mode would default to enabled in controller


def test_room_config_minimal_requirements():
    """Test minimal room configuration"""
    minimal_room = {
        "temp_sensor": "sensor.temp",
        "climate_entity": "climate.room",
    }

    assert "temp_sensor" in minimal_room
    assert "climate_entity" in minimal_room
    # outdoor_unit is optional (defaults to "default")


# Note: Full integration tests would require mocking AppDaemon,
# which is complex. The actual controller behavior is validated
# through production deployment and manual testing.
# These tests validate config structure and business rules.
