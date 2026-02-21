# Multi-Device Support

**Version:** 3.1+  
**Status:** Stable

## Overview

ClimatIQ v3.1 introduces support for **multiple outdoor units**, each with independent operating modes and power sensors. This enables:

- ✅ Simultaneous heating and cooling in different zones
- ✅ Per-unit power monitoring and optimization
- ✅ Intelligent room on/off control based on operating mode
- ✅ Mixed-mode validation (heat+cool forbidden within same unit)
- ✅ 100% backward compatible with single-unit configs

## Why Multi-Device?

### Scenario: Multi-Story Building

**Before (Single Unit):**
- One outdoor unit serves all rooms
- All rooms must use same mode (heat **or** cool)
- No per-floor climate control

**After (Multi-Device):**
- Ground floor: Outdoor Unit 1 (heat mode)
- Upper floor: Outdoor Unit 2 (cool mode)
- Independent control and power monitoring
- Night-mode optimization per zone

### Benefits

1. **Mixed Modes:** Ground floor heating while upstairs cooling
2. **Power Accuracy:** Separate sensors = better optimization
3. **Zone Isolation:** Problems in one unit don't affect others
4. **Scalability:** Support for 2+ outdoor units

## Configuration

### Simple Config (Single Unit - Backward Compatible)

```yaml
climatiq_controller:
  module: climatiq_controller
  class: ClimatIQController
  
  # Global operating mode (applies to all rooms)
  controller:
    operating_mode: "heat"  # or "cool"
  
  sensors:
    power: sensor.ac_current_energy  # Single power sensor
    outdoor_temp: sensor.ac_temperatur_outdoor
  
  rooms:
    erdgeschoss:
      # outdoor_unit: default (implicit)
      temp_sensor: sensor.temperatur_wohnzimmer
      climate_entity: climate.panasonic_climate_erdgeschoss
    
    schlafzimmer:
      temp_sensor: sensor.temperatur_flur_og
      climate_entity: climate.panasonic_climate_schlafzimmer
  
  rules:
    comfort:
      temp_tolerance_cold: 1.5
      temp_tolerance_warm: 1.0
    adjustments:
      target_step: 0.5
      target_min: 16.0
      target_max: 24.0
    hysteresis:
      min_action_interval_minutes: 15
    stability:
      max_actions_per_cycle: 2
```

### Advanced Config (Multiple Units)

```yaml
climatiq_controller:
  module: climatiq_controller
  class: ClimatIQController
  
  # Define outdoor units with independent modes
  outdoor_units:
    unit_1:
      operating_mode: "heat"
      power_sensor: sensor.ac_unit1_power
    
    unit_2:
      operating_mode: "cool"
      power_sensor: sensor.ac_unit2_power
  
  sensors:
    outdoor_temp: sensor.ac_temperatur_outdoor
  
  # Explicitly assign rooms to units
  rooms:
    erdgeschoss:
      outdoor_unit: unit_1  # Heating zone
      temp_sensor: sensor.temperatur_wohnzimmer
      climate_entity: climate.panasonic_climate_erdgeschoss
    
    kinderzimmer:
      outdoor_unit: unit_2  # Cooling zone
      temp_sensor: sensor.temp_kinderzimmer
      climate_entity: climate.panasonic_climate_kinderzimmer
    
    schlafzimmer:
      outdoor_unit: unit_1  # Also heating
      temp_sensor: sensor.temp_schlafzimmer
      climate_entity: climate.panasonic_climate_schlafzimmer
  
  rules:
    comfort:
      temp_tolerance_cold: 1.5
      temp_tolerance_warm: 1.0
    adjustments:
      target_step: 0.5
      target_min: 16.0
      target_max: 24.0
    hysteresis:
      min_action_interval_minutes: 15
    stability:
      max_actions_per_cycle: 2
```

## Operating Modes

### Per-Unit Modes

Each outdoor unit has **one** operating mode:

- **`heat`**: All rooms on this unit will heat
- **`cool`**: All rooms on this unit will cool

### Mixed-Mode Rules

**✅ ALLOWED:** Different modes across units
```yaml
outdoor_units:
  unit_1:
    operating_mode: "heat"  # Ground floor heats
  unit_2:
    operating_mode: "cool"  # Upstairs cools
```

**❌ FORBIDDEN:** Mixed modes within same unit
```yaml
# This configuration is INVALID:
outdoor_units:
  unit_1:
    operating_mode: "heat"

rooms:
  room_a:
    outdoor_unit: unit_1
    # Cannot have room_a heating AND room_b cooling on same unit
```

All rooms assigned to `unit_1` will operate in `heat` mode.

### Mode Validation

On startup, ClimatIQ validates that:

1. Each outdoor unit has exactly one `operating_mode`
2. All rooms are assigned to a valid unit
3. Each unit has a `power_sensor` (multi-device mode)

Warnings are logged for inconsistencies.

## Room Control

### On/Off Control

ClimatIQ v3.1 introduces **automatic room on/off control**:

#### `turn_room_off(room)`
**Always safe** - Turns HVAC off regardless of operating mode.

**Triggered by:**
- **Night mode** (23:00-06:00): Turns off rooms with delta ≥ -0.5K
- **Overheating:** Room is >2K above target (heat mode only)
- **Manual decision:** Low priority rooms during instability

```python
# Example: Night mode
if is_night_mode and room_delta >= -0.5:
    turn_room_off("erdgeschoss")
```

#### `turn_room_on(room)`
**Mode-aware** - Uses outdoor unit's `operating_mode`.

**Triggered by:**
- **Too cold:** Room is <-1.5K below target
- **Stability targeting:** Total power <500W
- **Comfort restoration:** After night mode ends

```python
# Example: Too cold
if room_delta < -1.5 and not room_is_on:
    turn_room_on("erdgeschoss")  # Uses unit_1's mode (heat)
```

**Implementation:**
```python
def turn_room_on(self, room: str):
    unit_id, unit_cfg = self.get_outdoor_unit_for_room(room)
    operating_mode = unit_cfg["operating_mode"]
    
    hvac_mode = "heat" if operating_mode == "heat" else "cool"
    
    self.call_service(
        "climate/set_hvac_mode",
        entity_id=room_entity,
        hvac_mode=hvac_mode
    )
```

### Target Adjustment

For **fine-tuning** when room is already on:

```python
if room_is_on and delta < -1.5:
    adjust_target(room, target + 0.5)
```

## Power Aggregation

### Single Unit
Uses global `sensors.power`:

```yaml
sensors:
  power: sensor.ac_current_energy
```

### Multiple Units
Sums all unit `power_sensor` values:

```yaml
outdoor_units:
  unit_1:
    power_sensor: sensor.ac_unit1_power  # 800W
  unit_2:
    power_sensor: sensor.ac_unit2_power  # 600W

# Total power: 1400W
```

**Implementation:**
```python
def get_total_power(self) -> float:
    if len(self.outdoor_units) == 1:
        # Use single power sensor
        return float(self.get_state(unit["power_sensor"]))
    
    # Aggregate across units
    total = 0.0
    for unit_id, unit_cfg in self.outdoor_units.items():
        total += float(self.get_state(unit_cfg["power_sensor"]))
    
    return total
```

## Decision Logic

### Priority Order

ClimatIQ evaluates actions in this order:

1. **Night Mode** (23:00-06:00)
   - Turn off rooms with delta ≥ -0.5K
   - Reduces unnecessary heating/cooling

2. **Overheating Prevention**
   - If room >2K above target → turn off
   - Prevents energy waste

3. **Too Cold**
   - If room <-1.5K below target:
     - If off → turn on
     - If on → increase target

4. **Too Warm**
   - If room >+1.0K above target:
     - If on → decrease target

5. **Stability Targeting**
   - If total power <500W → turn on lowest-priority off room

### Example Decision Flow

**State:**
- Time: 02:30 (night mode)
- Room: erdgeschoss
- Current: 20.5°C, Target: 21.0°C
- Delta: -0.5K
- HVAC: On (heat mode)

**Decision:**
```python
# Night mode + acceptable temp → turn off
action = {
    "action_type": "turn_off",
    "room": "erdgeschoss",
    "reason": "Night mode (Δ=-0.5K, ok to turn off)"
}
```

**State:**
- Time: 14:00 (daytime)
- Room: kinderzimmer
- Current: 18.0°C, Target: 21.0°C
- Delta: -3.0K
- HVAC: Off

**Decision:**
```python
# Too cold + room off → turn on
action = {
    "action_type": "turn_on",
    "room": "kinderzimmer",
    "unit_id": "unit_1",
    "reason": "Too cold (-3.0K), unit=unit_1"
}
```

## Home Assistant Integration

### Entities Created

ClimatIQ creates the following entities:

#### Per Outdoor Unit
```yaml
select.climatiq_operating_mode_unit_1:
  options: ["heat", "cool"]
  current: "heat"

select.climatiq_operating_mode_unit_2:
  options: ["heat", "cool"]
  current: "cool"
```

#### Global
```yaml
sensor.climatiq_power_total:
  unit: "W"
  value: 1400  # Aggregated across all units

sensor.climatiq_cycles_today:
  unit: "count"
  value: 12

sensor.climatiq_last_action:
  value: "turn_on erdgeschoss (Too cold)"

binary_sensor.climatiq_night_mode:
  state: "off"  # on = 23:00-06:00
```

### Device Info

All entities are grouped under one device:

```python
device_info = {
    "identifiers": {("climatiq", "controller")},
    "name": "ClimatIQ Controller",
    "manufacturer": "ClimatIQ",
    "model": "v3.1",
}
```

## Migration Guide

### From Single to Multi-Device

**Step 1:** Identify your outdoor units and their power sensors

```bash
# Find power sensors in Home Assistant
# Developer Tools → States → search for "power"
sensor.ac_unit1_power
sensor.ac_unit2_power
```

**Step 2:** Update config

**Before:**
```yaml
controller:
  operating_mode: "heat"

sensors:
  power: sensor.ac_current_energy
```

**After:**
```yaml
outdoor_units:
  unit_1:
    operating_mode: "heat"
    power_sensor: sensor.ac_unit1_power
  
  unit_2:
    operating_mode: "cool"
    power_sensor: sensor.ac_unit2_power

# Remove global sensors.power
```

**Step 3:** Assign rooms to units

```yaml
rooms:
  erdgeschoss:
    outdoor_unit: unit_1  # Add this line
    temp_sensor: sensor.temperatur_wohnzimmer
    climate_entity: climate.panasonic_climate_erdgeschoss
```

**Step 4:** Restart AppDaemon

```bash
# Reload AppDaemon
docker exec -it appdaemon appdaemon -c /config
```

**Step 5:** Verify logs

Check AppDaemon logs for:

```
=== ClimatIQ Controller V3 (Multi-Device) ===
Outdoor units configured: 2
  - unit_1: mode=heat
  - unit_2: mode=cool
Controller started (Interval: 5min, Rooms: [...])
```

### Rollback to Single Unit

If you need to revert:

1. Remove `outdoor_units` section
2. Re-add `controller.operating_mode`
3. Re-add `sensors.power`
4. Remove `outdoor_unit` from room configs

Your old config will work unchanged!

## Troubleshooting

### Issue: Room not turning on

**Check:**
1. Is room assigned to a valid unit?
   ```yaml
   rooms:
     my_room:
       outdoor_unit: unit_1  # Must exist in outdoor_units
   ```

2. Does unit have correct operating_mode?
   ```bash
   # Check logs for:
   "Unit unit_1: mode=heat"
   ```

3. Is cooldown active?
   ```
   # Default: 15 minutes between actions per room
   min_action_interval_minutes: 15
   ```

### Issue: Power aggregation incorrect

**Check:**
1. Each unit has `power_sensor` defined
2. All sensors are available in Home Assistant
   ```bash
   # Developer Tools → States
   sensor.ac_unit1_power: "800"
   sensor.ac_unit2_power: "600"
   ```

3. Check logs for warnings:
   ```
   WARNING: Unit unit_2 power unavailable
   ```

### Issue: Mixed mode validation failed

**Check:**
1. Each outdoor unit has exactly one `operating_mode`
2. No rooms override the unit's mode (not supported)

**Valid:**
```yaml
outdoor_units:
  unit_1:
    operating_mode: "heat"
  unit_2:
    operating_mode: "cool"
```

**Invalid:**
```yaml
outdoor_units:
  unit_1:
    operating_mode: "heat"
    
# Cannot have room on unit_1 using cool mode
```

## Performance

### Resource Usage

- **Memory:** ~50MB (includes sklearn for GMM)
- **CPU:** <5% during control cycle
- **Storage:** RL logs grow ~1MB/day

### Scalability

Tested with:
- ✅ 2 outdoor units, 5 rooms
- ✅ 3 outdoor units, 8 rooms
- ✅ Single unit, 10 rooms (backward compatible)

**Limits:**
- Max outdoor units: 10 (theoretical, not tested)
- Max rooms per unit: Unlimited
- Control cycle interval: 5 minutes recommended

## Advanced Features

### Custom Night Mode Schedule

Modify `decide_actions()` to customize night mode:

```python
# Default: 23:00 - 06:00
current_hour = datetime.now().hour
is_night_mode = 23 <= current_hour or current_hour < 6

# Custom: 22:00 - 07:00
is_night_mode = 22 <= current_hour or current_hour < 7
```

### Priority-Based Room Selection

For stability targeting, rooms are selected by:

1. Largest negative delta (coldest first)
2. Lowest target temp
3. Alphabetical order

Customize in `decide_actions()`:

```python
# Example: Prioritize specific rooms
priority_rooms = ["erdgeschoss", "schlafzimmer"]
if room in priority_rooms:
    priority_score += 10
```

### Zone-Specific Rules

Apply different rules per outdoor unit:

```python
def get_rules_for_room(self, room: str) -> dict:
    unit_id, unit_cfg = self.get_outdoor_unit_for_room(room)
    
    if unit_id == "unit_1":
        return self.rules  # Default
    elif unit_id == "unit_2":
        # Custom rules for unit_2
        return {
            "comfort": {"temp_tolerance_cold": 2.0},
            "adjustments": {"target_step": 1.0},
            ...
        }
```

## API Reference

### Methods

#### `parse_outdoor_units() -> dict`
Parse outdoor units from config with backward compatibility.

**Returns:**
```python
{
    "unit_1": {
        "operating_mode": "heat",
        "power_sensor": "sensor.ac_unit1_power"
    },
    "default": {  # Fallback for single-unit configs
        "operating_mode": "heat",
        "power_sensor": "sensor.ac_current_energy"
    }
}
```

#### `get_outdoor_unit_for_room(room: str) -> tuple[str, dict]`
Get outdoor unit config for room.

**Returns:**
```python
("unit_1", {
    "operating_mode": "heat",
    "power_sensor": "sensor.ac_unit1_power"
})
```

#### `get_total_power() -> float`
Aggregate power across all outdoor units.

**Returns:** Total power consumption in watts.

#### `turn_room_off(room: str)`
Turn room HVAC off (always safe).

#### `turn_room_on(room: str)`
Turn room HVAC on using outdoor unit's operating mode.

#### `validate_outdoor_unit_modes() -> bool`
Check configuration validity.

**Returns:** `True` if valid, `False` if mixed modes detected.

## Support

### Reporting Issues

Open an issue on GitHub with:

1. **Config:** Your `climatiq.yaml` (anonymize entity names)
2. **Logs:** Last 50 lines of AppDaemon logs
3. **Version:** ClimatIQ version (`git describe --tags`)
4. **Expected vs Actual:** What should happen vs what happens

### Community

- **GitHub:** https://github.com/kreativmonkey/climatiq
- **Discussions:** https://github.com/kreativmonkey/climatiq/discussions
- **Wiki:** https://github.com/kreativmonkey/climatiq/wiki

## Changelog

### v3.1.0 (2026-02-21)

#### Added
- ✅ Multi-device support (multiple outdoor units)
- ✅ Room on/off control with mode awareness
- ✅ Power aggregation across units
- ✅ Mixed-mode validation per unit
- ✅ Night mode optimization (23:00-06:00)
- ✅ Overheating prevention (auto turn-off)

#### Changed
- 📝 Config schema extended with `outdoor_units`
- 📝 Backward compatible with old configs

#### Fixed
- 🐛 Single power sensor now properly handled in multi-unit mode

---

**Last updated:** 2026-02-21  
**ClimatIQ Version:** 3.1.0
