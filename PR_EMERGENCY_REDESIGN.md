# Emergency Override Logic Redesign

## Problem

PR #12 and PR #13 implemented **WRONG** emergency logic:

### What was wrong:
- **Current:** `total_delta_abs >= 6.0K` triggers emergency
- **Issue:** 5 rooms × 1.5K each = 7.5K → triggers emergency even though individual rooms are fine
- **Example:** All rooms within comfortable tolerance (+1K each), but total triggers emergency

## Solution

Emergency should be triggered by **TWO SEPARATE conditions**, not total delta:

### 1. 🌡️ Comfort Emergency
**Individual room outside tolerance zone**

```yaml
rules:
  comfort:
    temp_tolerance_cold: 1.5  # delta < -1.5K → too cold
    temp_tolerance_warm: 1.0  # delta > +1.0K → too warm
```

**Behavior:**
- Check EACH room individually (not total)
- If ANY room exceeds tolerance → comfort emergency
- Uses shorter cooldown (7 min vs 15 min)

**Example:**
```
🚨 Comfort Emergency! Room(s) outside tolerance zone
  ❄️ bedroom: Too cold! Delta -1.8K (threshold: -1.5K)
```

### 2. ⚡ Stability Emergency
**Power oscillating/fluctuating in last 15 minutes**

```yaml
rules:
  stability:
    power_std_threshold: 300      # W - Standard deviation threshold
    power_range_threshold: 800    # W - Range (max-min) threshold
```

**Behavior:**
- Queries last 15 minutes of power data from InfluxDB
- Calculates standard deviation and range
- If EITHER threshold exceeded → stability emergency
- **NOT** about being in unstable zone (1000-1500W)
- About **fluctuation**: Is system settling or oscillating?

**Philosophy:**
> "Wenn die steuerung es hin bekommt, das System in einer Instabilen Zone stabil zu betreiben soll mir das egal sein."

**Example:**
```
🚨 Stability Emergency! Power oscillating
  ⚡ Power oscillating: StdDev=370W, Range=900W (mean=1100W, last 15min)
```

## Changes

### Reverted:
- ✅ PR #12 - Emergency override with total delta
- ✅ PR #13 - Emergency cooldown based on flawed logic

### Implemented:
- ✅ `_check_comfort_emergency()` - Per-room tolerance checks
- ✅ `_check_stability_emergency()` - Power fluctuation detection (InfluxDB)
- ✅ Emergency cooldown: 7 minutes (vs 15 normal)
- ✅ Updated tests for new logic
- ✅ Updated documentation

### Config Changes:

**Removed:**
```yaml
emergency_delta_threshold: 6.0  # ❌ DELETE
```

**Added:**
```yaml
hysteresis:
  emergency_action_interval_minutes: 7  # Shorter cooldown in emergencies

stability:
  power_std_threshold: 300      # W - StdDev threshold
  power_range_threshold: 800    # W - Range threshold
```

## Testing

### Code Quality:
```bash
✅ black appdaemon/apps/climatiq_controller.py --check
✅ ruff check appdaemon/apps/climatiq_controller.py
✅ ruff check tests/unit/test_controller_emergency_override.py
```

### Tests Created:
- ✅ Comfort emergency: too cold
- ✅ Comfort emergency: too warm
- ✅ Comfort emergency: within tolerance (no trigger)
- ✅ Comfort emergency: multi-room with one violation
- ✅ Stability emergency: high oscillation
- ✅ Stability emergency: stable power (no trigger)
- ✅ Stability emergency: InfluxDB integration
- ✅ Emergency cooldown: shorter than normal

**Note:** Tests require AppDaemon environment for full execution. Syntax and linting verified.

## Files Changed

- `appdaemon/apps/climatiq_controller.py` - Core logic
- `appdaemon/apps/climatiq.yaml` - Configuration
- `tests/unit/test_controller_emergency_override.py` - New test file
- `docs/CONTROLLER.md` - Documentation

## Breaking Changes

⚠️ **BREAKING:** Emergency logic completely redesigned.

**Migration:**
1. Remove `emergency_delta_threshold` from config
2. Add `emergency_action_interval_minutes` to `hysteresis`
3. Add `power_std_threshold` and `power_range_threshold` to `stability`

**Behavior change:**
- Old: Emergency triggered by high total delta (sum of all room deltas)
- New: Emergency triggered by individual room comfort OR power oscillation

## Expected Outcome

Emergency logic now correctly handles:
1. ✅ **Individual room comfort** (not total delta)
   - 5 rooms at +1K each: NO emergency (within tolerance)
   - 1 room at -1.8K: EMERGENCY (exceeds cold tolerance)

2. ✅ **System oscillation** (not unstable zones)
   - Stable at 1200W (in "unstable zone"): NO emergency
   - Power swinging 500W-1400W: EMERGENCY (high fluctuation)

## References

- Closes discussion about wrong emergency triggers
- User quote: "Wenn die steuerung es hin bekommt, das System in einer Instabilen Zone stabil zu betreiben soll mir das egal sein."
