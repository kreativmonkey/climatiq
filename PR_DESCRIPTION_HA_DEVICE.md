# Add Home Assistant Device with Sensor Entities

## Overview

This PR adds a Home Assistant device with 12 sensor entities to provide comprehensive visibility into ClimatIQ's operation.

## Changes

### New Features

1. **Home Assistant Device**: "ClimatIQ Controller"
   - Appears in Home Assistant device registry
   - Groups all ClimatIQ sensors together
   - Provides device metadata (manufacturer, model, version)

2. **12 Sensor Entities**:

   **System Metrics** (4):
   - `sensor.climatiq_power` - Current power level (W)
   - `sensor.climatiq_outdoor_temp` - Outdoor temperature (°C)
   - `sensor.climatiq_total_delta` - Total room delta (K)
   - `sensor.climatiq_stability_state` - System state (stable/unstable/transition)

   **Performance Metrics** (4):
   - `sensor.climatiq_cycles_today` - Compressor cycles today
   - `sensor.climatiq_actions_today` - Controller actions today
   - `sensor.climatiq_last_reward` - Last reward value
   - `sensor.climatiq_compressor_runtime` - Runtime % today

   **Status Metrics** (4):
   - `sensor.climatiq_emergency_active` - Emergency override active (binary)
   - `sensor.climatiq_cooldown_active` - Cooldown active (binary)
   - `sensor.climatiq_active_rooms` - Number of active rooms
   - `sensor.climatiq_critical_room` - Room with highest delta

### Implementation Details

- **Device creation**: `_create_device_sensors()` method called in `initialize()`
- **Sensor updates**: `_update_device_sensors()` method called in every `control_cycle()`
- **State tracking**: Daily counters for cycles, actions, and runtime
- **Stability detection**: Power-based state classification (stable/unstable/transition)
- **Critical room detection**: Tracks room with highest temperature deviation

### Code Quality

- ✅ All code in English (comments, variables, function names)
- ✅ Black formatting applied
- ✅ Ruff linting passed
- ✅ 10 unit tests added (all passing)

### Documentation

Updated `docs/APPDAEMON_SETUP.md` with:
- Complete sensor list with descriptions
- Example dashboard card configuration
- Example automation using emergency sensor
- Usage examples in German (matching existing docs)

### Testing

New test file: `tests/unit/test_device_sensors.py`

Tests cover:
- Device creation with correct attributes
- Sensor value updates
- Stability state detection (stable/unstable/transition)
- Critical room detection
- Active rooms count
- Emergency status
- Actions counter
- Compressor cycle detection

All tests pass: `pytest tests/unit/test_device_sensors.py -v`

## Benefits

1. **Better Visibility**: Users can see ClimatIQ metrics directly in Home Assistant UI
2. **Dashboard Integration**: Easy to add sensors to existing dashboards
3. **Automation Support**: Sensors can trigger automations (e.g., emergency alerts)
4. **Performance Tracking**: Daily counters help track system behavior
5. **Debugging**: Status sensors help diagnose issues

## Usage Example

After merging, users will automatically get the device and sensors on next AppDaemon restart.

**Dashboard Card**:
```yaml
type: entities
title: ClimatIQ System
entities:
  - sensor.climatiq_power
  - sensor.climatiq_outdoor_temp
  - sensor.climatiq_total_delta
  - sensor.climatiq_stability_state
  - sensor.climatiq_cycles_today
  - sensor.climatiq_actions_today
  - sensor.climatiq_emergency_active
  - sensor.climatiq_critical_room
```

**Emergency Alert Automation**:
```yaml
automation:
  - alias: "ClimatIQ Emergency Alert"
    trigger:
      - platform: state
        entity_id: sensor.climatiq_emergency_active
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          message: "ClimatIQ Emergency! Delta: {{ states('sensor.climatiq_total_delta') }}K"
```

## Breaking Changes

None. This is a purely additive feature.

## Related Issues

Closes #[issue-number] (if applicable)

## Checklist

- [x] Code follows project style (Black + Ruff)
- [x] Tests added and passing
- [x] Documentation updated
- [x] All code in English
- [x] Commit message follows conventional commits format
- [x] No breaking changes

## Screenshots

*(Note: Screenshots would show the device in Home Assistant UI and example dashboard)*

---

**PR URL**: https://github.com/kreativmonkey/climatiq/pull/new/feat/ha-device-sensors
