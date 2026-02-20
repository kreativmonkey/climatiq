#!/usr/bin/env python3
"""Automatisches Finden von stabilen Betriebszonen ohne hard-coded Ranges"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from sklearn.cluster import DBSCAN
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler
from climatiq.data.influx_v1_client import InfluxV1Client

client = InfluxV1Client()

MAX_DAYS = 90
end = datetime.now()
start = end - timedelta(days=MAX_DAYS)

print(f"=== AUTOMATISCHE STABILE-ZONEN DETEKTION (max {MAX_DAYS} Tage) ===\n")

# ===== DATEN LADEN =====
entities = {
    'power': 'ac_current_energy',
    'outdoor_temp': 'ac_temperatur_outdoor',
}

print("Lade Daten (5min Auflösung)...")
data = {}
for key, entity in entities.items():
    df_ent = client.get_entity_data(entity, start, end, resample='5m')
    if not df_ent.empty:
        data[key] = df_ent['value']
        print(f"  ✓ {key}: {len(df_ent)} Punkte")

df = pd.DataFrame(data).sort_index()

# Feature Engineering
df['power_std'] = df['power'].rolling(6, min_periods=1).std()
df['power_spread'] = df['power'].rolling(6, min_periods=1).max() - df['power'].rolling(6, min_periods=1).min()
df['power_gradient'] = df['power'].diff().rolling(6).mean().abs()

# Drop NaN und Anlage-AUS (< 100W)
df = df.dropna()
df = df[df['power'] > 100].copy()

print(f"\nDataset nach Cleanup: {len(df)} Zeitpunkte")
print(f"Power Range: {df['power'].min():.0f} - {df['power'].max():.0f}W")

# ===== METHOD 1: GAUSSIAN MIXTURE MODEL =====
print("\n=== METHOD 1: Gaussian Mixture Model auf (power, power_std) ===")

X = df[['power', 'power_std']].values
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

# Try different number of clusters
best_n = 3
best_bic = np.inf
for n in range(2, 8):
    gmm = GaussianMixture(n_components=n, random_state=42)
    gmm.fit(X_scaled)
    bic = gmm.bic(X_scaled)
    if bic < best_bic:
        best_bic = bic
        best_n = n

print(f"Optimal clusters (BIC): {best_n}")

gmm = GaussianMixture(n_components=best_n, random_state=42)
df['cluster_gmm'] = gmm.fit_predict(X_scaled)

# Analyze clusters
print("\n--- CLUSTER STATISTICS (GMM) ---")
cluster_stats = []
for c in range(best_n):
    cluster_data = df[df['cluster_gmm'] == c]
    stats = {
        'cluster': c,
        'size': len(cluster_data),
        'power_mean': cluster_data['power'].mean(),
        'power_median': cluster_data['power'].median(),
        'power_std_mean': cluster_data['power_std'].mean(),
        'power_std_median': cluster_data['power_std'].median(),
        'outdoor_temp_mean': cluster_data['outdoor_temp'].mean() if 'outdoor_temp' in cluster_data else np.nan,
    }
    cluster_stats.append(stats)
    print(f"Cluster {c}:")
    print(f"  Size: {stats['size']:5d} Punkte ({stats['size']/len(df)*100:.1f}%)")
    print(f"  Power: {stats['power_median']:.0f}W (mean: {stats['power_mean']:.0f}W)")
    print(f"  Power_std: {stats['power_std_median']:.1f}W (mean: {stats['power_std_mean']:.1f}W)")
    if not np.isnan(stats['outdoor_temp_mean']):
        print(f"  Outdoor Temp: {stats['outdoor_temp_mean']:.1f}°C")

cluster_df = pd.DataFrame(cluster_stats).sort_values('power_std_median')

# Identify stable clusters (lowest power_std)
print("\n--- STABLE CLUSTERS (sortiert nach power_std) ---")
for idx, row in cluster_df.iterrows():
    stability = "🟢 STABIL" if row['power_std_median'] < 50 else "🟡 MODERAT" if row['power_std_median'] < 100 else "🔴 INSTABIL"
    print(f"Cluster {int(row['cluster'])}: {stability} | Power ~{row['power_median']:.0f}W | Std {row['power_std_median']:.0f}W")

# ===== METHOD 2: QUANTILE-BASED =====
print("\n=== METHOD 2: Quantile-basierte Stabilität ===")

# Define stable as: power_std in lowest 25% quantile
power_std_threshold = df['power_std'].quantile(0.25)
print(f"25% Quantil power_std: {power_std_threshold:.1f}W")

df['stable_quantile'] = df['power_std'] < power_std_threshold

stable_data = df[df['stable_quantile']]
print(f"\nStabile Punkte (power_std < {power_std_threshold:.1f}W): {len(stable_data)} ({len(stable_data)/len(df)*100:.1f}%)")
print(f"  Power Range: {stable_data['power'].min():.0f} - {stable_data['power'].max():.0f}W")
print(f"  Power Median: {stable_data['power'].median():.0f}W")

# Power distribution in stable zone
print("\n  Power Verteilung in stabiler Zone:")
for pmin, pmax, label in [(0, 500, "Niedrig"), (500, 800, "Mittel"), (800, 1200, "Hoch"), (1200, 5000, "Sehr hoch")]:
    count = ((stable_data['power'] >= pmin) & (stable_data['power'] < pmax)).sum()
    pct = count / len(stable_data) * 100 if len(stable_data) > 0 else 0
    print(f"    {label:12s} ({pmin:4d}-{pmax:4d}W): {count:5d} Punkte ({pct:.1f}%)")

# ===== METHOD 3: ADAPTIVE THRESHOLD PER POWER RANGE =====
print("\n=== METHOD 3: Adaptive Threshold per Power Range ===")

power_bins = [(0, 400), (400, 700), (700, 1000), (1000, 1500), (1500, 5000)]
adaptive_thresholds = {}

for pmin, pmax in power_bins:
    mask = (df['power'] >= pmin) & (df['power'] < pmax)
    if mask.sum() > 100:
        power_std_in_range = df.loc[mask, 'power_std']
        threshold = power_std_in_range.quantile(0.25)
        adaptive_thresholds[f"{pmin}-{pmax}"] = threshold
        stable_count = (power_std_in_range < threshold).sum()
        print(f"  {pmin:4d}-{pmax:4d}W: Threshold={threshold:.1f}W, Stabil: {stable_count}/{mask.sum()} ({stable_count/mask.sum()*100:.1f}%)")

# ===== VISUALISIERUNG =====
print("\nErstelle Visualisierungen...")

fig = plt.figure(figsize=(20, 12))

# Plot 1: Scatter (power vs power_std) colored by GMM cluster
ax1 = plt.subplot(2, 3, 1)
scatter1 = ax1.scatter(df['power'], df['power_std'], c=df['cluster_gmm'], cmap='viridis', alpha=0.3, s=5)
ax1.set_xlabel('Power (W)')
ax1.set_ylabel('Power Std (W)')
ax1.set_title(f'GMM Clustering ({best_n} Clusters)')
plt.colorbar(scatter1, ax=ax1, label='Cluster')
ax1.grid(True, alpha=0.3)
ax1.axhline(y=50, color='red', linestyle='--', alpha=0.5, label='Std=50W')
ax1.legend()

# Plot 2: Cluster characteristics
ax2 = plt.subplot(2, 3, 2)
colors_map = plt.cm.viridis(np.linspace(0, 1, best_n))
for idx, row in cluster_df.iterrows():
    ax2.scatter(row['power_median'], row['power_std_median'], 
                s=row['size']/10, alpha=0.7, 
                color=colors_map[int(row['cluster'])],
                label=f"C{int(row['cluster'])}")
ax2.set_xlabel('Median Power (W)')
ax2.set_ylabel('Median Power Std (W)')
ax2.set_title('Cluster Centroids (size = # samples)')
ax2.axhline(y=50, color='red', linestyle='--', alpha=0.5)
ax2.grid(True, alpha=0.3)
ax2.legend()

# Plot 3: Quantile-based stable zone
ax3 = plt.subplot(2, 3, 3)
ax3.scatter(df[df['stable_quantile']]['power'], 
            df[df['stable_quantile']]['power_std'], 
            c='green', alpha=0.3, s=5, label='Stabil (25% Quantil)')
ax3.scatter(df[~df['stable_quantile']]['power'], 
            df[~df['stable_quantile']]['power_std'], 
            c='red', alpha=0.1, s=2, label='Instabil')
ax3.set_xlabel('Power (W)')
ax3.set_ylabel('Power Std (W)')
ax3.set_title(f'Quantile-basiert (Threshold: {power_std_threshold:.1f}W)')
ax3.axhline(y=power_std_threshold, color='black', linestyle='--', alpha=0.5)
ax3.legend()
ax3.grid(True, alpha=0.3)

# Plot 4: Power distribution per cluster
ax4 = plt.subplot(2, 3, 4)
for c in range(best_n):
    cluster_power = df[df['cluster_gmm'] == c]['power']
    ax4.hist(cluster_power, bins=30, alpha=0.5, label=f'C{c}', color=colors_map[c])
ax4.set_xlabel('Power (W)')
ax4.set_ylabel('Anzahl')
ax4.set_title('Power Verteilung pro Cluster')
ax4.legend()
ax4.grid(True, alpha=0.3)

# Plot 5: Power_std distribution per cluster
ax5 = plt.subplot(2, 3, 5)
for c in range(best_n):
    cluster_std = df[df['cluster_gmm'] == c]['power_std']
    ax5.hist(cluster_std, bins=30, alpha=0.5, label=f'C{c}', color=colors_map[c])
ax5.set_xlabel('Power Std (W)')
ax5.set_ylabel('Anzahl')
ax5.set_title('Power Std Verteilung pro Cluster')
ax5.legend()
ax5.grid(True, alpha=0.3)
ax5.axvline(x=50, color='red', linestyle='--', alpha=0.5)

# Plot 6: Outdoor temp vs stability (if available)
ax6 = plt.subplot(2, 3, 6)
if 'outdoor_temp' in df.columns:
    stable_outdoor = df[df['stable_quantile']]['outdoor_temp']
    unstable_outdoor = df[~df['stable_quantile']]['outdoor_temp']
    ax6.hist(stable_outdoor, bins=30, alpha=0.6, color='green', label='Stabil')
    ax6.hist(unstable_outdoor, bins=30, alpha=0.4, color='red', label='Instabil')
    ax6.set_xlabel('Außentemperatur (°C)')
    ax6.set_ylabel('Anzahl')
    ax6.set_title('Stabilität vs. Außentemperatur')
    ax6.legend()
    ax6.grid(True, alpha=0.3)

plt.tight_layout()
output_path = '/home/diyon/.openclaw/workspace/climatiq/data/auto_stable_zones.png'
plt.savefig(output_path, dpi=150)
print(f"✓ Gespeichert: {output_path}")

# ===== EXPORT STABLE ZONE DEFINITION =====
stable_zones_config = {
    'method': 'gmm',
    'clusters': cluster_df.to_dict('records'),
    'quantile_threshold': float(power_std_threshold),
    'stable_clusters': cluster_df[cluster_df['power_std_median'] < 50]['cluster'].tolist(),
}

import json
with open('/home/diyon/.openclaw/workspace/climatiq/data/stable_zones_config.json', 'w') as f:
    json.dump(stable_zones_config, f, indent=2)
print("✓ Config exportiert: data/stable_zones_config.json")

print("\n✅ Analyse abgeschlossen!")
print(f"\n🎯 EMPFEHLUNG für Labeling:")
stable_clusters = cluster_df[cluster_df['power_std_median'] < 50]
if len(stable_clusters) > 0:
    print(f"  - Nutze Cluster {stable_clusters['cluster'].tolist()} als 'stable'")
    print(f"  - Diese decken Power-Bereiche ab:")
    for _, row in stable_clusters.iterrows():
        print(f"    * Cluster {int(row['cluster'])}: ~{row['power_median']:.0f}W (Std: {row['power_std_median']:.0f}W)")
else:
    print(f"  - Nutze power_std < {power_std_threshold:.1f}W als 'stable' (25% Quantil)")
