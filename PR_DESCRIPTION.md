# fix: Add emergency override for unstable zones with high delta

## 🚨 Production Bug Fix

**Problem:** Controller stops ALL actions when in unstable power zone (1000-1500W), even with critical high temperature delta (9.0K). This prevents the system from correcting the instability.

**Evidence:**
```
Power: 973W | Outdoor: 4.8°C | Δ Total: 9.0K
⚠️ Instabile Zone (973W) - keine Actions
```
Result: System stayed unstable for hours.

## 🔧 Solution: Emergency Override

**Core principle:** Instability prevention should NOT block instability correction!

**Logic:**
- **Normal delta (<6K)** + unstable zone → Wait (as before)
- **Emergency delta (≥6K)** + unstable zone → Override and take action ✅

**New config parameter:**
```yaml
rules:
  stability:
    emergency_delta_threshold: 6.0  # Kelvin
```

## 📝 Changes

- ✅ Add emergency override logic in `control_cycle()`
- ✅ Add `emergency_delta_threshold` config parameter (default 6.0K)
- ✅ Update documentation (CONTROLLER.md, MULTI_DEVICE.md)
- ✅ Add unit tests for emergency logic
- ✅ All code in English (comments, variables)

## ✅ Testing

- Unit tests: `test_controller_emergency_override.py` (6 tests, all passing)
- Manual test scenario: Set delta >6K in unstable zone → Actions executed ✅
- Full test suite: All passing

## 🎯 Impact

- **Before:** System stuck in unstable zone with high delta
- **After:** Emergency situations trigger corrective action

## 📚 Documentation

- CONTROLLER.md: New "Emergency Override" section
- MULTI_DEVICE.md: Note in "Decision Logic"
- Config examples updated

---

Ready for review! This fix ensures the controller can correct unstable situations instead of just avoiding them.
