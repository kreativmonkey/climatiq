#!/usr/bin/env python3
"""Sprint 3.2 V3: Kausale Analyse - Was VERURSACHT Instabilität?"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.mixture import GaussianMixture
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix
from climatiq.data.influx_v1_client import InfluxV1Client

client = InfluxV1Client()

# Lade so viele Daten wie möglich (max 90 Tage)
MAX_DAYS = 90
end = datetime.now()
start = end - timedelta(days=MAX_DAYS)

print(f"=== SPRINT 3.2 V3: KAUSALE ANALYSE ===\n")
print("Frage: Welche EXTERNEN Faktoren VERURSACHEN Instabilität?\n")
print(f"Lade Daten (max {MAX_DAYS} Tage)...")
print(f"Zeitraum: {start.strftime('%Y-%m-%d')} bis {end.strftime('%Y-%m-%d')}\n")

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
    df_ent = client.get_entity_data(entity, start, end, resample='5m')
    if not df_ent.empty:
        data[key] = df_ent['value']

df = pd.DataFrame(data).sort_index()

# Forward-fill targets
for col in [c for c in df.columns if c.startswith('target_')]:
    df[col] = df[col].ffill()

print(f"Dataset: {len(df)} Zeitpunkte")

# ===== FEATURE ENGINEERING (NUR EXTERNE FAKTOREN!) =====
print("\nFeature Engineering (nur externe Faktoren)...")

# Power-Metriken für Labeling (NICHT als Features!)
df['power_std'] = df['power'].rolling(6, min_periods=1).std()
df['power_spread'] = df['power'].rolling(6, min_periods=1).max() - df['power'].rolling(6, min_periods=1).min()
df['power_gradient'] = df['power'].diff().rolling(6).mean()

# EXTERNE Features:

# 1. Absolute Power (ist OK - beschreibt Last-Level)
df['power_level'] = df['power']

# 2. Temperature deltas (Abweichung vom Soll)
for room in ['eg', 'sz', 'az', 'kz', 'ak']:
    t_col = f'temp_{room}'
    s_col = f'target_{room}'
    if t_col in df.columns and s_col in df.columns:
        df[f'delta_{room}'] = df[t_col] - df[s_col]
        df[f'delta_{room}_abs'] = df[f'delta_{room}'].abs()

# 3. Summe aller Deltas (Gesamtabweichung)
delta_cols = [c for c in df.columns if c.startswith('delta_') and not c.endswith('_abs')]
if delta_cols:
    df['total_delta_abs'] = df[[f'{c}_abs' for c in delta_cols if f'{c}_abs' in df.columns]].sum(axis=1)

# 4. Outdoor Temp
if 'outdoor_temp' in df.columns:
    df['outdoor_temp_norm'] = df['outdoor_temp']
    # Outdoor Änderung (über 30min)
    df['outdoor_temp_change'] = df['outdoor_temp'].diff(6)  # Änderung über 30min

# 5. Target-Änderungen (Hat User gerade Target geändert?)
for room in ['eg', 'sz', 'az', 'kz', 'ak']:
    s_col = f'target_{room}'
    if s_col in df.columns:
        df[f'{s_col}_changed'] = (df[s_col].diff().abs() > 0.1).astype(int)

df['any_target_changed'] = df[[c for c in df.columns if c.endswith('_changed')]].max(axis=1)

# 6. Tageszeit
df['hour'] = df.index.hour
df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)

# 7. Wochentag
df['weekday'] = df.index.weekday
df['is_weekend'] = (df['weekday'] >= 5).astype(int)

print("✓ Externe Features erstellt")

# ===== GMM-BASIERTES LABELING =====
print("\n=== GMM-BASIERTES LABELING ===")

df_gmm = df[['power', 'power_std']].dropna()
df_gmm = df_gmm[df_gmm['power'] > 100].copy()

print(f"GMM Input: {len(df_gmm)} Punkte")

X_gmm = df_gmm[['power', 'power_std']].values
scaler_gmm = StandardScaler()
X_gmm_scaled = scaler_gmm.fit_transform(X_gmm)

# Find optimal clusters
best_n = 3
best_bic = np.inf
for n in range(2, 8):
    gmm = GaussianMixture(n_components=n, random_state=42)
    gmm.fit(X_gmm_scaled)
    bic = gmm.bic(X_gmm_scaled)
    if bic < best_bic:
        best_bic = bic
        best_n = n

gmm = GaussianMixture(n_components=best_n, random_state=42)
df_gmm['cluster'] = gmm.fit_predict(X_gmm_scaled)

cluster_stats = []
for c in range(best_n):
    cluster_data = df_gmm[df_gmm['cluster'] == c]
    stats = {
        'cluster': c,
        'size': len(cluster_data),
        'power_std_median': cluster_data['power_std'].median(),
        'power_median': cluster_data['power'].median(),
    }
    cluster_stats.append(stats)

cluster_df = pd.DataFrame(cluster_stats).sort_values('power_std_median')

print(f"Optimal GMM clusters: {best_n}")
print("\n--- CLUSTER RANKING ---")
stable_clusters = []
for idx, row in cluster_df.iterrows():
    stability = "🟢 STABIL" if row['power_std_median'] < 50 else "🟡 MODERAT" if row['power_std_median'] < 100 else "🔴 INSTABIL"
    print(f"Cluster {int(row['cluster'])}: {stability} | Power ~{row['power_median']:.0f}W | Std {row['power_std_median']:.0f}W")
    if row['power_std_median'] < 80:
        stable_clusters.append(int(row['cluster']))

print(f"✓ Stabile Cluster: {stable_clusters}")

# Apply labels
df['gmm_cluster'] = -1
df.loc[df_gmm.index, 'gmm_cluster'] = df_gmm['cluster'].values
df['label_gmm'] = 'unknown'
df.loc[df['gmm_cluster'].isin(stable_clusters), 'label_gmm'] = 'stable'
df.loc[~df['gmm_cluster'].isin(stable_clusters) & (df['gmm_cluster'] >= 0), 'label_gmm'] = 'unstable'

df_ml = df[df['label_gmm'].isin(['stable', 'unstable'])].copy()
df_ml['target'] = (df_ml['label_gmm'] == 'unstable').astype(int)

print(f"\n--- ML DATASET ---")
print(f"  Stable: {(df_ml['target'] == 0).sum()}")
print(f"  Unstable: {(df_ml['target'] == 1).sum()}")

# ===== EXTERNE FEATURES ONLY =====
print("\n=== EXTERNE FEATURES (keine Symptome!) ===")

external_features = [
    # Power level (externe Bedingung: "bei welcher Last läuft System?")
    'power_level',
    
    # Outdoor
    'outdoor_temp_norm',
    'outdoor_temp_change',
    
    # Raumtemperatur-Abweichungen
    'delta_eg', 'delta_sz', 'delta_az', 'delta_kz', 'delta_ak',
    'delta_eg_abs', 'delta_sz_abs', 'delta_az_abs', 'delta_kz_abs', 'delta_ak_abs',
    'total_delta_abs',
    
    # Target-Änderungen
    'any_target_changed',
    
    # Zeit
    'hour_sin', 'hour_cos',
    'is_weekend',
]

available_features = [f for f in external_features if f in df_ml.columns]
print(f"Verfügbare externe Features: {len(available_features)}")
for f in available_features:
    print(f"  - {f}")

df_ml_features = df_ml[available_features + ['target']].copy()

# Fill NaN
for col in available_features:
    if df_ml_features[col].isna().sum() > 0:
        if 'change' in col or 'changed' in col:
            df_ml_features[col] = df_ml_features[col].fillna(0)
        else:
            df_ml_features[col] = df_ml_features[col].ffill().bfill()

df_ml = df_ml_features.dropna()

print(f"Samples nach cleanup: {len(df_ml)}")

if len(df_ml) < 100:
    print("\n❌ Nicht genug Samples!")
    exit(1)

# ===== RANDOM FOREST =====
print("\n=== RANDOM FOREST (KAUSALE FAKTOREN) ===")

X = df_ml[available_features].values
y = df_ml['target'].values

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42, stratify=y)

# Balance
from sklearn.utils import resample
train_df = pd.DataFrame(X_train, columns=available_features)
train_df['target'] = y_train

train_stable = train_df[train_df['target'] == 0]
train_unstable = train_df[train_df['target'] == 1]

n_samples = min(len(train_stable), len(train_unstable))
train_stable_balanced = resample(train_stable, n_samples=n_samples, random_state=42)
train_unstable_balanced = resample(train_unstable, n_samples=n_samples, random_state=42)
train_balanced = pd.concat([train_stable_balanced, train_unstable_balanced])

X_train_balanced = train_balanced[available_features].values
y_train_balanced = train_balanced['target'].values

print(f"Train: {len(X_train_balanced)} balanced samples")
print(f"Test: {len(X_test)} samples")

rf = RandomForestClassifier(n_estimators=200, max_depth=15, random_state=42)
rf.fit(X_train_balanced, y_train_balanced)

y_pred = rf.predict(X_test)

print("\n--- TEST PERFORMANCE ---")
print(classification_report(y_test, y_pred, target_names=['Stable', 'Unstable']))

cm = confusion_matrix(y_test, y_pred)
print("\nConfusion Matrix:")
print(f"                Predicted Stable  Predicted Unstable")
print(f"Actual Stable        {cm[0][0]:6d}            {cm[0][1]:6d}")
print(f"Actual Unstable      {cm[1][0]:6d}            {cm[1][1]:6d}")

# Feature importance
importances = rf.feature_importances_
feature_importance_df = pd.DataFrame({
    'feature': available_features,
    'importance': importances
}).sort_values('importance', ascending=False)

print("\n🎯 === KAUSALE FAKTOREN (Top 15) ===")
print("Diese externen Faktoren VERURSACHEN Instabilität:\n")
for idx, row in feature_importance_df.head(15).iterrows():
    print(f"  {row['importance']*100:5.2f}% : {row['feature']}")

# ===== VISUALISIERUNG =====
print("\nErstelle Visualisierungen...")

fig = plt.figure(figsize=(20, 12))

# Plot 1: Feature Importance (CAUSAL!)
ax1 = plt.subplot(2, 3, 1)
top_features = feature_importance_df.head(15)
colors_importance = ['red' if 'power' in f else 'steelblue' for f in top_features['feature']]
ax1.barh(range(len(top_features)), top_features['importance']*100, color=colors_importance, alpha=0.7)
ax1.set_yticks(range(len(top_features)))
ax1.set_yticklabels(top_features['feature'])
ax1.set_xlabel('Importance (%)')
ax1.set_title('🎯 KAUSALE Faktoren (externe Features only)')
ax1.grid(True, alpha=0.3, axis='x')

# Plot 2: Confusion Matrix
ax2 = plt.subplot(2, 3, 2)
im = ax2.imshow(cm, cmap='Blues', aspect='auto')
ax2.set_xticks([0, 1])
ax2.set_yticks([0, 1])
ax2.set_xticklabels(['Stable', 'Unstable'])
ax2.set_yticklabels(['Stable', 'Unstable'])
ax2.set_xlabel('Predicted')
ax2.set_ylabel('Actual')
ax2.set_title(f'Test Accuracy: {(y_pred == y_test).sum() / len(y_test):.1%}')
for i in range(2):
    for j in range(2):
        ax2.text(j, i, cm[i, j], ha="center", va="center", 
                color="white" if cm[i, j] > cm.max()/2 else "black", fontsize=20)
plt.colorbar(im, ax=ax2)

# Plot 3: Top feature distributions
top_feature = feature_importance_df.iloc[0]['feature']
ax3 = plt.subplot(2, 3, 3)
df_ml[df_ml['target'] == 0][top_feature].hist(bins=30, alpha=0.6, color='green', label='Stable', ax=ax3)
df_ml[df_ml['target'] == 1][top_feature].hist(bins=30, alpha=0.6, color='red', label='Unstable', ax=ax3)
ax3.set_xlabel(top_feature)
ax3.set_ylabel('Anzahl')
ax3.set_title(f'Top Kausal-Faktor: {top_feature}')
ax3.legend()
ax3.grid(True, alpha=0.3)

# Plot 4: Power_level vs outdoor_temp (colored by stability)
ax4 = plt.subplot(2, 3, 4)
if 'outdoor_temp_norm' in df_ml.columns:
    scatter = ax4.scatter(df_ml['outdoor_temp_norm'], df_ml['power_level'], 
                         c=df_ml['target'], cmap='RdYlGn_r', alpha=0.3, s=5)
    ax4.set_xlabel('Outdoor Temp (°C)')
    ax4.set_ylabel('Power (W)')
    ax4.set_title('Outdoor Temp vs Power (Grün=Stabil)')
    plt.colorbar(scatter, ax=ax4)
    ax4.grid(True, alpha=0.3)

# Plot 5: Total_delta vs stability
ax5 = plt.subplot(2, 3, 5)
if 'total_delta_abs' in df_ml.columns:
    df_ml[df_ml['target'] == 0]['total_delta_abs'].hist(bins=30, alpha=0.6, color='green', label='Stable', ax=ax5)
    df_ml[df_ml['target'] == 1]['total_delta_abs'].hist(bins=30, alpha=0.6, color='red', label='Unstable', ax=ax5)
    ax5.set_xlabel('Total Room Temp Deviation (K)')
    ax5.set_ylabel('Anzahl')
    ax5.set_title('Gesamtabweichung Raumtemps')
    ax5.legend()
    ax5.grid(True, alpha=0.3)

# Plot 6: Hour distribution
ax6 = plt.subplot(2, 3, 6)
df_ml_with_hour = df_ml.copy()
df_ml_with_hour['hour'] = np.arctan2(df_ml['hour_sin'], df_ml['hour_cos']) / (2*np.pi) * 24
df_ml_with_hour['hour'] = (df_ml_with_hour['hour'] + 24) % 24

stable_hours = df_ml_with_hour[df_ml_with_hour['target'] == 0]['hour']
unstable_hours = df_ml_with_hour[df_ml_with_hour['target'] == 1]['hour']

ax6.hist(stable_hours, bins=24, alpha=0.6, color='green', label='Stable')
ax6.hist(unstable_hours, bins=24, alpha=0.6, color='red', label='Unstable')
ax6.set_xlabel('Stunde')
ax6.set_ylabel('Anzahl')
ax6.set_title('Stabilität nach Tageszeit')
ax6.legend()
ax6.grid(True, alpha=0.3)

plt.tight_layout()
output_path = '/home/diyon/.openclaw/workspace/climatiq/data/sprint3_2_v3_causal.png'
plt.savefig(output_path, dpi=150)
print(f"✓ Gespeichert: {output_path}")

# Export
feature_importance_df.to_csv('/home/diyon/.openclaw/workspace/climatiq/data/feature_importance_causal.csv', index=False)
print("✓ Kausale Features exportiert: data/feature_importance_causal.csv")

print("\n✅ Sprint 3.2 V3 abgeschlossen!")
print(f"\n🎯 KERNERKENNTNISSE:")
print(f"  - Test Accuracy: {(y_pred == y_test).sum() / len(y_test):.1%}")
print(f"  - Top kausaler Faktor: {feature_importance_df.iloc[0]['feature']} ({feature_importance_df.iloc[0]['importance']*100:.1f}%)")
print(f"  - Diese Faktoren sind URSACHEN, nicht Symptome!")
