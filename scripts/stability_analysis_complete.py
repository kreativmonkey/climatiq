#!/usr/bin/env python3
"""Vollständige Stabilitätsanalyse mit ALLEN verfügbaren Daten"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from climatiq.data.influx_v1_client import InfluxV1Client

client = InfluxV1Client()

DAYS = 60
end = datetime.now()
start = end - timedelta(days=DAYS)

print(f"=== Vollständige Stabilitäts-Analyse ({DAYS} Tage) ===\n")

# ===== KORRIGIERTE ENTITY-NAMEN (Sebastian's Input) =====
entities = {
    # Power
    'power': 'ac_current_energy',
    'outdoor_temp': 'ac_temperatur_outdoor',
    
    # Path Temperaturen (AKTUELLE Raumtemps - beste Quelle!)
    'temp_eg': 'ac_erdgeschoss_path_temperatur',
    'temp_sz': 'ac_schlafzimmer_path_temperatur',
    'temp_az': 'ac_arbeitszimmer_path_temperatur',
    'temp_kz': 'ac_kinderzimmer_path_temperatur',
    'temp_ak': 'ac_ankleide_path_temperatur',
    
    # Zieltemperaturen (desired - nur bei Änderung geschrieben!)
    'target_eg': 'panasonic_climate_erdgeschoss_desired_temperature',
    'target_sz': 'panasonic_climate_schlafzimmer_desired_temperature',
    'target_az': 'panasonic_climate_arbeitszimmer_desired_temperature',
    'target_kz': 'panasonic_climate_kinderzimmer_desired_temperature',
    'target_ak': 'panasonic_climate_ankleide_desired_temperature',
    
    # Unit Ein/Aus
    'unit_eg': 'ac_erdgeschoss_ac_ein_aus',
    'unit_az': 'ac_arbeitszimmer_ac_eine_aus',
    'unit_kz': 'ac_kinderzimmer_e_a',
    'unit_ak': 'ac_ankleidezimmer_e_a',
    
    # Taktreduzierung
    'taktred_kz': 'ac_kinderzimmer_tacktreduzierung',
    'taktred_ak': 'ac_ankleide_tacktreduzierung',
}

print("Lade Daten (5min Auflösung)...")
data = {}
for key, entity in entities.items():
    df = client.get_entity_data(entity, start, end, resample='5m')
    if not df.empty and len(df) > 10:
        data[key] = df['value']
        print(f"  ✓ {key:15s}: {len(df):5d} Punkte")
    else:
        print(f"  ✗ {key:15s}: keine/wenig Daten ({len(df)} Punkte)")

if 'power' not in data:
    print("\nFEHLER: Keine Power-Daten!")
    exit(1)

df = pd.DataFrame(data)
df = df.sort_index()

# Forward-fill für Zieltemperaturen (werden nur bei Änderung geschrieben)
target_cols = [c for c in df.columns if c.startswith('target_')]
for col in target_cols:
    df[col] = df[col].ffill()

print(f"\nGesamt: {len(df)} Zeitpunkte, {len(data)} verfügbare Kanäle")

# ===== STABILITÄTSMETRIKEN =====
print("\nBerechne Stabilität...")
df['power_std'] = df['power'].rolling(6, min_periods=1).std()
df['power_spread'] = df['power'].rolling(6, min_periods=1).max() - df['power'].rolling(6, min_periods=1).min()
df['power_gradient'] = df['power'].diff().rolling(6).mean()

# Klassifizierung
df['phase'] = 'neutral'
df['phase'] = df['phase'].where(~(df['power_std'] < 50), 'stable')
df['phase'] = df['phase'].where(~(df['power_std'] > 120), 'unstable')

# Aktive Units zählen
unit_cols = [c for c in df.columns if c.startswith('unit_')]
for col in unit_cols:
    df[col] = pd.to_numeric(df[col], errors='coerce')
    df[col] = (df[col].fillna(0) > 0).astype(int)
df['active_units'] = sum(df[col] for col in unit_cols if col in df.columns)

# ===== NEUE FEATURE: Temperatur-Abweichung von Ziel =====
print("\nBerechne Temperatur-Abweichungen...")
for room in ['eg', 'sz', 'az', 'kz', 'ak']:
    temp_col = f'temp_{room}'
    target_col = f'target_{room}'
    if temp_col in df.columns and target_col in df.columns:
        df[f'temp_delta_{room}'] = df[temp_col] - df[target_col]
        mean_delta = df[f'temp_delta_{room}'].mean()
        print(f"  {room}: Ø {mean_delta:+.2f}°C Abweichung vom Ziel")

# ===== ÜBERGÄNGE FINDEN =====
print("\nFinde Übergänge...")
df['prev_phase'] = df['phase'].shift(1)
df['transition_to_unstable'] = (df['prev_phase'] == 'stable') & (df['phase'] == 'unstable')
df['transition_to_stable'] = (df['prev_phase'] == 'unstable') & (df['phase'] == 'stable')

trans_unstable = df[df['transition_to_unstable']].index.tolist()
trans_stable = df[df['transition_to_stable']].index.tolist()

print(f"  Stable → Unstable: {len(trans_unstable)}")
print(f"  Unstable → Stable: {len(trans_stable)}")

if len(trans_unstable) == 0:
    print("\n⚠️ Keine Übergänge gefunden!")
    exit()

# ===== PARAMETER-ANALYSE BEI ÜBERGÄNGEN =====
print("\n=== PARAMETER-ÄNDERUNGEN BEI ÜBERGÄNGEN ===\n")

results = []
for t in trans_unstable:
    before_start = t - pd.Timedelta(minutes=30)
    before_end = t
    after_start = t
    after_end = t + pd.Timedelta(minutes=30)
    
    row = {'timestamp': t}
    
    # Power
    row['power_before'] = df.loc[before_start:before_end, 'power'].mean()
    row['power_after'] = df.loc[after_start:after_end, 'power'].mean()
    row['power_delta'] = row['power_after'] - row['power_before']
    
    # Outdoor
    if 'outdoor_temp' in df.columns:
        row['outdoor_before'] = df.loc[before_start:before_end, 'outdoor_temp'].mean()
        row['outdoor_after'] = df.loc[after_start:after_end, 'outdoor_temp'].mean()
        row['outdoor_delta'] = row.get('outdoor_after', 0) - row.get('outdoor_before', 0)
    
    # Active Units
    row['units_before'] = df.loc[before_start:before_end, 'active_units'].mean()
    row['units_after'] = df.loc[after_start:after_end, 'active_units'].mean()
    row['units_delta'] = row['units_after'] - row['units_before']
    
    # Temperaturen (aktuell)
    for room in ['eg', 'sz', 'az', 'kz', 'ak']:
        temp_col = f'temp_{room}'
        if temp_col in df.columns:
            before_val = df.loc[before_start:before_end, temp_col].mean()
            after_val = df.loc[after_start:after_end, temp_col].mean()
            row[f'{temp_col}_before'] = before_val
            row[f'{temp_col}_after'] = after_val
            row[f'{temp_col}_delta'] = after_val - before_val
    
    # Zieltemperaturen
    for room in ['eg', 'sz', 'az', 'kz', 'ak']:
        target_col = f'target_{room}'
        if target_col in df.columns:
            before_val = df.loc[before_start:before_end, target_col].mean()
            after_val = df.loc[after_start:after_end, target_col].mean()
            row[f'{target_col}_delta'] = after_val - before_val
    
    # Temperatur-Abweichungen vom Ziel
    for room in ['eg', 'sz', 'az', 'kz', 'ak']:
        delta_col = f'temp_delta_{room}'
        if delta_col in df.columns:
            before_val = df.loc[before_start:before_end, delta_col].mean()
            after_val = df.loc[after_start:after_end, delta_col].mean()
            row[f'{delta_col}_before'] = before_val
            row[f'{delta_col}_after'] = after_val
    
    # Taktreduzierung
    for room in ['kz', 'ak']:
        takt_col = f'taktred_{room}'
        if takt_col in df.columns:
            before_val = df.loc[before_start:before_end, takt_col].mean()
            after_val = df.loc[after_start:after_end, takt_col].mean()
            row[f'{takt_col}_delta'] = after_val - before_val
    
    results.append(row)

res_df = pd.DataFrame(results)

# ===== STATISTIK =====
print(f"Analysiert: {len(res_df)} Übergänge (Stabil → Instabil)\n")

print("--- POWER ---")
print(f"  Vor Übergang (Ø): {res_df['power_before'].mean():.0f} W")
print(f"  Nach Übergang (Ø): {res_df['power_after'].mean():.0f} W")
print(f"  Delta: {res_df['power_delta'].mean():+.0f} W")

if 'outdoor_before' in res_df.columns:
    print("\n--- AUßENTEMPERATUR ---")
    print(f"  Vor Übergang (Ø): {res_df['outdoor_before'].mean():.1f} °C")
    print(f"  Nach Übergang (Ø): {res_df['outdoor_after'].mean():.1f} °C")
    print(f"  Delta (Ø): {res_df['outdoor_delta'].mean():+.2f} °C")

print("\n--- AKTIVE GERÄTE ---")
print(f"  Vor Übergang (Ø): {res_df['units_before'].mean():.2f}")
print(f"  Nach Übergang (Ø): {res_df['units_after'].mean():.2f}")
print(f"  Delta (Ø): {res_df['units_delta'].mean():+.2f}")
nonzero_changes = (res_df['units_delta'].abs() > 0.1).sum()
print(f"  Änderungen: {nonzero_changes}/{len(res_df)} Übergänge")

# Temperaturen
print("\n--- RAUMTEMPERATUR-ÄNDERUNGEN ---")
for room in ['eg', 'sz', 'az', 'kz', 'ak']:
    delta_col = f'temp_{room}_delta'
    if delta_col in res_df.columns:
        mean_delta = res_df[delta_col].mean()
        direction = "↑" if mean_delta > 0.1 else "↓" if mean_delta < -0.1 else "→"
        print(f"  {room.upper()}: {direction} {mean_delta:+.3f}°C")

# Zieltemperatur-Änderungen
print("\n--- ZIELTEMPERATUR-ÄNDERUNGEN ---")
for room in ['eg', 'sz', 'az', 'kz', 'ak']:
    delta_col = f'target_{room}_delta'
    if delta_col in res_df.columns:
        mean_delta = res_df[delta_col].mean()
        changed = (res_df[delta_col].abs() > 0.1).sum()
        if changed > 0:
            print(f"  {room.upper()}: Ø {mean_delta:+.2f}°C, {changed} Änderungen")

# Temp-Abweichungen vom Ziel
print("\n--- TEMP-ABWEICHUNG VOM ZIEL (bei Übergang) ---")
for room in ['eg', 'sz', 'az', 'kz', 'ak']:
    before_col = f'temp_delta_{room}_before'
    after_col = f'temp_delta_{room}_after'
    if before_col in res_df.columns and after_col in res_df.columns:
        before = res_df[before_col].mean()
        after = res_df[after_col].mean()
        print(f"  {room.upper()}: {before:+.2f}°C → {after:+.2f}°C")

# ===== KORRELATION =====
print("\n=== KORRELATION MIT INSTABILITÄT ===\n")
numeric_cols = res_df.select_dtypes(include=[np.number]).columns.tolist()
power_delta = res_df['power_delta']

correlations = {}
for col in numeric_cols:
    if col in ['power_before', 'power_after', 'timestamp']:
        continue
    try:
        corr = power_delta.corr(res_df[col])
        if not pd.isna(corr) and abs(corr) > 0.1:
            correlations[col] = corr
    except:
        pass

sorted_corr = sorted(correlations.items(), key=lambda x: abs(x[1]), reverse=True)
print("Top Korrelationen mit Power-Anstieg:")
for name, corr in sorted_corr[:20]:
    direction = "↑↑" if corr > 0.3 else "↓↓" if corr < -0.3 else "  "
    print(f"  {direction} {name:40s}: r={corr:+.3f}")

# ===== VISUALISIERUNG =====
print("\nErstelle Visualisierungen...")
fig, axes = plt.subplots(2, 3, figsize=(20, 12))

# Plot 1: Power Distribution
ax1 = axes[0][0]
ax1.hist(res_df['power_before'].dropna(), bins=20, alpha=0.7, label='Vor Übergang', color='green')
ax1.hist(res_df['power_after'].dropna(), bins=20, alpha=0.7, label='Nach Übergang', color='red')
ax1.set_xlabel('Power (W)')
ax1.set_ylabel('Anzahl')
ax1.set_title('Power vor/nach Stabilitätsverlust')
ax1.legend()
ax1.grid(True, alpha=0.3)

# Plot 2: Temp Deltas per Room
ax2 = axes[0][1]
rooms = ['eg', 'sz', 'az', 'kz', 'ak']
temp_deltas = []
for room in rooms:
    col = f'temp_{room}_delta'
    if col in res_df.columns:
        temp_deltas.append(res_df[col].mean())
    else:
        temp_deltas.append(0)
colors = ['red' if d > 0.1 else 'blue' if d < -0.1 else 'gray' for d in temp_deltas]
ax2.barh([r.upper() for r in rooms], temp_deltas, color=colors, alpha=0.7)
ax2.set_xlabel('Temperatur-Änderung (°C)')
ax2.set_title('Raumtemp-Änderung bei Übergang')
ax2.axvline(x=0, color='black', linewidth=0.5)
ax2.grid(True, alpha=0.3)

# Plot 3: Outdoor Temp vs Power
ax3 = axes[0][2]
if 'outdoor_before' in res_df.columns:
    ax3.scatter(res_df['outdoor_before'], res_df['power_before'], alpha=0.6, c='green', label='Stabil', s=50)
    ax3.scatter(res_df['outdoor_after'], res_df['power_after'], alpha=0.6, c='red', label='Instabil', s=50)
    ax3.set_xlabel('Außentemperatur (°C)')
    ax3.set_ylabel('Power (W)')
    ax3.set_title('Außentemperatur vs. Power')
    ax3.legend()
    ax3.grid(True, alpha=0.3)

# Plot 4: Active Units Distribution
ax4 = axes[1][0]
if res_df['units_before'].max() > 0 or res_df['units_after'].max() > 0:
    ax4.hist(res_df['units_before'].dropna(), bins=10, alpha=0.7, label='Vor Übergang', color='green')
    ax4.hist(res_df['units_after'].dropna(), bins=10, alpha=0.7, label='Nach Übergang', color='red')
    ax4.set_xlabel('Aktive Geräte')
    ax4.set_ylabel('Anzahl')
    ax4.set_title('Aktive Geräte bei Übergang')
    ax4.legend()
    ax4.grid(True, alpha=0.3)

# Plot 5: Top Correlations
ax5 = axes[1][1]
top_factors = [name for name, _ in sorted_corr[:10]]
if top_factors:
    corr_values = [correlations[f] for f in top_factors]
    colors_corr = ['red' if v > 0 else 'blue' for v in corr_values]
    # Shorten names for display
    short_names = [n.replace('temp_', '').replace('_delta', '').replace('_before', '(v)').replace('_after', '(n)') for n in top_factors]
    ax5.barh(short_names, corr_values, color=colors_corr, alpha=0.7)
    ax5.set_xlabel('Korrelation')
    ax5.set_title('Top 10 Faktoren für Instabilität')
    ax5.axvline(x=0, color='black', linewidth=0.5)
    ax5.grid(True, alpha=0.3)

# Plot 6: Timeline of transitions
ax6 = axes[1][2]
trans_times = [t.hour for t in trans_unstable]
ax6.hist(trans_times, bins=24, alpha=0.7, color='orange', edgecolor='black')
ax6.set_xlabel('Uhrzeit')
ax6.set_ylabel('Anzahl Übergänge')
ax6.set_title('Wann treten Instabilitäten auf?')
ax6.set_xticks(range(0, 24, 3))
ax6.grid(True, alpha=0.3)

plt.tight_layout()
output_path = '/home/diyon/.openclaw/workspace/climatiq/data/stability_analysis_complete.png'
plt.savefig(output_path, dpi=150)
print(f"✓ Gespeichert: {output_path}")

print("\n✅ Analyse abgeschlossen.")
