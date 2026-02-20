#!/usr/bin/env python3
"""Sprint 3.2 V2: ML Feature Importance mit GMM-basiertem Labeling"""

import pandas as pd
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.mixture import GaussianMixture
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix
from climatiq.data.influx_v1_client import InfluxV1Client

client = InfluxV1Client()

DAYS = 60
end = datetime.now()
start = end - timedelta(days=DAYS)

print(f"=== SPRINT 3.2 V2: ML mit GMM-Labeling ({DAYS} Tage) ===\n")

# ===== DATEN LADEN =====
entities = {
    "power": "ac_current_energy",
    "outdoor_temp": "ac_temperatur_outdoor",
    "temp_eg": "temperatur_wohnzimmer",
    "temp_sz": "temperatur_flur_og",
    "temp_az": "rwm_arbeitszimmer_temperature",
    "temp_kz": "0x000d6f0019c90b85_temperature",
    "temp_ak": "temperatur_flur_og",
    "target_eg": "panasonic_climate_erdgeschoss_desired_temperature",
    "target_sz": "panasonic_climate_schlafzimmer_desired_temperature",
    "target_az": "panasonic_climate_arbeitszimmer_desired_temperature",
    "target_kz": "panasonic_climate_kinderzimmer_desired_temperature",
    "target_ak": "panasonic_climate_ankleide_desired_temperature",
}

print("Lade Daten (5min Auflösung)...")
data = {}
for key, entity in entities.items():
    df_ent = client.get_entity_data(entity, start, end, resample="5m")
    if not df_ent.empty:
        data[key] = df_ent["value"]

df = pd.DataFrame(data).sort_index()

# Forward-fill targets
for col in [c for c in df.columns if c.startswith("target_")]:
    df[col] = df[col].ffill()

print(f"Dataset: {len(df)} Zeitpunkte")

# ===== FEATURE ENGINEERING =====
print("\nFeature Engineering...")

# Power features
df["power_std"] = df["power"].rolling(6, min_periods=1).std()
df["power_gradient"] = df["power"].diff().rolling(6).mean()
df["power_spread"] = (
    df["power"].rolling(6, min_periods=1).max() - df["power"].rolling(6, min_periods=1).min()
)

# Temperature deltas
for room in ["eg", "sz", "az", "kz", "ak"]:
    t_col = f"temp_{room}"
    s_col = f"target_{room}"
    if t_col in df.columns and s_col in df.columns:
        df[f"delta_{room}"] = df[t_col] - df[s_col]
        df[f"delta_{room}_abs"] = df[f"delta_{room}"].abs()

# Outdoor
if "outdoor_temp" in df.columns:
    df["outdoor_gradient"] = df["outdoor_temp"].diff().rolling(6).mean()

# Hour
df["hour"] = df.index.hour
df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)

# ===== GMM-BASIERTES LABELING =====
print("\n=== GMM-BASIERTES LABELING ===")

# Prepare data for GMM (only power + power_std, exclude system-off)
df_gmm = df[["power", "power_std"]].dropna()
df_gmm = df_gmm[df_gmm["power"] > 100].copy()  # Anlage läuft

print(f"GMM Input: {len(df_gmm)} Punkte (power > 100W)")

X_gmm = df_gmm[["power", "power_std"]].values
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

print(f"Optimal GMM clusters: {best_n}")

gmm = GaussianMixture(n_components=best_n, random_state=42)
df_gmm["cluster"] = gmm.fit_predict(X_gmm_scaled)

# Analyze clusters
cluster_stats = []
for c in range(best_n):
    cluster_data = df_gmm[df_gmm["cluster"] == c]
    stats = {
        "cluster": c,
        "size": len(cluster_data),
        "power_std_median": cluster_data["power_std"].median(),
        "power_median": cluster_data["power"].median(),
    }
    cluster_stats.append(stats)

cluster_df = pd.DataFrame(cluster_stats).sort_values("power_std_median")

print("\n--- CLUSTER RANKING (nach Stabilität) ---")
stable_clusters = []
for idx, row in cluster_df.iterrows():
    stability = (
        "🟢 STABIL"
        if row["power_std_median"] < 50
        else "🟡 MODERAT" if row["power_std_median"] < 100 else "🔴 INSTABIL"
    )
    print(
        f"Cluster {int(row['cluster'])}: {stability} | Power ~{row['power_median']:.0f}W | Std {row['power_std_median']:.0f}W"
    )
    if row["power_std_median"] < 80:  # Accept both stable + moderate
        stable_clusters.append(int(row["cluster"]))

print(f"\n✓ Stabile Cluster: {stable_clusters}")

# Apply labels to main dataframe
df["gmm_cluster"] = -1
df.loc[df_gmm.index, "gmm_cluster"] = df_gmm["cluster"].values
df["label_gmm"] = "unknown"
df.loc[df["gmm_cluster"].isin(stable_clusters), "label_gmm"] = "stable"
df.loc[~df["gmm_cluster"].isin(stable_clusters) & (df["gmm_cluster"] >= 0), "label_gmm"] = (
    "unstable"
)

# Prepare ML dataset
df_ml = df[df["label_gmm"].isin(["stable", "unstable"])].copy()
df_ml["target"] = (df_ml["label_gmm"] == "unstable").astype(int)

print(f"\n--- ML DATASET ---")
print(f"  Stable: {(df_ml['target'] == 0).sum()}")
print(f"  Unstable: {(df_ml['target'] == 1).sum()}")

# ===== FEATURE SELECTION =====
feature_cols = [
    "power",
    "power_std",
    "power_gradient",
    "power_spread",
    "outdoor_temp",
    "outdoor_gradient",
    "delta_eg",
    "delta_sz",
    "delta_az",
    "delta_kz",
    "delta_ak",
    "delta_eg_abs",
    "delta_sz_abs",
    "delta_az_abs",
    "delta_kz_abs",
    "delta_ak_abs",
    "hour_sin",
    "hour_cos",
]

available_features = [f for f in feature_cols if f in df_ml.columns]
df_ml_features = df_ml[available_features + ["target"]].copy()

# Fill NaN
for col in available_features:
    if df_ml_features[col].isna().sum() > 0:
        if "gradient" in col:
            df_ml_features[col] = df_ml_features[col].fillna(0)
        else:
            df_ml_features[col] = df_ml_features[col].ffill().bfill()

df_ml = df_ml_features.dropna()

print(f"Features: {len(available_features)}")
print(f"Samples after cleanup: {len(df_ml)}")

if len(df_ml) < 100:
    print("\n❌ Nicht genug Samples!")
    exit(1)

# ===== RANDOM FOREST TRAINING =====
print("\n=== RANDOM FOREST TRAINING ===")

X = df_ml[available_features].values
y = df_ml["target"].values

# Train/Test Split
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.3, random_state=42, stratify=y
)

print(f"Train: {len(X_train)} samples")
print(f"Test: {len(X_test)} samples")

# Balance training set
from sklearn.utils import resample

train_df = pd.DataFrame(X_train, columns=available_features)
train_df["target"] = y_train

train_stable = train_df[train_df["target"] == 0]
train_unstable = train_df[train_df["target"] == 1]

n_samples = min(len(train_stable), len(train_unstable))
train_stable_balanced = resample(train_stable, n_samples=n_samples, random_state=42)
train_unstable_balanced = resample(train_unstable, n_samples=n_samples, random_state=42)
train_balanced = pd.concat([train_stable_balanced, train_unstable_balanced])

X_train_balanced = train_balanced[available_features].values
y_train_balanced = train_balanced["target"].values

print(f"Balanced train: {len(X_train_balanced)} samples")

# Train
rf = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42)
rf.fit(X_train_balanced, y_train_balanced)

# Evaluate
y_pred = rf.predict(X_test)
print("\n--- TEST SET PERFORMANCE ---")
print(classification_report(y_test, y_pred, target_names=["Stable", "Unstable"]))

cm = confusion_matrix(y_test, y_pred)
print("\nConfusion Matrix:")
print(f"                Predicted Stable  Predicted Unstable")
print(f"Actual Stable        {cm[0][0]:6d}            {cm[0][1]:6d}")
print(f"Actual Unstable      {cm[1][0]:6d}            {cm[1][1]:6d}")

# Feature importance
importances = rf.feature_importances_
feature_importance_df = pd.DataFrame(
    {"feature": available_features, "importance": importances}
).sort_values("importance", ascending=False)

print("\n--- TOP 15 FEATURE IMPORTANCE ---")
for idx, row in feature_importance_df.head(15).iterrows():
    print(f"  {row['importance']:.3f} : {row['feature']}")

# ===== VISUALISIERUNG =====
print("\nErstelle Visualisierungen...")

fig = plt.figure(figsize=(20, 12))

# Plot 1: Feature Importance
ax1 = plt.subplot(2, 3, 1)
top_features = feature_importance_df.head(15)
ax1.barh(range(len(top_features)), top_features["importance"], color="steelblue", alpha=0.7)
ax1.set_yticks(range(len(top_features)))
ax1.set_yticklabels(top_features["feature"])
ax1.set_xlabel("Importance")
ax1.set_title("Top 15 Features (GMM-labeled)")
ax1.grid(True, alpha=0.3, axis="x")

# Plot 2: GMM Clusters
ax2 = plt.subplot(2, 3, 2)
colors = ["green" if c in stable_clusters else "red" for c in df_gmm["cluster"]]
ax2.scatter(df_gmm["power"], df_gmm["power_std"], c=colors, alpha=0.3, s=5)
ax2.set_xlabel("Power (W)")
ax2.set_ylabel("Power Std (W)")
ax2.set_title(f"GMM Clusters (Grün=Stabil)")
ax2.grid(True, alpha=0.3)
ax2.axhline(y=50, color="black", linestyle="--", alpha=0.5, label="Std=50W")
ax2.legend()

# Plot 3: Confusion Matrix Heatmap
ax3 = plt.subplot(2, 3, 3)
im = ax3.imshow(cm, cmap="Blues", aspect="auto")
ax3.set_xticks([0, 1])
ax3.set_yticks([0, 1])
ax3.set_xticklabels(["Stable", "Unstable"])
ax3.set_yticklabels(["Stable", "Unstable"])
ax3.set_xlabel("Predicted")
ax3.set_ylabel("Actual")
ax3.set_title("Confusion Matrix")
for i in range(2):
    for j in range(2):
        text = ax3.text(
            j,
            i,
            cm[i, j],
            ha="center",
            va="center",
            color="white" if cm[i, j] > cm.max() / 2 else "black",
            fontsize=20,
        )
plt.colorbar(im, ax=ax3)

# Plot 4: Power distribution per label
ax4 = plt.subplot(2, 3, 4)
df_ml[df_ml["target"] == 0]["power"].hist(bins=30, alpha=0.6, color="green", label="Stable", ax=ax4)
df_ml[df_ml["target"] == 1]["power"].hist(bins=30, alpha=0.6, color="red", label="Unstable", ax=ax4)
ax4.set_xlabel("Power (W)")
ax4.set_ylabel("Anzahl")
ax4.set_title("Power Distribution (GMM-labeled)")
ax4.legend()
ax4.grid(True, alpha=0.3)

# Plot 5: Top feature vs power_std
top_feature = feature_importance_df.iloc[0]["feature"]
ax5 = plt.subplot(2, 3, 5)
ax5.scatter(
    df_ml[top_feature], df_ml["power_std"], c=df_ml["target"], cmap="RdYlGn_r", alpha=0.3, s=10
)
ax5.set_xlabel(top_feature)
ax5.set_ylabel("Power Std (W)")
ax5.set_title(f"{top_feature} vs Power Std")
ax5.grid(True, alpha=0.3)

# Plot 6: Cluster characteristics
ax6 = plt.subplot(2, 3, 6)
for idx, row in cluster_df.iterrows():
    color = "green" if row["cluster"] in stable_clusters else "red"
    ax6.scatter(
        row["power_median"],
        row["power_std_median"],
        s=row["size"] / 2,
        alpha=0.7,
        color=color,
        label=f"C{int(row['cluster'])}",
    )
ax6.set_xlabel("Median Power (W)")
ax6.set_ylabel("Median Power Std (W)")
ax6.set_title("GMM Cluster Centroids")
ax6.axhline(y=50, color="black", linestyle="--", alpha=0.5)
ax6.grid(True, alpha=0.3)
ax6.legend()

plt.tight_layout()
output_path = "/home/diyon/.openclaw/workspace/climatiq/data/sprint3_2_v2_gmm.png"
plt.savefig(output_path, dpi=150)
print(f"✓ Gespeichert: {output_path}")

# Export
feature_importance_df.to_csv(
    "/home/diyon/.openclaw/workspace/climatiq/data/feature_importance_gmm.csv", index=False
)
print("✓ Feature Importance exportiert: data/feature_importance_gmm.csv")

print("\n✅ Sprint 3.2 V2 abgeschlossen!")
print(f"\n🎯 KEY FINDINGS:")
print(f"  - Test Accuracy: {(y_pred == y_test).sum() / len(y_test):.1%}")
print(
    f"  - Top Feature: {feature_importance_df.iloc[0]['feature']} ({feature_importance_df.iloc[0]['importance']:.3f})"
)
print(f"  - Stable Clusters: {stable_clusters} (Power-unabhängig!)")
