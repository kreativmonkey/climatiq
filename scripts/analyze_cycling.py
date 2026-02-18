#!/usr/bin/env python3
"""Analyze power data for cycling patterns using v2 detection logic."""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta

# Load data
df = pd.read_csv('/home/diyon/.openclaw/workspace/climatiq/data/power_last_5days.csv', 
                 index_col=0, parse_dates=True)

# Berechne Rolling-Metriken (5 Min Fenster)
window = 5  # minutes
df['power_mean'] = df['value'].rolling(window, min_periods=1).mean()
df['power_std'] = df['value'].rolling(window, min_periods=1).std()
df['power_min'] = df['value'].rolling(window, min_periods=1).min()
df['power_max'] = df['value'].rolling(window, min_periods=1).max()
df['power_spread'] = df['power_max'] - df['power_min']

# Gradient (W/min)
df['power_gradient'] = df['value'].diff()

# Cycling Risk Berechnung (vereinfacht)
# Hohe Varianz + hoher Spread = hohes Risiko
df['cycling_risk'] = 0.0
df.loc[df['power_std'] > 50, 'cycling_risk'] += 30
df.loc[df['power_std'] > 100, 'cycling_risk'] += 30
df.loc[df['power_spread'] > 200, 'cycling_risk'] += 20
df.loc[df['power_spread'] > 400, 'cycling_risk'] += 20
df['cycling_risk'] = df['cycling_risk'].clip(0, 100)

# Identifiziere Cycling-Episoden (Risk > 70%)
df['is_cycling'] = df['cycling_risk'] > 70

# Statistiken
print("=== Cycling Analysis (v2) ===")
print(f"\nDataset: {len(df)} points, {df.index[0]} to {df.index[-1]}")
print(f"\nPower Statistics:")
print(f"  Range: {df['value'].min():.1f} - {df['value'].max():.1f} W")
print(f"  Mean: {df['value'].mean():.1f} W")
print(f"  Overall Std Dev: {df['value'].std():.1f} W")

print(f"\nCycling Detection:")
cycling_points = df['is_cycling'].sum()
cycling_pct = (cycling_points / len(df)) * 100
print(f"  Cycling points: {cycling_points} ({cycling_pct:.1f}%)")
print(f"  Stable points: {len(df) - cycling_points} ({100-cycling_pct:.1f}%)")

# Finde Cycling-Episoden (zusammenhängende Zeiträume)
df['cycling_episode'] = (df['is_cycling'] != df['is_cycling'].shift()).cumsum()
episodes = df[df['is_cycling']].groupby('cycling_episode').agg({
    'value': ['min', 'max', 'mean', 'std', 'count']
})
episodes.columns = ['_'.join(col).strip() for col in episodes.columns.values]
episodes = episodes[episodes['value_count'] > 5]  # Min 5 Minuten

print(f"\nCycling Episodes (>5 min): {len(episodes)}")
if len(episodes) > 0:
    print(f"  Avg duration: {episodes['value_count'].mean():.1f} min")
    print(f"  Avg power spread: {(episodes['value_max'] - episodes['value_min']).mean():.1f} W")

# Finde stabile Bereiche (Risk < 30% und >10 min)
df['is_stable'] = df['cycling_risk'] < 30
df['stable_episode'] = (df['is_stable'] != df['is_stable'].shift()).cumsum()
stable_episodes = df[df['is_stable']].groupby('stable_episode').agg({
    'value': ['min', 'max', 'mean', 'std', 'count']
})
stable_episodes.columns = ['_'.join(col).strip() for col in stable_episodes.columns.values]
stable_episodes = stable_episodes[stable_episodes['value_count'] > 10]

print(f"\nStable Episodes (>10 min, Risk<30%): {len(stable_episodes)}")
if len(stable_episodes) > 0:
    print(f"  Avg duration: {stable_episodes['value_count'].mean():.1f} min")
    print(f"  Avg power: {stable_episodes['value_mean'].mean():.1f} W")
    print(f"  Avg std dev: {stable_episodes['value_std'].mean():.1f} W")
    print(f"\n  Low-power stable (<600W): {(stable_episodes['value_mean'] < 600).sum()} episodes")
    if (stable_episodes['value_mean'] < 600).sum() > 0:
        low_power = stable_episodes[stable_episodes['value_mean'] < 600]
        print(f"    Mean power: {low_power['value_mean'].mean():.1f} W")
        print(f"    Mean std dev: {low_power['value_std'].mean():.1f} W")

# Erstelle Visualisierung
fig, axes = plt.subplots(4, 1, figsize=(16, 12), sharex=True)

# Plot 1: Power mit Cycling-Markierungen
ax1 = axes[0]
ax1.plot(df.index, df['value'], 'b-', linewidth=0.5, alpha=0.7, label='Power')
ax1.plot(df.index, df['power_mean'], 'navy', linewidth=1.5, label='5-min Mean')
# Markiere Cycling-Phasen
cycling_mask = df['is_cycling']
ax1.fill_between(df.index, 0, df['value'].max() * 1.1, 
                 where=cycling_mask, alpha=0.2, color='red', label='Cycling')
ax1.set_ylabel('Power (W)', fontsize=12)
ax1.set_title('AC Power Consumption - Last 5 Days', fontsize=14, fontweight='bold')
ax1.legend(loc='upper right')
ax1.grid(True, alpha=0.3)
ax1.set_ylim(0, df['value'].max() * 1.1)

# Plot 2: Standard Deviation
ax2 = axes[1]
ax2.plot(df.index, df['power_std'], 'orange', linewidth=1, label='5-min Std Dev')
ax2.axhline(50, color='green', linestyle='--', linewidth=1, alpha=0.5, label='Stable threshold (50W)')
ax2.axhline(100, color='red', linestyle='--', linewidth=1, alpha=0.5, label='High variance (100W)')
ax2.set_ylabel('Std Dev (W)', fontsize=12)
ax2.set_title('Power Variance (Stability Indicator)', fontsize=12, fontweight='bold')
ax2.legend(loc='upper right')
ax2.grid(True, alpha=0.3)
ax2.set_ylim(0, max(200, df['power_std'].max() * 1.1))

# Plot 3: Power Spread (Max-Min)
ax3 = axes[2]
ax3.plot(df.index, df['power_spread'], 'purple', linewidth=1, label='Power Spread (Max-Min)')
ax3.axhline(200, color='green', linestyle='--', linewidth=1, alpha=0.5, label='Low spread')
ax3.axhline(400, color='red', linestyle='--', linewidth=1, alpha=0.5, label='High spread')
ax3.set_ylabel('Spread (W)', fontsize=12)
ax3.set_title('Power Range in 5-min Window', fontsize=12, fontweight='bold')
ax3.legend(loc='upper right')
ax3.grid(True, alpha=0.3)
ax3.set_ylim(0, max(500, df['power_spread'].max() * 1.1))

# Plot 4: Cycling Risk
ax4 = axes[3]
ax4.plot(df.index, df['cycling_risk'], 'red', linewidth=1, label='Cycling Risk')
ax4.axhline(70, color='red', linestyle='--', linewidth=2, alpha=0.7, label='High risk threshold')
ax4.axhline(30, color='green', linestyle='--', linewidth=2, alpha=0.7, label='Stable threshold')
ax4.fill_between(df.index, 0, 100, where=df['cycling_risk'] > 70, 
                 alpha=0.2, color='red', label='Cycling detected')
ax4.set_ylabel('Risk (%)', fontsize=12)
ax4.set_xlabel('Date/Time', fontsize=12)
ax4.set_title('Cycling Risk Score', fontsize=12, fontweight='bold')
ax4.legend(loc='upper right')
ax4.grid(True, alpha=0.3)
ax4.set_ylim(0, 105)

# Format x-axis
for ax in axes:
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=12))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

plt.tight_layout()
plt.savefig('/home/diyon/.openclaw/workspace/climatiq/data/cycling_analysis.png', dpi=150, bbox_inches='tight')
print(f"\n✓ Visualization saved to data/cycling_analysis.png")

# Zoomed view: letzte 24h
df_recent = df[df.index > (df.index[-1] - timedelta(hours=24))]

fig2, axes2 = plt.subplots(3, 1, figsize=(16, 10), sharex=True)

# Power + Cycling
ax1 = axes2[0]
ax1.plot(df_recent.index, df_recent['value'], 'b-', linewidth=1, alpha=0.8, label='Power')
ax1.plot(df_recent.index, df_recent['power_mean'], 'navy', linewidth=2, label='5-min Mean')
cycling_mask = df_recent['is_cycling']
ax1.fill_between(df_recent.index, 0, df_recent['value'].max() * 1.1, 
                 where=cycling_mask, alpha=0.3, color='red', label='Cycling')
ax1.set_ylabel('Power (W)', fontsize=12)
ax1.set_title('AC Power - Last 24 Hours (Detailed View)', fontsize=14, fontweight='bold')
ax1.legend(loc='upper right')
ax1.grid(True, alpha=0.3)

# Std Dev
ax2 = axes2[1]
ax2.plot(df_recent.index, df_recent['power_std'], 'orange', linewidth=1.5)
ax2.axhline(50, color='green', linestyle='--', linewidth=1.5, alpha=0.6)
ax2.axhline(100, color='red', linestyle='--', linewidth=1.5, alpha=0.6)
ax2.set_ylabel('Std Dev (W)', fontsize=12)
ax2.set_title('Power Stability (Lower = Better)', fontsize=12, fontweight='bold')
ax2.grid(True, alpha=0.3)

# Cycling Risk
ax3 = axes2[2]
ax3.plot(df_recent.index, df_recent['cycling_risk'], 'red', linewidth=2)
ax3.axhline(70, color='red', linestyle='--', linewidth=2, alpha=0.7)
ax3.axhline(30, color='green', linestyle='--', linewidth=2, alpha=0.7)
ax3.fill_between(df_recent.index, 0, 100, where=df_recent['cycling_risk'] > 70, 
                 alpha=0.3, color='red')
ax3.set_ylabel('Risk (%)', fontsize=12)
ax3.set_xlabel('Time', fontsize=12)
ax3.set_title('Cycling Risk', fontsize=12, fontweight='bold')
ax3.grid(True, alpha=0.3)
ax3.set_ylim(0, 105)

for ax in axes2:
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

plt.tight_layout()
plt.savefig('/home/diyon/.openclaw/workspace/climatiq/data/cycling_analysis_24h.png', dpi=150, bbox_inches='tight')
print(f"✓ 24h visualization saved to data/cycling_analysis_24h.png")
