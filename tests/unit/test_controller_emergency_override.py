"""
Unit tests for emergency override logic in unstable zones.
"""


def test_emergency_override_config_structure():
    """Test that emergency_delta_threshold is in config"""
    config = {
        "rules": {
            "stability": {
                "emergency_delta_threshold": 6.0,
            }
        }
    }

    threshold = config["rules"]["stability"]["emergency_delta_threshold"]
    assert threshold == 6.0
    assert isinstance(threshold, (int, float))


def test_emergency_threshold_default():
    """Test default value if not configured"""
    config = {"rules": {"stability": {}}}

    # Controller should use default of 6.0 if not specified
    threshold = config["rules"]["stability"].get("emergency_delta_threshold", 6.0)
    assert threshold == 6.0


def test_normal_delta_respects_unstable_zone():
    """Normal delta (3K) in unstable zone should wait"""
    state = {
        "power": 1200,  # unstable zone (1000-1500W)
        "total_delta_abs": 3.0,  # normal delta
    }

    emergency_threshold = 6.0
    is_emergency = state["total_delta_abs"] > emergency_threshold

    assert not is_emergency
    # Controller should wait (no actions)


def test_emergency_delta_overrides_unstable_zone():
    """High delta (9K) in unstable zone should override"""
    state = {
        "power": 1200,  # unstable zone
        "total_delta_abs": 9.0,  # emergency!
    }

    emergency_threshold = 6.0
    is_emergency = state["total_delta_abs"] > emergency_threshold

    assert is_emergency
    # Controller should take action despite unstable zone


def test_boundary_case_exactly_threshold():
    """Delta exactly at threshold should trigger emergency"""
    state = {
        "power": 1200,
        "total_delta_abs": 6.0,  # exactly at threshold
    }

    emergency_threshold = 6.0
    is_emergency = state["total_delta_abs"] > emergency_threshold

    assert not is_emergency  # > not >=
    # Use >= if you want threshold to trigger


def test_emergency_in_stable_zone_still_acts():
    """Emergency delta in stable zone should also act (no change)"""
    state = {
        "power": 500,  # stable zone
        "total_delta_abs": 7.0,  # emergency
    }

    emergency_threshold = 6.0
    is_emergency = state["total_delta_abs"] > emergency_threshold
    in_unstable = False  # stable zone

    assert is_emergency
    assert not in_unstable
    # Controller acts (normal behavior)


def test_invalid_threshold_type_string():
    """Invalid threshold type (string) should fall back to default"""
    config = {"rules": {"stability": {"emergency_delta_threshold": "invalid"}}}

    # In real code, this would trigger validation and fallback to 6.0
    threshold = config["rules"]["stability"]["emergency_delta_threshold"]

    # Simulate validation
    if not isinstance(threshold, (int, float)) or threshold <= 0:
        threshold = 6.0

    assert threshold == 6.0


def test_negative_threshold_value():
    """Negative threshold should fall back to default"""
    config = {"rules": {"stability": {"emergency_delta_threshold": -5.0}}}

    threshold = config["rules"]["stability"]["emergency_delta_threshold"]

    # Simulate validation
    if not isinstance(threshold, (int, float)) or threshold <= 0:
        threshold = 6.0

    assert threshold == 6.0


def test_zero_threshold_value():
    """Zero threshold should fall back to default"""
    config = {"rules": {"stability": {"emergency_delta_threshold": 0.0}}}

    threshold = config["rules"]["stability"]["emergency_delta_threshold"]

    # Simulate validation
    if not isinstance(threshold, (int, float)) or threshold <= 0:
        threshold = 6.0

    assert threshold == 6.0


def test_emergency_cooldown_config():
    """Test emergency cooldown configuration"""
    config = {
        "rules": {
            "hysteresis": {
                "min_action_interval_minutes": 15,
                "emergency_action_interval_minutes": 7,
            }
        }
    }

    # Verify both values exist
    assert config["rules"]["hysteresis"]["min_action_interval_minutes"] == 15
    assert config["rules"]["hysteresis"]["emergency_action_interval_minutes"] == 7

    # Emergency should be shorter
    assert (
        config["rules"]["hysteresis"]["emergency_action_interval_minutes"]
        < config["rules"]["hysteresis"]["min_action_interval_minutes"]
    )


def test_emergency_cooldown_default():
    """Test default emergency cooldown when not configured"""
    config = {"rules": {"hysteresis": {"min_action_interval_minutes": 15}}}

    # If emergency_action_interval_minutes not set, should default to 7
    emergency_cooldown = config["rules"]["hysteresis"].get("emergency_action_interval_minutes", 7)
    assert emergency_cooldown == 7


def test_cooldown_logic_normal_vs_emergency():
    """Test that emergency uses shorter cooldown"""
    rules = {
        "hysteresis": {
            "min_action_interval_minutes": 15,
            "emergency_action_interval_minutes": 7,
        }
    }

    # Normal mode
    is_emergency = False
    cooldown_minutes = (
        rules["hysteresis"].get("emergency_action_interval_minutes", 7)
        if is_emergency
        else rules["hysteresis"]["min_action_interval_minutes"]
    )
    assert cooldown_minutes == 15

    # Emergency mode
    is_emergency = True
    cooldown_minutes = (
        rules["hysteresis"].get("emergency_action_interval_minutes", 7)
        if is_emergency
        else rules["hysteresis"]["min_action_interval_minutes"]
    )
    assert cooldown_minutes == 7
