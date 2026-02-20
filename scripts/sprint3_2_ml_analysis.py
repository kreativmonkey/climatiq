#!/usr/bin/env python3
"""Sprint 3.2: ML Feature Importance & Multi-Dimensional Clustering"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import DBSCAN
from sklearn.decomposition import PCA
from climatiq.data.influx_v1_client import InfluxV1Client

client = InfluxV1Client()

DAYS = 60
end = datetime.now()
start = end - timedelta(days=DAYS)

print(f"=== SPRINT 3.2: ML ANALYSIS ({DAYS} Tage) ===\n")

# ===== DATEN LADEN =====
entities = {
    'power': 'ac_current_energy',
    'outdoor_temp': 'ac_temperatur_outdoor',
    'temp_eg': 'temperatur_wohnzimmer',
    'temp_sz': 'temperatur_flur_og',
    'temp_az': 'rwm_arbeitszimmer_temperature',
    'temp_kz': '0x000d6f0019c90b85_temperature',
    'temp_ak': 'temperatur_flur_og',
    'target_eg': 'panasonic_climate_erdgeschoss_desired_temperature',
    'target_sz': 'panasonic_climate_schlafzimmer_desired_temperature',
    'target_az': 'panasonic_climate_arbeitszimmer_desired_temperature',
    'target_kz': 'panasonic_climate_kinderzimmer_desired_temperature',
    'target_ak': 'panasonic_climate_ankleide_desired_temperature',
}

print("Lade Daten (5min Auflösung)...")
data = {}
for key, entity in entities.items():
    df = client.get_entity_data(entity, start, end, resample='5m')
    if not df.empty:
        data[key] = df['value']
        print(f"  ✓ {key}")

df = pd.DataFrame(data).sort_index()

# Forward-fill targets
for col in [c for c in df.columns if c.startswith('target_')]:
    df[col] = df[col].ffill()

print(f"\nDataset: {len(df)} Zeitpunkte")

# ===== FEATURE ENGINEERING =====
print("\nFeature Engineering...")

# Power features
df['power_std'] = df['power'].rolling(6, min_periods=1).std()
df['power_gradient'] = df['power'].diff().rolling(6).mean()
df['power_spread'] = df['power'].rolling(6, min_periods=1).max() - df['power'].rolling(6, min_periods=1).min()

# Temperature deltas (Abweichung vom Soll)
for room in ['eg', 'sz', 'az', 'kz', 'ak']:
    t_col = f'temp_{room}'
    s_col = f'target_{room}'
    if t_col in df.columns and s_col in df.columns:
        df[f'delta_{room}'] = df[t_col] - df[s_col]
        df[f'delta_{room}_abs'] = df[f'delta_{room}'].abs()

# Outdoor delta
if 'outdoor_temp' in df.columns:
    df['outdoor_gradient'] = df['outdoor_temp'].diff().rolling(6).mean()

# Hour of day (cyclical)
df['hour'] = df.index.hour
df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)

# ===== LABELING =====
print("Labeling (stable vs unstable)...")
df['label'] = 'neutral'
df.loc[df['power_std'] < 50, 'label'] = 'stable'
df.loc[df['power_std'] > 120, 'label'] = 'unstable'

# Drop neutral samples for binary classification
df_ml = df[df['label'].isin(['stable', 'unstable'])].copy()
df_ml['target'] = (df_ml['label'] == 'unstable').astype(int)

print(f"  Stable: {(df_ml['target'] == 0).sum()}")
print(f"  Unstable: {(df_ml['target'] == 1).sum()}")

# ===== FEATURE SELECTION =====
feature_cols = [
    'power', 'power_std', 'power_gradient', 'power_spread',
    'outdoor_temp', 'outdoor_gradient',
    'delta_eg', 'delta_sz', 'delta_az', 'delta_kz', 'delta_ak',
    'delta_eg_abs', 'delta_sz_abs', 'delta_az_abs', 'delta_kz_abs', 'delta_ak_abs',
    'hour_sin', 'hour_cos',
]

# Check feature availability and fill missing values
available_features = [f for f in feature_cols if f in df_ml.columns]
df_ml_features = df_ml[available_features + ['target']].copy()

# Fill NaN values intelligently
for col in available_features:
    if df_ml_features[col].isna().sum() > 0:
        # For gradient features, fill with 0 (no change)
        if 'gradient' in col:
            df_ml_features[col] = df_ml_features[col].fillna(0)
        # For other features, forward-fill then back-fill
        else:
            df_ml_features[col] = df_ml_features[col].ffill().bfill()

df_ml = df_ml_features.dropna()

print(f"\nFeatures: {len(available_features)}")
print(f"Samples after cleanup: {len(df_ml)}")

X = df_ml[available_features].values
y = df_ml['target'].values

# ===== RANDOM FOREST CLASSIFIER =====
print("\n=== RANDOM FOREST TRAINING ===")

# Balance classes
from sklearn.utils import resample
df_stable = df_ml[df_ml['target'] == 0]
df_unstable = df_ml[df_ml['target'] == 1]

# Downsample majority class
n_samples = min(len(df_stable), len(df_unstable))
df_stable_balanced = resample(df_stable, n_samples=n_samples, random_state=42)
df_unstable_balanced = resample(df_unstable, n_samples=n_samples, random_state=42)
df_balanced = pd.concat([df_stable_balanced, df_unstable_balanced])

X_balanced = df_balanced[available_features].values
y_balanced = df_balanced['target'].values

print(f"Balanced dataset: {len(df_balanced)} samples ({n_samples} stable, {n_samples} unstable)")

# Train model
rf = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42)
rf.fit(X_balanced, y_balanced)

# Feature importance
importances = rf.feature_importances_
feature_importance_df = pd.DataFrame({
    'feature': available_features,
    'importance': importances
}).sort_values('importance', ascending=False)

print("\n--- TOP 10 FEATURE IMPORTANCE ---")
for idx, row in feature_importance_df.head(10).iterrows():
    print(f"  {row['importance']:.3f} : {row['feature']}")

# ===== CLUSTERING (STABLE ZONES) =====
print("\n=== MULTI-DIMENSIONAL CLUSTERING ===")

# Only use stable samples - use the cleaned dataframe
df_stable_full = df_ml[df_ml['target'] == 0][available_features].copy()
print(f"Stable samples for clustering: {len(df_stable_full)}")

if len(df_stable_full) < 100:
    print("⚠️ Nicht genug stabile Samples für Clustering! Skip.")
    # Create dummy plot
    fig = plt.figure(figsize=(20, 12))
    plt.text(0.5, 0.5, 'Not enough stable samples for clustering', ha='center', va='center')
    plt.savefig('/home/diyon/.openclaw/workspace/climatiq/data/sprint3_2_ml_analysis.png', dpi=150)
    print("✅ Sprint 3.2 abgeschlossen (ohne Clustering)")
    exit(0)

X_stable = df_stable_full.values

# Standardize
scaler = StandardScaler()
X_stable_scaled = scaler.fit_transform(X_stable)

# PCA for visualization
pca = PCA(n_components=2)
X_pca = pca.fit_transform(X_stable_scaled)

# DBSCAN clustering
dbscan = DBSCAN(eps=0.5, min_samples=50)
clusters = dbscan.fit_predict(X_stable_scaled)

print(f"Clusters gefunden: {len(set(clusters)) - (1 if -1 in clusters else 0)}")
print(f"Noise points: {(clusters == -1).sum()}")

# ===== VISUALISIERUNG =====
print("\nErstelle Visualisierungen...")

fig = plt.figure(figsize=(20, 12))

# Plot 1: Feature Importance
ax1 = plt.subplot(2, 3, 1)
top_features = feature_importance_df.head(15)
ax1.barh(range(len(top_features)), top_features['importance'], color='steelblue', alpha=0.7)
ax1.set_yticks(range(len(top_features)))
ax1.set_yticklabels(top_features['feature'])
ax1.set_xlabel('Importance')
ax1.set_title('Top 15 Features (Random Forest)')
ax1.grid(True, alpha=0.3, axis='x')

# Plot 2: Clusters (PCA projection)
ax2 = plt.subplot(2, 3, 2)
scatter = ax2.scatter(X_pca[:, 0], X_pca[:, 1], c=clusters, cmap='viridis', alpha=0.5, s=10)
ax2.set_xlabel(f'PC1 ({pca.explained_variance_ratio_[0]:.1%} variance)')
ax2.set_ylabel(f'PC2 ({pca.explained_variance_ratio_[1]:.1%} variance)')
ax2.set_title('Stable Operating Zones (PCA + DBSCAN)')
plt.colorbar(scatter, ax=ax2, label='Cluster')

# Plot 3: Power vs Top Feature
top_feature = feature_importance_df.iloc[0]['feature']
ax3 = plt.subplot(2, 3, 3)
ax3.scatter(df_ml[top_feature], df_ml['power'], c=df_ml['target'], cmap='RdYlGn_r', alpha=0.3, s=10)
ax3.set_xlabel(top_feature)
ax3.set_ylabel('Power (W)')
ax3.set_title(f'Power vs {top_feature}')
ax3.grid(True, alpha=0.3)

# Plot 4: Power_std distribution per label
ax4 = plt.subplot(2, 3, 4)
df_ml[df_ml['target'] == 0]['power_std'].hist(bins=30, alpha=0.6, color='green', label='Stable', ax=ax4)
df_ml[df_ml['target'] == 1]['power_std'].hist(bins=30, alpha=0.6, color='red', label='Unstable', ax=ax4)
ax4.set_xlabel('Power Std (W)')
ax4.set_ylabel('Anzahl')
ax4.set_title('Power Std Distribution')
ax4.legend()
ax4.grid(True, alpha=0.3)

# Plot 5: Correlation matrix (top features)
ax5 = plt.subplot(2, 3, 5)
top_features_list = feature_importance_df.head(8)['feature'].tolist()
corr = df_ml[top_features_list].corr()
im = ax5.imshow(corr, cmap='coolwarm', vmin=-1, vmax=1, aspect='auto')
ax5.set_xticks(range(len(top_features_list)))
ax5.set_yticks(range(len(top_features_list)))
ax5.set_xticklabels([f.replace('delta_', '') for f in top_features_list], rotation=45, ha='right')
ax5.set_yticklabels([f.replace('delta_', '') for f in top_features_list])
ax5.set_title('Feature Correlation Matrix')
plt.colorbar(im, ax=ax5)

# Plot 6: Cluster characteristics (mean values per cluster)
ax6 = plt.subplot(2, 3, 6)
df_stable_full['cluster'] = clusters
cluster_stats = []
for c in set(clusters):
    if c != -1:  # Ignore noise
        cluster_data = df_stable_full[df_stable_full['cluster'] == c]
        mean_power = cluster_data['power'].mean()
        mean_top_feature = cluster_data[top_feature].mean()
        cluster_stats.append({'cluster': c, 'power': mean_power, 'feature': mean_top_feature, 'size': len(cluster_data)})

if cluster_stats:
    cluster_df = pd.DataFrame(cluster_stats)
    scatter2 = ax6.scatter(cluster_df['feature'], cluster_df['power'], s=cluster_df['size']/10, alpha=0.7, c=cluster_df['cluster'], cmap='viridis')
    ax6.set_xlabel(f'Mean {top_feature}')
    ax6.set_ylabel('Mean Power (W)')
    ax6.set_title('Cluster Centroids (size = # samples)')
    plt.colorbar(scatter2, ax=ax6, label='Cluster')
    ax6.grid(True, alpha=0.3)

plt.tight_layout()
output_path = '/home/diyon/.openclaw/workspace/climatiq/data/sprint3_2_ml_analysis.png'
plt.savefig(output_path, dpi=150)
print(f"✓ Gespeichert: {output_path}")

# ===== EXPORT FEATURE IMPORTANCE =====
feature_importance_df.to_csv('/home/diyon/.openclaw/workspace/climatiq/data/feature_importance.csv', index=False)
print("✓ Feature Importance exportiert: data/feature_importance.csv")

print("\n✅ Sprint 3.2 abgeschlossen!")
print(f"\n🎯 KEY FINDINGS:")
print(f"  - Top Feature: {feature_importance_df.iloc[0]['feature']} ({feature_importance_df.iloc[0]['importance']:.3f})")
print(f"  - Stable Clusters: {len(set(clusters)) - (1 if -1 in clusters else 0)}")
print(f"  - Model Accuracy wird im nächsten Sprint mit Train/Test Split gemessen")
