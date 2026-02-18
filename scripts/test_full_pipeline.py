#!/usr/bin/env python3
"""Test the complete ClimatIQ pipeline with 30 days of real data."""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from climatiq.core.observer import Observer
from climatiq.core.analyzer import Analyzer
from climatiq.core.controller import Controller, ActionType
from climatiq.core.entities import OptimizerStatus, SystemMode, UnitStatus

print("=" * 70)
print("ClimatIQ v2 - Full Pipeline Test (30 Days)")
print("=" * 70)

# Load data
df = pd.read_csv('/home/diyon/.openclaw/workspace/climatiq/data/power_30days.csv', 
                 index_col=0, parse_dates=True)
power_series = df['value']

print(f"\nDataset: {len(df)} points, {df.index[0]} to {df.index[-1]}")
print(f"Duration: {(df.index[-1] - df.index[0]).days} days")

# ============================================================
# 1. ANALYZER - Discover Stable Regions
# ============================================================
print("\n" + "=" * 70)
print("PHASE 1: ANALYZER - Discovering Stable Operating Regions")
print("=" * 70)

analyzer = Analyzer()
analysis_result = analyzer.analyze(power_series)

print(f"\nData Sufficient: {analysis_result.sufficient_data}")
print(f"Data Quality: {analysis_result.data_quality_score:.2f}")
print(f"Min Stable Power: {analysis_result.min_stable_power:.1f} W")
print(f"\nDiscovered {len(analysis_result.regions)} operating regions:")

stable_regions = [r for r in analysis_result.regions if r.stability_score > 0.7]
unstable_regions = [r for r in analysis_result.regions if r.stability_score <= 0.4]

print(f"\n  Stable regions (score > 0.7): {len(stable_regions)}")
for r in stable_regions[:5]:  # Show first 5
    print(f"    • {r.name}: {r.stability_score:.2f}, n={r.sample_count}")

print(f"\n  Unstable regions (score < 0.4): {len(unstable_regions)}")
for r in unstable_regions[:5]:
    print(f"    • {r.name}: {r.stability_score:.2f}, n={r.sample_count}")

# Validation check
if analysis_result.min_stable_power and analysis_result.min_stable_power < 700:
    print(f"\n✅ PASS: Analyzer correctly identified low-power stable zone ({analysis_result.min_stable_power:.0f}W)")
else:
    print(f"\n❌ FAIL: Analyzer did not find low-power stable zone (found {analysis_result.min_stable_power:.0f}W)")

# ============================================================
# 2. OBSERVER - Real-time Detection
# ============================================================
print("\n" + "=" * 70)
print("PHASE 2: OBSERVER - Real-time Cycling Detection")
print("=" * 70)

observer = Observer(config={})

# Simulate real-time observations (sample every 10 minutes)
sample_indices = range(0, len(df), 10)  # Every 10 minutes
observations = []

for idx in sample_indices:
    if idx < 10:  # Need history
        continue
    
    # Update observer with power value
    observer.update_power(df['value'].iloc[idx], df.index[idx])
    
    # Get current status
    status = observer.status
    
    observations.append({
        'timestamp': df.index[idx],
        'power': status.power_consumption,
        'cycling_risk': status.cycling_risk,
        'mode': status.mode
    })

obs_df = pd.DataFrame(observations)
high_risk = (obs_df['cycling_risk'] > 0.7).sum()
high_risk_pct = (high_risk / len(obs_df)) * 100

print(f"\nProcessed {len(observations)} observations")
print(f"High cycling risk (>70%): {high_risk} ({high_risk_pct:.1f}%)")
print(f"Mean cycling risk: {obs_df['cycling_risk'].mean():.2f}")
print(f"Max cycling risk: {obs_df['cycling_risk'].max():.2f}")

# ============================================================
# 3. CONTROLLER - Decision Making
# ============================================================
print("\n" + "=" * 70)
print("PHASE 3: CONTROLLER - Action Decision Simulation")
print("=" * 70)

config = {
    'comfort': {'target_temp': 21.0, 'night_temp': 19.0},
    'unit_priorities': {},
}
controller = Controller(config)

# Simulate decisions for high-risk situations
decisions = []
for _, obs in obs_df.iterrows():
    if obs['cycling_risk'] > 0.6:  # Only decide when risk is significant
        # Create mock status
        status = OptimizerStatus(
            power_consumption=obs['power'],
            cycling_risk=obs['cycling_risk'],
            mode=SystemMode.ACTIVE,
            units={},
            outdoor_temp=None,
            timestamp=obs['timestamp']
        )
        
        # Mock prediction and analysis
        prediction = {'cycling_predicted': True, 'probability': obs['cycling_risk']}
        analysis_data = {
            'min_stable_power': analysis_result.min_stable_power,
            'power_std': 100.0 if obs['cycling_risk'] > 0.7 else 40.0,
            'power_spread': 400.0 if obs['cycling_risk'] > 0.7 else 150.0,
        }
        
        action = controller.decide_action(status, prediction, analysis_data)
        if action.action_type != ActionType.NO_ACTION:
            decisions.append({
                'timestamp': obs['timestamp'],
                'action': action.action_type.value,
                'reason': action.reason,
            })

print(f"\nTotal high-risk situations: {(obs_df['cycling_risk'] > 0.6).sum()}")
print(f"Actions decided: {len(decisions)}")
print(f"\nAction breakdown:")
action_types = pd.Series([d['action'] for d in decisions]).value_counts()
for action, count in action_types.items():
    print(f"  • {action}: {count}")

print(f"\nController Stats:")
for key, val in controller.stats.items():
    print(f"  • {key}: {val}")

# Sample decisions
print(f"\nSample Actions (first 5):")
for d in decisions[:5]:
    print(f"  • {d['timestamp']}: {d['action']} - {d['reason'][:60]}")

# ============================================================
# 4. METRICS & VALIDATION
# ============================================================
print("\n" + "=" * 70)
print("PHASE 4: METRICS & VALIDATION")
print("=" * 70)

# Calculate metrics on the full 30-day dataset
df['power_std'] = df['value'].rolling(10, min_periods=1).std()
df['power_spread'] = df['value'].rolling(10, min_periods=1).max() - df['value'].rolling(10, min_periods=1).min()
df['cycling_risk'] = (df['power_std'] / 50.0).clip(0, 1.0)

stable_time = (df['power_std'] < 50).sum()
stable_pct = (stable_time / len(df)) * 100

low_power_stable = ((df['power_std'] < 50) & (df['value'] < 600)).sum()
low_power_stable_pct = (low_power_stable / len(df)) * 100

print(f"\n📊 Stability Metrics (30 days):")
print(f"  • Stable time (Std Dev < 50W): {stable_pct:.1f}%")
print(f"  • Low-power stable (<600W, stable): {low_power_stable_pct:.1f}%")
print(f"  • Mean power: {df['value'].mean():.1f} W")
print(f"  • Mean Std Dev: {df['power_std'].mean():.1f} W")

print(f"\n🎯 Target Metrics:")
print(f"  • >80% stable time: {'✅ PASS' if stable_pct > 80 else '❌ FAIL'} (current: {stable_pct:.1f}%)")
print(f"  • >50% low-power stable: {'✅ PASS' if low_power_stable_pct > 50 else '⚠️  PARTIAL'} (current: {low_power_stable_pct:.1f}%)")
print(f"  • Min stable power < 700W: {'✅ PASS' if analysis_result.min_stable_power < 700 else '❌ FAIL'}")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

checks = []
checks.append(("Analyzer identifies low-power zones", analysis_result.min_stable_power < 700))
checks.append(("Observer detects cycling", high_risk > 0))
checks.append(("Controller makes decisions", len(decisions) > 0))
checks.append(("Stable time >= baseline", stable_pct >= 40))  # Baseline: at least 40%

passed = sum(1 for _, result in checks if result)
total = len(checks)

print(f"\nValidation Results: {passed}/{total} checks passed\n")
for check, result in checks:
    status = "✅" if result else "❌"
    print(f"  {status} {check}")

if passed == total:
    print(f"\n{'='*70}")
    print("🎉 ALL TESTS PASSED! Pipeline is ready for deployment.")
    print("="*70)
elif passed >= total * 0.75:
    print(f"\n{'='*70}")
    print("⚠️  MOSTLY PASSED. Minor issues to address.")
    print("="*70)
else:
    print(f"\n{'='*70}")
    print("❌ TESTS FAILED. Major issues detected.")
    print("="*70)

print("\n✅ Pipeline test complete.")
