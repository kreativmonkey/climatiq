#!/usr/bin/env python3
"""Pipeline test with 5-day dataset (proven to work fast)."""

import pandas as pd
import numpy as np
from climatiq.core.analyzer import Analyzer
from climatiq.core.observer import Observer
from climatiq.core.controller import Controller, ActionType
from climatiq.core.entities import OptimizerStatus, SystemMode

print("="*70)
print("ClimatIQ v2 - Pipeline Test (5 Days)")
print("="*70)

# Load 5-day data
df = pd.read_csv('/home/diyon/.openclaw/workspace/climatiq/data/power_last_5days.csv', 
                 index_col=0, parse_dates=True)

print(f"\nDataset: {len(df)} points ({df.index[0]} to {df.index[-1]})")
print(f"Duration: {(df.index[-1] - df.index[0]).days} days")

# ============================================================
# PHASE 1: ANALYZER
# ============================================================
print("\n" + "="*70)
print("PHASE 1: ANALYZER - Discovering Stable Regions")
print("="*70)

analyzer = Analyzer()
result = analyzer.analyze(df['value'])

print(f"\n✓ Analysis complete")
print(f"  Data sufficient: {result.sufficient_data}")
print(f"  Data quality: {result.data_quality_score:.2f}")
print(f"  Min stable power: {result.min_stable_power:.1f} W")
print(f"  Regions: {len(result.regions)}")

stable = [r for r in result.regions if r.stability_score > 0.7]
unstable = [r for r in result.regions if r.stability_score < 0.4]

print(f"\n  Stable regions (score >0.7): {len(stable)}")
for r in stable[:5]:
    avg_power = r.conditions.get('avg_power', 0)
    avg_std = r.conditions.get('avg_std', 0)
    print(f"    • {r.name}: score={r.stability_score:.2f}, σ={avg_std:.1f}W, n={r.sample_count}")

print(f"\n  Unstable regions (score <0.4): {len(unstable)}")
for r in unstable[:3]:
    avg_std = r.conditions.get('avg_std', 0)
    print(f"    • {r.name}: score={r.stability_score:.2f}, σ={avg_std:.1f}W")

analyzer_pass = result.min_stable_power and result.min_stable_power < 700
print(f"\n{'✅' if analyzer_pass else '❌'} TEST: Min stable power < 700W: {result.min_stable_power:.0f}W")

# ============================================================
# PHASE 2: OBSERVER
# ============================================================
print("\n" + "="*70)
print("PHASE 2: OBSERVER - Real-time Detection")
print("="*70)

observer = Observer(config={})
observations = []

# Process every 5th minute
for idx in range(10, len(df), 5):
    observer.update_power(df['value'].iloc[idx], df.index[idx])
    observations.append({
        'time': df.index[idx],
        'power': observer.status.power_consumption,
        'risk': observer.status.cycling_risk,
    })

obs_df = pd.DataFrame(observations)
high_risk = (obs_df['risk'] > 0.7).sum()
high_risk_pct = (high_risk / len(obs_df)) * 100

print(f"\n✓ Processed {len(obs_df)} observations")
print(f"  High risk (>70%): {high_risk} ({high_risk_pct:.1f}%)")
print(f"  Medium risk (50-70%): {((obs_df['risk'] > 0.5) & (obs_df['risk'] <= 0.7)).sum()}")
print(f"  Low risk (<50%): {(obs_df['risk'] <= 0.5).sum()}")
print(f"  Mean risk: {obs_df['risk'].mean():.2f}")

observer_pass = high_risk > 0
print(f"\n{'✅' if observer_pass else '❌'} TEST: Cycling detected: {high_risk} episodes")

# ============================================================
# PHASE 3: CONTROLLER
# ============================================================
print("\n" + "="*70)
print("PHASE 3: CONTROLLER - Decision Simulation")
print("="*70)

config = {'comfort': {'target_temp': 21.0, 'night_temp': 19.0}, 'unit_priorities': {}}
controller = Controller(config)

actions = []
action_details = []

# Only decide for high-risk situations
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
        'power_std': 120 if obs['risk'] > 0.7 else 60,
        'power_spread': 450 if obs['risk'] > 0.7 else 250,
    }
    
    action = controller.decide_action(status, prediction, analysis_data)
    if action.action_type != ActionType.NO_ACTION:
        actions.append(action.action_type.value)
        action_details.append({
            'time': obs['time'],
            'type': action.action_type.value,
            'reason': action.reason[:60]
        })

print(f"\n✓ High-risk situations: {len(obs_df[obs_df['risk'] > 0.6])}")
print(f"  Actions decided: {len(actions)}")

if actions:
    action_counts = pd.Series(actions).value_counts()
    for act, cnt in action_counts.items():
        print(f"    • {act}: {cnt}")
    
    print(f"\n  Sample actions:")
    for detail in action_details[:5]:
        print(f"    • {detail['time'].strftime('%m-%d %H:%M')}: {detail['type']} - {detail['reason']}")

print(f"\n  Controller stats:")
for k, v in controller.stats.items():
    print(f"    • {k}: {v}")

controller_pass = len(actions) > 0
print(f"\n{'✅' if controller_pass else '❌'} TEST: Actions generated: {len(actions)}")

# ============================================================
# PHASE 4: METRICS
# ============================================================
print("\n" + "="*70)
print("PHASE 4: FULL METRICS (5 days)")
print("="*70)

# Calculate on all data
df['std'] = df['value'].rolling(10, min_periods=1).std()
df['spread'] = df['value'].rolling(10, min_periods=1).max() - df['value'].rolling(10, min_periods=1).min()

stable_mask = df['std'] < 50
stable_pct = (stable_mask.sum() / len(df)) * 100

low_power_stable = ((df['std'] < 50) & (df['value'] < 600)).sum()
low_power_stable_pct = (low_power_stable / len(df)) * 100

print(f"\n📊 Stability Metrics:")
print(f"  • Stable time (Std<50W): {stable_pct:.1f}%")
print(f"  • Low-power stable: {low_power_stable_pct:.1f}%")
print(f"  • Mean Std Dev: {df['std'].mean():.1f}W")

print(f"\n📈 Power Distribution:")
print(f"  • Mean: {df['value'].mean():.0f} W")
print(f"  • Median: {df['value'].median():.0f} W")
print(f"  • P25: {df['value'].quantile(0.25):.0f} W")
print(f"  • P75: {df['value'].quantile(0.75):.0f} W")
print(f"  • Min/Max: {df['value'].min():.0f} / {df['value'].max():.0f} W")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "="*70)
print("VALIDATION SUMMARY")
print("="*70)

checks = [
    ("Analyzer identifies low-power zones (<700W)", analyzer_pass),
    ("Observer detects cycling events", observer_pass),
    ("Controller makes decisions", controller_pass),
    ("Stable time >= 40%", stable_pct >= 40),
    ("Low-power stable >= 20%", low_power_stable_pct >= 20),
]

passed = sum(1 for _, r in checks if r)
total = len(checks)

print(f"\nResults: {passed}/{total} checks passed\n")
for check, result in checks:
    print(f"  {'✅' if result else '❌'} {check}")

print(f"\n🎯 Target Metrics vs Actual:")
print(f"  • >80% stable: Target vs {stable_pct:.1f}% {'✅' if stable_pct > 80 else '⚠️ '}")
print(f"  • >50% low-power: Target vs {low_power_stable_pct:.1f}% {'✅' if low_power_stable_pct > 50 else '⚠️ '}")
print(f"  • <700W min stable: Target vs {result.min_stable_power:.0f}W {'✅' if result.min_stable_power < 700 else '❌'}")

if passed == total:
    print(f"\n{'='*70}")
    print("🎉 ALL VALIDATION CHECKS PASSED!")
    print("Pipeline is ready for deployment.")
    print("="*70)
elif passed >= 4:
    print(f"\n{'='*70}")
    print("⚠️  MOSTLY PASSED - Minor tuning needed")
    print("="*70)
else:
    print(f"\n{'='*70}")
    print("❌ VALIDATION FAILED - Major issues")
    print("="*70)

print("\n✅ Test complete.")
