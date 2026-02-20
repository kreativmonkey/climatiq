#!/usr/bin/env python3
"""Deep Transition Analysis: What causes stable→unstable shifts?"""

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
from datetime import datetime, timedelta

import matplotlib.pyplot as plt

from climatiq.data.influx_v1_client import InfluxV1Client

client = InfluxV1Client()

DAYS = 60  # Last 60 days for good sample size
end = datetime.now()
start = end - timedelta(days=DAYS)

print(f"=== Deep Transition Analysis ({DAYS} Tage) ===\n")

# ============================================================
# 1. Lade alle relevanten Daten (5-min Auflösung für Speed)
# ============================================================
print("Lade Daten...")

entities = {
    "power": "ac_current_energy",
    "outdoor_temp": "ac_temperatur_outdoor",
    # Target Temperatures (Panasonic API)
    "target_eg": "panasonic_climate_erdgeschoss_target_temperature",
    "target_sz": "panasonic_climate_schlafzimmer_target_temperature",
    "target_az": "panasonic_climate_arbeitszimmer_target_temperature",
    "target_kz": "panasonic_climate_kinderzimmer_target_temperature",
    "target_ak": "panasonic_climate_ankleide_target_temperature",
    # Room Temperatures (measured)
    "room_eg": "erdgeschoss",
    "room_sz": "schlafzimmer",
    "room_az": "arbeitszimmer",
    "room_kz": "kinderzimmer",
    "room_ak": "ankleide",
    # Unit On/Off (Ein/Aus)
    "unit_eg": "ac_erdgeschoss_ac_ein_aus",
    "unit_sz": "ac_schlafzimmer_e_a",
    "unit_az": "ac_arbeitszimmer_ac_eine_aus",
    "unit_kz": "ac_kinderzimmer_e_a",
    "unit_ak": "ac_ankleidezimmer_e_a",
    # Fanspeed
    "fan_eg": "ac_erdgeschoss_fanspeed_mode",
}

data = {}
for key, entity in entities.items():
    df = client.get_entity_data(entity, start, end, resample="5m")
    if not df.empty:
        data[key] = df["value"]
        print(f"  ✓ {key}: {len(df)} points")
    else:
        print(f"  ✗ {key}: keine Daten")

if "power" not in data:
    print("FEHLER: Keine Power-Daten!")
    exit(1)

# Combine into single DataFrame
df = pd.DataFrame(data)
df = df.sort_index()
print(f"\nGesamt: {len(df)} Zeitpunkte, {len(data)} Kanäle")

# ============================================================
# 2. Berechne Stabilitätsmetriken
# ============================================================
print("\nBerechne Stabilität...")

df["power_std"] = df["power"].rolling(6, min_periods=1).std()  # 30 min window (6 x 5min)
df["power_spread"] = (
    df["power"].rolling(6, min_periods=1).max() - df["power"].rolling(6, min_periods=1).min()
)

# Classify phases
df["phase"] = "neutral"
df.loc[df["power_std"] < 50, "phase"] = "stable"
df.loc[df["power_std"] > 120, "phase"] = "unstable"

# Count active units (assume >0 means on)
unit_cols = [c for c in df.columns if c.startswith("unit_")]
for col in unit_cols:
    df[col] = pd.to_numeric(df[col], errors="coerce")
df["active_units"] = sum(
    df[col].fillna(0).astype(bool).astype(int) for col in unit_cols if col in df.columns
)

# ============================================================
# 3. Finde Übergänge (Stable → Unstable)
# ============================================================
print("Finde Übergänge...")

df["prev_phase"] = df["phase"].shift(1)
df["transition_to_unstable"] = (df["prev_phase"] == "stable") & (df["phase"] == "unstable")
df["transition_to_stable"] = (df["prev_phase"] == "unstable") & (df["phase"] == "stable")

trans_unstable = df[df["transition_to_unstable"]].index.tolist()
trans_stable = df[df["transition_to_stable"]].index.tolist()

print(f"  Stable → Unstable: {len(trans_unstable)}")
print(f"  Unstable → Stable: {len(trans_stable)}")

# ============================================================
# 4. Analysiere Parameter bei Übergängen
# ============================================================
print("\n=== ANALYSE: Was passiert bei Übergängen? ===\n")

# Für jeden Übergang: Snapshot 10 min vorher vs. 10 min nachher
results = []
for t in trans_unstable:
    before_start = t - pd.Timedelta(minutes=30)
    before_end = t
    after_start = t
    after_end = t + pd.Timedelta(minutes=30)

    row = {"timestamp": t}

    # Power
    row["power_before"] = df.loc[before_start:before_end, "power"].mean()
    row["power_after"] = df.loc[after_start:after_end, "power"].mean()

    # Outdoor temp
    if "outdoor_temp" in df.columns:
        row["outdoor_before"] = df.loc[before_start:before_end, "outdoor_temp"].mean()
        row["outdoor_after"] = df.loc[after_start:after_end, "outdoor_temp"].mean()
        row["outdoor_delta"] = row.get("outdoor_after", 0) - row.get("outdoor_before", 0)

    # Active units
    row["units_before"] = df.loc[before_start:before_end, "active_units"].mean()
    row["units_after"] = df.loc[after_start:after_end, "active_units"].mean()
    row["units_delta"] = row["units_after"] - row["units_before"]

    # Target temperatures
    for unit_key in ["target_eg", "target_sz", "target_az", "target_kz", "target_ak"]:
        if unit_key in df.columns:
            before_val = df.loc[before_start:before_end, unit_key].mean()
            after_val = df.loc[after_start:after_end, unit_key].mean()
            row[f"{unit_key}_delta"] = after_val - before_val

    # Room temperatures
    for room_key in ["room_eg", "room_sz", "room_az", "room_kz", "room_ak"]:
        if room_key in df.columns:
            before_val = df.loc[before_start:before_end, room_key].mean()
            after_val = df.loc[after_start:after_end, room_key].mean()
            row[f"{room_key}_delta"] = after_val - before_val

    results.append(row)

res_df = pd.DataFrame(results)

if len(res_df) == 0:
    print("Keine Übergänge gefunden!")
    exit()

# ============================================================
# 5. Statistische Auswertung
# ============================================================
print(f"Analysiert: {len(res_df)} Übergänge (Stabil → Instabil)\n")

print("--- POWER ---")
print(f"  Vor Übergang (Ø): {res_df['power_before'].mean():.0f} W")
print(f"  Nach Übergang (Ø): {res_df['power_after'].mean():.0f} W")
print(f"  Delta: +{(res_df['power_after'] - res_df['power_before']).mean():.0f} W")

if "outdoor_before" in res_df.columns:
    print("\n--- AUßENTEMPERATUR ---")
    print(f"  Vor Übergang (Ø): {res_df['outdoor_before'].mean():.1f} °C")
    print(f"  Nach Übergang (Ø): {res_df['outdoor_after'].mean():.1f} °C")
    print(f"  Delta (Ø): {res_df['outdoor_delta'].mean():+.2f} °C")

print("\n--- AKTIVE GERÄTE ---")
print(f"  Vor Übergang (Ø): {res_df['units_before'].mean():.1f}")
print(f"  Nach Übergang (Ø): {res_df['units_after'].mean():.1f}")
print(f"  Delta (Ø): {res_df['units_delta'].mean():+.2f}")

# Welche Zieltemperaturen haben sich geändert?
print("\n--- ZIELTEMPERATUR-ÄNDERUNGEN ---")
target_deltas = [c for c in res_df.columns if c.startswith("target_") and c.endswith("_delta")]
for col in target_deltas:
    room = col.replace("target_", "").replace("_delta", "")
    mean_delta = res_df[col].mean()
    nonzero = (res_df[col].abs() > 0.1).sum()
    print(f"  {room}: Ø {mean_delta:+.2f}°C, {nonzero} Änderungen in {len(res_df)} Übergängen")

# Raumtemperatur-Deltas
print("\n--- RAUMTEMPERATUR-ÄNDERUNGEN ---")
room_deltas = [c for c in res_df.columns if c.startswith("room_") and c.endswith("_delta")]
for col in room_deltas:
    room = col.replace("room_", "").replace("_delta", "")
    mean_delta = res_df[col].mean()
    print(f"  {room}: Ø {mean_delta:+.3f}°C")

# ============================================================
# 6. Korrelationsanalyse
# ============================================================
print("\n=== KORRELATION mit Instabilität ===\n")

# Welche Faktoren korrelieren am stärksten mit Power-Anstieg?
numeric_cols = res_df.select_dtypes(include=[np.number]).columns.tolist()
power_delta = res_df["power_after"] - res_df["power_before"]

print("Korrelation mit Power-Anstieg bei Übergang:")
correlations = {}
for col in numeric_cols:
    if col in ["power_before", "power_after", "timestamp"]:
        continue
    try:
        corr = power_delta.corr(res_df[col])
        if not pd.isna(corr):
            correlations[col] = corr
    except:
        pass

sorted_corr = sorted(correlations.items(), key=lambda x: abs(x[1]), reverse=True)
for name, corr in sorted_corr[:10]:
    direction = "↑↑" if corr > 0.3 else "↓↓" if corr < -0.3 else "  "
    print(f"  {direction} {name}: r={corr:+.3f}")

# ============================================================
# 7. Visualisierung
# ============================================================
print("\nErstelle Visualisierungen...")

fig, axes = plt.subplots(2, 2, figsize=(16, 12))

# Plot 1: Power Distribution at Transitions
ax1 = axes[0][0]
ax1.hist(res_df["power_before"].dropna(), bins=20, alpha=0.7, label="Vor Übergang", color="green")
ax1.hist(res_df["power_after"].dropna(), bins=20, alpha=0.7, label="Nach Übergang", color="red")
ax1.set_xlabel("Power (W)")
ax1.set_ylabel("Anzahl Übergänge")
ax1.set_title("Power vor/nach Stabilitätsverlust")
ax1.legend()
ax1.grid(True, alpha=0.3)

# Plot 2: Active Units Distribution
ax2 = axes[0][1]
ax2.hist(res_df["units_before"].dropna(), bins=10, alpha=0.7, label="Vor Übergang", color="green")
ax2.hist(res_df["units_after"].dropna(), bins=10, alpha=0.7, label="Nach Übergang", color="red")
ax2.set_xlabel("Aktive Geräte")
ax2.set_ylabel("Anzahl Übergänge")
ax2.set_title("Aktive Geräte vor/nach Stabilitätsverlust")
ax2.legend()
ax2.grid(True, alpha=0.3)

# Plot 3: Outdoor Temp at Transitions
ax3 = axes[1][0]
if "outdoor_before" in res_df.columns:
    ax3.scatter(
        res_df["outdoor_before"], res_df["power_before"], alpha=0.5, c="green", label="Stabil"
    )
    ax3.scatter(
        res_df["outdoor_after"], res_df["power_after"], alpha=0.5, c="red", label="Instabil"
    )
    ax3.set_xlabel("Außentemperatur (°C)")
    ax3.set_ylabel("Power (W)")
    ax3.set_title("Außentemperatur vs. Power bei Übergängen")
    ax3.legend()
    ax3.grid(True, alpha=0.3)

# Plot 4: Correlation Heatmap (Top Factors)
ax4 = axes[1][1]
top_factors = [name for name, _ in sorted_corr[:8]]
if top_factors:
    corr_values = [correlations[f] for f in top_factors]
    colors = ["red" if v > 0 else "blue" for v in corr_values]
    bars = ax4.barh(top_factors, corr_values, color=colors, alpha=0.7)
    ax4.set_xlabel("Korrelation mit Power-Anstieg")
    ax4.set_title("Top Faktoren für Instabilität")
    ax4.axvline(x=0, color="black", linewidth=0.5)
    ax4.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig("/home/diyon/.openclaw/workspace/climatiq/data/transition_analysis_deep.png", dpi=150)
print("✓ Gespeichert: data/transition_analysis_deep.png")

# ============================================================
# 8. Stabile Kombinationen finden
# ============================================================
print("\n=== STABILE PARAMETER-KOMBINATIONEN ===\n")

# Finde Zeiträume die >30 min stabil waren
df["stable_run"] = (df["phase"] == "stable").astype(int)
df["stable_group"] = (df["stable_run"] != df["stable_run"].shift()).cumsum()

stable_runs = df[df["phase"] == "stable"].groupby("stable_group")

long_stable = []
for gid, group in stable_runs:
    if len(group) >= 6:  # >= 30 min (6 x 5min)
        row = {
            "start": group.index[0],
            "end": group.index[-1],
            "duration_min": len(group) * 5,
            "power_mean": group["power"].mean(),
            "power_std": group["power_std"].mean(),
        }
        if "outdoor_temp" in group.columns:
            row["outdoor"] = group["outdoor_temp"].mean()
        row["active_units"] = group["active_units"].mean()

        for tgt in ["target_eg", "target_sz", "target_az", "target_kz", "target_ak"]:
            if tgt in group.columns:
                row[tgt] = group[tgt].mean()

        long_stable.append(row)

stable_df = pd.DataFrame(long_stable)

if len(stable_df) > 0:
    print(f"Gefunden: {len(stable_df)} stabile Episoden (>30 min)\n")
    print("Durchschnittliche stabile Konfiguration:")
    print(
        f"  Power: {stable_df['power_mean'].mean():.0f} W (Std: {stable_df['power_std'].mean():.1f} W)"
    )
    print(f"  Dauer: {stable_df['duration_min'].mean():.0f} min")
    print(f"  Aktive Geräte: {stable_df['active_units'].mean():.1f}")
    if "outdoor" in stable_df.columns:
        print(f"  Außentemp: {stable_df['outdoor'].mean():.1f} °C")

    for tgt in ["target_eg", "target_sz", "target_az", "target_kz", "target_ak"]:
        if tgt in stable_df.columns:
            room = tgt.replace("target_", "")
            print(f"  Zieltemp {room}: {stable_df[tgt].mean():.1f} °C")

    print(f"\n  Längste stabile Episode: {stable_df['duration_min'].max():.0f} min")
    print(f"  Kürzeste: {stable_df['duration_min'].min():.0f} min")
else:
    print("Keine stabilen Episoden >30 min gefunden!")

print("\n✅ Analyse abgeschlossen.")
