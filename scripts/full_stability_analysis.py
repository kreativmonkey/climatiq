#!/usr/bin/env python3
"""Vollständige Stabilitätsanalyse mit Climate State Data aus InfluxDB"""

import pandas as pd
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from climatiq.data.influx_v1_client import InfluxV1Client

client = InfluxV1Client()

DAYS = 30  # 30 Tage für gute Balance zwischen Datenmenge und Relevanz
end = datetime.now()
start = end - timedelta(days=DAYS)

print(f"=== VOLLSTÄNDIGE STABILITÄTSANALYSE ({DAYS} Tage) ===\n")
print("Datenquellen:")
print("  - state Measurement: Climate-Entities (target_temp, hvac_mode, fan_mode)")
print("  - °C Measurement: Temperatursensoren")
print("  - W Measurement: Power\n")

# ============================================================
# 1. CLIMATE STATE DATA (aus 'state' Measurement)
# ============================================================
print("Lade Climate State Data...")

climate_entities = ["ac_erdgeschoss", "ac_arbeitszimmer"]
climate_data = {}

for entity in climate_entities:
    query = f"""
    SELECT current_temperature, temperature, fan_mode, state, hvac_action_str, preset_mode_str
    FROM "state" 
    WHERE entity_id = '{entity}' 
    AND time >= '{start.strftime("%Y-%m-%dT%H:%M:%SZ")}' 
    AND time <= '{end.strftime("%Y-%m-%dT%H:%M:%SZ")}'
    """

    result = client._query(query)
    if "results" in result and result["results"]:
        series = result["results"][0].get("series", [])
        if series:
            columns = series[0].get("columns", [])
            values = series[0].get("values", [])

            df = pd.DataFrame(values, columns=columns)
            df["time"] = pd.to_datetime(df["time"])
            df = df.set_index("time")

            room = entity.replace("ac_", "")
            climate_data[f"{room}_current_temp"] = df["current_temperature"]
            climate_data[f"{room}_target_temp"] = df["temperature"]
            climate_data[f"{room}_fan_mode"] = df["fan_mode"]
            climate_data[f"{room}_hvac_state"] = df["state"]
            climate_data[f"{room}_hvac_action"] = df["hvac_action_str"]

            print(f"  ✓ {entity}: {len(df)} Punkte")
        else:
            print(f"  ✗ {entity}: keine Daten")

# ============================================================
# 2. SENSOR DATA (°C und W Measurements)
# ============================================================
print("\nLade Sensor Data (5min resample)...")

sensor_entities = {
    "power": "ac_current_energy",
    "outdoor_temp": "ac_temperatur_outdoor",
    "path_eg": "ac_erdgeschoss_path_temperatur",
    "path_sz": "ac_schlafzimmer_path_temperatur",
    "path_az": "ac_arbeitszimmer_path_temperatur",
    "path_kz": "ac_kinderzimmer_path_temperatur",
    "path_ak": "ac_ankleide_path_temperatur",
}

sensor_data = {}
for key, entity in sensor_entities.items():
    df = client.get_entity_data(entity, start, end, resample="5m")
    if not df.empty:
        sensor_data[key] = df["value"]
        print(f"  ✓ {key}: {len(df)} Punkte")

# ============================================================
# 3. KOMBINIERE ALLE DATEN
# ============================================================
print("\nKombiniere Datenquellen...")

# Resample climate data to 5min to match sensor data
climate_df = pd.DataFrame(climate_data)
climate_df = climate_df.resample("5min").ffill()  # Forward-fill für state data

sensor_df = pd.DataFrame(sensor_data)

# Merge
df = pd.concat([sensor_df, climate_df], axis=1)
df = df.sort_index()

print(f"  Kombinierter Datensatz: {len(df)} Zeitpunkte, {len(df.columns)} Spalten")

if "power" not in df.columns:
    print("\nFEHLER: Keine Power-Daten!")
    exit(1)

# ============================================================
# 4. STABILITÄTSMETRIKEN
# ============================================================
print("\nBerechne Stabilität...")

df["power_std"] = df["power"].rolling(6, min_periods=1).std()
df["power_spread"] = (
    df["power"].rolling(6, min_periods=1).max() - df["power"].rolling(6, min_periods=1).min()
)
df["power_gradient"] = df["power"].diff().rolling(6).mean()

# Klassifizierung
df["phase"] = "neutral"
df.loc[df["power_std"] < 50, "phase"] = "stable"
df.loc[df["power_std"] > 120, "phase"] = "unstable"

# ============================================================
# 5. ÜBERGÄNGE FINDEN
# ============================================================
print("\nFinde Übergänge...")

df["prev_phase"] = df["phase"].shift(1)
df["transition_to_unstable"] = (df["prev_phase"] == "stable") & (df["phase"] == "unstable")
df["transition_to_stable"] = (df["prev_phase"] == "unstable") & (df["phase"] == "stable")

trans_unstable = df[df["transition_to_unstable"]].index.tolist()
trans_stable = df[df["transition_to_stable"]].index.tolist()

print(f"  Stable → Unstable: {len(trans_unstable)}")
print(f"  Unstable → Stable: {len(trans_stable)}")

if len(trans_unstable) == 0:
    print("\n⚠️ Keine Übergänge gefunden!")
    exit()

# ============================================================
# 6. PARAMETER-ANALYSE BEI ÜBERGÄNGEN
# ============================================================
print("\n=== PARAMETER-ÄNDERUNGEN BEI ÜBERGÄNGEN ===\n")

results = []
for t in trans_unstable:
    before_start = t - pd.Timedelta(minutes=30)
    before_end = t
    after_start = t
    after_end = t + pd.Timedelta(minutes=30)

    row = {"timestamp": t}

    # Für jede Spalte: Mittelwert vor/nach Übergang
    for col in df.columns:
        if col in ["phase", "prev_phase", "transition_to_unstable", "transition_to_stable"]:
            continue

        try:
            before_val = df.loc[before_start:before_end, col].mean()
            after_val = df.loc[after_start:after_end, col].mean()

            if not pd.isna(before_val) and not pd.isna(after_val):
                row[f"{col}_before"] = before_val
                row[f"{col}_after"] = after_val
                row[f"{col}_delta"] = after_val - before_val
        except:
            pass

    results.append(row)

res_df = pd.DataFrame(results)

if len(res_df) == 0:
    print("Keine auswertbaren Übergänge!")
    exit()

# ============================================================
# 7. STATISTIK
# ============================================================
print(f"Analysiert: {len(res_df)} Übergänge (Stabil → Instabil)\n")

print("--- POWER ---")
if "power_before" in res_df.columns:
    print(f"  Vor Übergang (Ø): {res_df['power_before'].mean():.0f} W")
    print(f"  Nach Übergang (Ø): {res_df['power_after'].mean():.0f} W")
    print(f"  Delta: {res_df['power_delta'].mean():+.0f} W")

print("\n--- ZIELTEMPERATUREN (⭐ NEU!) ---")
for room in ["erdgeschoss", "arbeitszimmer"]:
    col_before = f"{room}_target_temp_before"
    col_after = f"{room}_target_temp_after"
    col_delta = f"{room}_target_temp_delta"

    if col_before in res_df.columns:
        changes = (res_df[col_delta].abs() > 0.1).sum()
        print(f"  {room.upper()}:")
        print(f"    Vor: {res_df[col_before].mean():.1f}°C, Nach: {res_df[col_after].mean():.1f}°C")
        print(
            f"    Delta (Ø): {res_df[col_delta].mean():+.2f}°C, Änderungen: {changes}/{len(res_df)}"
        )

print("\n--- AKTUELLE TEMPERATUR (ist-Wert) ---")
for room in ["erdgeschoss", "arbeitszimmer"]:
    col_delta = f"{room}_current_temp_delta"
    if col_delta in res_df.columns:
        print(f"  {room}: Ø {res_df[col_delta].mean():+.3f}°C")

print("\n--- PATH TEMPERATUR (interne Sensoren) ---")
for room in ["eg", "sz", "az", "kz", "ak"]:
    col_delta = f"path_{room}_delta"
    if col_delta in res_df.columns:
        print(f"  {room}: Ø {res_df[col_delta].mean():+.3f}°C")

print("\n--- HVAC MODE / FAN MODE ---")
for room in ["erdgeschoss", "arbeitszimmer"]:
    state_col = f"{room}_hvac_state_before"
    fan_col = f"{room}_fan_mode_before"

    if state_col in res_df.columns:
        # Häufigste States vor Übergang
        print(
            f"  {room} HVAC State vor Übergang: {res_df[state_col].mode()[0] if not res_df[state_col].empty else 'N/A'}"
        )

    if fan_col in res_df.columns:
        print(f"  {room} Fan Mode (Ø): {res_df[fan_col].mean():.0f}")

# ============================================================
# 8. KORRELATION
# ============================================================
print("\n=== KORRELATION MIT INSTABILITÄT ===\n")

numeric_cols = res_df.select_dtypes(include=[np.number]).columns.tolist()
delta_cols = [c for c in numeric_cols if c.endswith("_delta")]

if "power_delta" in res_df.columns:
    power_delta = res_df["power_delta"]

    correlations = {}
    for col in delta_cols:
        if col == "power_delta":
            continue
        try:
            corr = power_delta.corr(res_df[col])
            if not pd.isna(corr):
                correlations[col] = corr
        except:
            pass

    sorted_corr = sorted(correlations.items(), key=lambda x: abs(x[1]), reverse=True)
    print("Korrelation mit Power-Anstieg bei Übergang:")
    for name, corr in sorted_corr[:15]:
        direction = "↑↑" if corr > 0.3 else "↓↓" if corr < -0.3 else "  "
        print(f"  {direction} {name}: r={corr:+.3f}")

# ============================================================
# 9. VISUALISIERUNG
# ============================================================
print("\nErstelle Visualisierungen...")

fig, axes = plt.subplots(2, 2, figsize=(16, 12))

# Plot 1: Power Distribution
ax1 = axes[0][0]
if "power_before" in res_df.columns:
    ax1.hist(
        res_df["power_before"].dropna(), bins=20, alpha=0.7, label="Vor Übergang", color="green"
    )
    ax1.hist(res_df["power_after"].dropna(), bins=20, alpha=0.7, label="Nach Übergang", color="red")
    ax1.set_xlabel("Power (W)")
    ax1.set_ylabel("Anzahl")
    ax1.set_title("Power vor/nach Stabilitätsverlust")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

# Plot 2: Target Temperature Changes
ax2 = axes[0][1]
target_deltas = [c for c in res_df.columns if "target_temp_delta" in c]
if target_deltas:
    data_to_plot = [res_df[col].dropna() for col in target_deltas]
    labels = [col.replace("_target_temp_delta", "") for col in target_deltas]
    ax2.boxplot(data_to_plot, labels=labels)
    ax2.set_ylabel("Temperatur-Änderung (°C)")
    ax2.set_title("Zieltemperatur-Änderungen bei Übergängen")
    ax2.axhline(y=0, color="black", linewidth=0.5)
    ax2.grid(True, alpha=0.3)

# Plot 3: Path Temp Deltas
ax3 = axes[1][0]
path_deltas = [c for c in res_df.columns if c.startswith("path_") and c.endswith("_delta")]
if path_deltas:
    means = [res_df[col].mean() for col in path_deltas]
    labels = [col.replace("path_", "").replace("_delta", "") for col in path_deltas]
    colors = ["red" if m > 0 else "blue" for m in means]
    ax3.barh(labels, means, color=colors, alpha=0.7)
    ax3.set_xlabel("Ø Temperatur-Änderung (°C)")
    ax3.set_title("Path-Temperatur-Änderungen (Raum-Sensoren)")
    ax3.axvline(x=0, color="black", linewidth=0.5)
    ax3.grid(True, alpha=0.3)

# Plot 4: Top Correlations
ax4 = axes[1][1]
if sorted_corr:
    top_factors = [name.replace("_delta", "") for name, _ in sorted_corr[:8]]
    corr_values = [corr for _, corr in sorted_corr[:8]]
    colors = ["red" if v > 0 else "blue" for v in corr_values]
    ax4.barh(top_factors, corr_values, color=colors, alpha=0.7)
    ax4.set_xlabel("Korrelation mit Power-Anstieg")
    ax4.set_title("Top Faktoren für Instabilität")
    ax4.axvline(x=0, color="black", linewidth=0.5)
    ax4.grid(True, alpha=0.3)

plt.tight_layout()
output_path = "/home/diyon/.openclaw/workspace/climatiq/data/full_stability_analysis.png"
plt.savefig(output_path, dpi=150)
print(f"✓ Gespeichert: {output_path}")

# ============================================================
# 10. STABILE KOMBINATIONEN
# ============================================================
print("\n=== STABILE PARAMETER-KOMBINATIONEN ===\n")

df["stable_run"] = (df["phase"] == "stable").astype(int)
df["stable_group"] = (df["stable_run"] != df["stable_run"].shift()).cumsum()

stable_runs = df[df["phase"] == "stable"].groupby("stable_group")

long_stable = []
for gid, group in stable_runs:
    if len(group) >= 6:  # >= 30 min
        row = {
            "start": group.index[0],
            "end": group.index[-1],
            "duration_min": len(group) * 5,
            "power_mean": group["power"].mean(),
            "power_std": group["power_std"].mean(),
        }

        # Climate data
        for room in ["erdgeschoss", "arbeitszimmer"]:
            if f"{room}_target_temp" in group.columns:
                row[f"{room}_target"] = group[f"{room}_target_temp"].mean()
                row[f"{room}_current"] = group[f"{room}_current_temp"].mean()

        # Path temps
        for room in ["eg", "sz", "az", "kz", "ak"]:
            if f"path_{room}" in group.columns:
                row[f"path_{room}"] = group[f"path_{room}"].mean()

        long_stable.append(row)

stable_df = pd.DataFrame(long_stable)

if len(stable_df) > 0:
    print(f"Gefunden: {len(stable_df)} stabile Episoden (>30 min)\n")
    print(f"Durchschnittliche stabile Konfiguration:")
    print(
        f"  Power: {stable_df['power_mean'].mean():.0f} W (Std: {stable_df['power_std'].mean():.1f} W)"
    )
    print(
        f"  Dauer: {stable_df['duration_min'].mean():.0f} min (max: {stable_df['duration_min'].max():.0f})"
    )

    print(f"\n  CLIMATE SETTINGS:")
    for room in ["erdgeschoss", "arbeitszimmer"]:
        if f"{room}_target" in stable_df.columns:
            target = stable_df[f"{room}_target"].mean()
            current = stable_df[f"{room}_current"].mean()
            print(f"    {room}: Ziel {target:.1f}°C, Ist {current:.1f}°C")

    print(f"\n  PATH TEMPERATUREN:")
    for room in ["eg", "sz", "az", "kz", "ak"]:
        if f"path_{room}" in stable_df.columns:
            print(f"    {room}: {stable_df[f'path_{room}'].mean():.1f}°C")
else:
    print("Keine stabilen Episoden gefunden!")

print("\n✅ Analyse abgeschlossen.")
print("\n💡 FAZIT: Jetzt haben wir die vollständigen Daten inkl. Zieltemperaturen!")
