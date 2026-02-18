#!/usr/bin/env python3
"""Optimized pipeline test with sampling for large datasets."""

import pandas as pd
import numpy as np
from climatiq.core.analyzer import Analyzer
from climatiq.core.observer import Observer
from climatiq.core.controller import Controller, ActionType
from climatiq.core.entities import OptimizerStatus, SystemMode

print("="*70)
print("ClimatIQ v2 - Optimized Pipeline Test (30 Days, Sampled)")
print("="*70)

# Load 30-day data
df = pd.read_csv('/home/diyon/.openclaw/workspace/climatiq/data/power_30days.csv', 
                 index_col=0, parse_dates=True)

print(f"\nFull dataset: {len(df)} points ({df.index[0]} to {df.index[-1]})")

# ============================================================
# PHASE 1: ANALYZER (with sampling)
# ============================================================
print("\n" + "="*70)
print("PHASE 1: ANALYZER")
print("="*70)

# Sample every 5th point for faster clustering (still 6k points)
df_sampled = df.iloc[::5].copy()
print(f"Sampled to {len(df_sampled)} points for analysis...")

analyzer = Analyzer()
result = analyzer.analyze(df_sampled['value'])

print(f"\n✓ Analysis complete")
print(f"  Min Stable Power: {result.min_stable_power:.1f} W")
print(f"  Regions discovered: {len(result.regions)}")

stable = [r for r in result.regions if r.stability_score > 0.7]
print(f"  Stable regions: {len(stable)}")
for r in stable[:3]:
    print(f"    • {r.name}")

analyzer_pass = result.min_stable_power and result.min_stable_power < 700
print(f"\n{'✅' if analyzer_pass else '❌'} Analyzer: {'PASS' if analyzer_pass else 'FAIL'}")

# ============================================================
# PHASE 2: OBSERVER (sample every minute, no sub-sampling)
# ============================================================
print("\n" + "="*70)
print("PHASE 2: OBSERVER")
print("="*70)

observer = Observer(config={})
observations = []

# Process every 10th point (every 10 minutes) for speed
for idx in range(10, len(df), 10):
    observer.update_power(df['value'].iloc[idx], df.index[idx])
    observations.append({
        'time': df.index[idx],
        'power': observer.status.power_consumption,
        'risk': observer.status.cycling_risk,
    })

obs_df = pd.DataFrame(observations)
high_risk_count = (obs_df['risk'] > 0.7).sum()
high_risk_pct = (high_risk_count / len(obs_df)) * 100

print(f"\n✓ Processed {len(obs_df)} observations")
print(f"  High risk (>70%): {high_risk_count} ({high_risk_pct:.1f}%)")
print(f"  Mean risk: {obs_df['risk'].mean():.2f}")

observer_pass = high_risk_count > 0
print(f"\n{'✅' if observer_pass else '❌'} Observer: {'PASS' if observer_pass else 'FAIL'}")

# ============================================================
# PHASE 3: CONTROLLER
# ============================================================
print("\n" + "="*70)
print("PHASE 3: CONTROLLER")
print("="*70)

controller = Controller({'comfort': {'target_temp': 21.0, 'night_temp': 19.0}})
actions = []

# Simulate decisions for high-risk situations
for _, obs in obs_df[obs_df['risk'] > 0.6].iterrows():
    status = OptimizerStatus(
        power_consumption=obs['power'],
        cycling_risk=obs['risk'],
        mode=SystemMode.ACTIVE,
        units={},
        outdoor_temp=None,
        timestamp=obs['time']
    )
    
    prediction = {'cycling_predicted': True, 'probability': obs['risk']}
    analysis_data = {
        'min_stable_power': result.min_stable_power,
        'power_std': 100 if obs['risk'] > 0.7 else 50,
        'power_spread': 400 if obs['risk'] > 0.7 else 200,
    }
    
    action = controller.decide_action(status, prediction, analysis_data)
    if action.action_type != ActionType.NO_ACTION:
        actions.append(action.action_type.value)

print(f"\n✓ Decisions made for {len(obs_df[obs_df['risk'] > 0.6])} high-risk situations")
print(f"  Actions: {len(actions)}")

if actions:
    action_counts = pd.Series(actions).value_counts()
    for act, cnt in action_counts.items():
        print(f"    • {act}: {cnt}")

controller_pass = len(actions) > 0
print(f"\n{'✅' if controller_pass else '❌'} Controller: {'PASS' if controller_pass else 'FAIL'}")

# ============================================================
# PHASE 4: METRICS
# ============================================================
print("\n" + "="*70)
print("PHASE 4: FULL-DATA METRICS (30 days)")
print("="*70)

# Calculate metrics on ALL data
df['std'] = df['value'].rolling(10, min_periods=1).std()
df['spread'] = df['value'].rolling(10, min_periods=1).max() - df['value'].rolling(10, min_periods=1).min()

stable_mask = df['std'] < 50
stable_pct = (stable_mask.sum() / len(df)) * 100

low_power_stable_mask = (df['std'] < 50) & (df['value'] < 600)
low_power_stable_pct = (low_power_stable_mask.sum() / len(df)) * 100

cycling_episodes = ((df['std'] > 100) | (df['spread'] > 400)).sum()
cycling_pct = (cycling_episodes / len(df)) * 100

print(f"\n📊 Stability:")
print(f"  • Stable time (Std<50W): {stable_pct:.1f}%")
print(f"  • Low-power stable (<600W): {low_power_stable_pct:.1f}%")
print(f"  • Cycling detected: {cycling_pct:.1f}%")

print(f"\n📈 Power Stats:")
print(f"  • Mean: {df['value'].mean():.1f} W")
print(f"  • Median: {df['value'].median():.1f} W")
print(f"  • Std Dev: {df['value'].std():.1f} W")
print(f"  • Range: {df['value'].min():.0f} - {df['value'].max():.0f} W")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "="*70)
print("SUMMARY")
print("="*70)

checks = [
    ("Analyzer finds low-power zones", analyzer_pass),
    ("Observer detects cycling", observer_pass),
    ("Controller makes decisions", controller_pass),
    ("Stable time >= 40%", stable_pct >= 40),
]

passed = sum(1 for _, r in checks if r)
total = len(checks)

print(f"\nTest Results: {passed}/{total} passed\n")
for check, result in checks:
    print(f"  {'✅' if result else '❌'} {check}")

if passed == total:
    print(f"\n{'='*70}")
    print("🎉 ALL TESTS PASSED!")
    print("="*70)
elif passed >= 3:
    print(f"\n{'='*70}")
    print("⚠️  MOSTLY PASSED")
    print("="*70)
else:
    print(f"\n{'='*70}")
    print("❌ TESTS FAILED")
    print("="*70)
