#!/usr/bin/env python3
"""Stabilitäts-Übergangs-Analyse mit korrekten Entity-Namen"""

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

print(f"=== Stabilitäts-Analyse ({DAYS} Tage) ===\n")

# ===== KORRIGIERTE ENTITY-NAMEN =====
entities = {
    'power': 'ac_current_energy',
    'outdoor_temp': 'ac_temperatur_outdoor',
    # Path Temperaturen (verfügbar!)
    'path_eg': 'ac_erdgeschoss_path_temperatur',
    'path_sz': 'ac_schlafzimmer_path_temperatur',
    'path_az': 'ac_arbeitszimmer_path_temperatur',
    'path_kz': 'ac_kinderzimmer_path_temperatur',
    'path_ak': 'ac_ankleide_path_temperatur',
    # Raumtemperaturen (Backup)
    'room_eg': 'erdgeschoss',
    'room_az': 'arbeitszimmer',
    'room_kz': 'kinderzimmer',
    'room_ak': 'ankleide',
    # Unit Ein/Aus
    'unit_eg': 'ac_erdgeschoss_ac_ein_aus',
    'unit_az': 'ac_arbeitszimmer_ac_eine_aus',
    'unit_kz': 'ac_kinderzimmer_e_a',
    'unit_ak': 'ac_ankleidezimmer_e_a',
    # WICHTIG: Taktreduzierung!
    'taktred_kz': 'ac_kinderzimmer_tacktreduzierung',
    'taktred_ak': 'ac_ankleide_tacktreduzierung',
}

print("Lade Daten (5min Auflösung)...")
data = {}
for key, entity in entities.items():
    df = client.get_entity_data(entity, start, end, resample='5m')
    if not df.empty:
        data[key] = df['value']
        print(f"  ✓ {key}: {len(df)} Punkte")
    else:
        print(f"  ✗ {key}: keine Daten")

if 'power' not in data:
    print("\nFEHLER: Keine Power-Daten!")
    exit(1)

df = pd.DataFrame(data)
df = df.sort_index()
print(f"\nGesamt: {len(df)} Zeitpunkte, {len(data)} verfügbare Kanäle")

# ===== STABILITÄTSMETRIKEN =====
print("\nBerechne Stabilität...")
df['power_std'] = df['power'].rolling(6, min_periods=1).std()
df['power_spread'] = df['power'].rolling(6, min_periods=1).max() - df['power'].rolling(6, min_periods=1).min()
df['power_gradient'] = df['power'].diff().rolling(6).mean()

# Klassifizierung
df['phase'] = 'neutral'
df.loc[df['power_std'] < 50, 'phase'] = 'stable'
df.loc[df['power_std'] > 120, 'phase'] = 'unstable'

# Aktive Units zählen
unit_cols = [c for c in df.columns if c.startswith('unit_')]
for col in unit_cols:
    df[col] = pd.to_numeric(df[col], errors='coerce')
    # Werte > 0 = on
    df[col] = (df[col].fillna(0) > 0).astype(int)
df['active_units'] = sum(df[col] for col in unit_cols if col in df.columns)

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
    
    # Path Temperatures (Delta)
    for path_key in ['path_eg', 'path_sz', 'path_az', 'path_kz', 'path_ak']:
        if path_key in df.columns:
            before_val = df.loc[before_start:before_end, path_key].mean()
            after_val = df.loc[after_start:after_end, path_key].mean()
            row[f'{path_key}_delta'] = after_val - before_val
    
    # Taktreduzierung (sehr wichtig!)
    for takt_key in ['taktred_kz', 'taktred_ak']:
        if takt_key in df.columns:
            before_val = df.loc[before_start:before_end, takt_key].mean()
            after_val = df.loc[after_start:after_end, takt_key].mean()
            row[f'{takt_key}_before'] = before_val
            row[f'{takt_key}_after'] = after_val
            row[f'{takt_key}_delta'] = after_val - before_val
    
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

# Path Temp Deltas
print("\n--- RAUMTEMPERATUR-ÄNDERUNGEN (Path) ---")
path_deltas = [c for c in res_df.columns if c.startswith('path_') and c.endswith('_delta')]
for col in path_deltas:
    room = col.replace('path_', '').replace('_delta', '')
    mean_delta = res_df[col].mean()
    print(f"  {room}: Ø {mean_delta:+.3f}°C")

# Taktreduzierung
print("\n--- TAKTREDUZIERUNG (⭐ WICHTIG) ---")
takt_cols = [c for c in res_df.columns if c.startswith('taktred_')]
if takt_cols:
    for base in ['taktred_kz', 'taktred_ak']:
        if f'{base}_before' in res_df.columns:
            room = base.replace('taktred_', '')
            before = res_df[f'{base}_before'].mean()
            after = res_df[f'{base}_after'].mean()
            delta = res_df[f'{base}_delta'].mean()
            changed = (res_df[f'{base}_delta'].abs() > 0.1).sum()
            print(f"  {room}: {before:.2f} → {after:.2f} (Δ {delta:+.2f}), {changed} Änderungen")
else:
    print("  (keine Daten)")

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
        if not pd.isna(corr):
            correlations[col] = corr
    except:
        pass

sorted_corr = sorted(correlations.items(), key=lambda x: abs(x[1]), reverse=True)
print("Korrelation mit Power-Anstieg bei Übergang:")
for name, corr in sorted_corr[:15]:
    direction = "↑↑" if corr > 0.3 else "↓↓" if corr < -0.3 else "  "
    print(f"  {direction} {name}: r={corr:+.3f}")

# ===== VISUALISIERUNG =====
print("\nErstelle Visualisierungen...")
fig, axes = plt.subplots(2, 2, figsize=(16, 12))

# Plot 1: Power Distribution
ax1 = axes[0][0]
ax1.hist(res_df['power_before'].dropna(), bins=20, alpha=0.7, label='Vor Übergang', color='green')
ax1.hist(res_df['power_after'].dropna(), bins=20, alpha=0.7, label='Nach Übergang', color='red')
ax1.set_xlabel('Power (W)')
ax1.set_ylabel('Anzahl')
ax1.set_title('Power vor/nach Stabilitätsverlust')
ax1.legend()
ax1.grid(True, alpha=0.3)

# Plot 2: Active Units
ax2 = axes[0][1]
if res_df['units_before'].max() > 0 or res_df['units_after'].max() > 0:
    ax2.hist(res_df['units_before'].dropna(), bins=10, alpha=0.7, label='Vor Übergang', color='green')
    ax2.hist(res_df['units_after'].dropna(), bins=10, alpha=0.7, label='Nach Übergang', color='red')
    ax2.set_xlabel('Aktive Geräte')
    ax2.set_ylabel('Anzahl')
    ax2.set_title('Aktive Geräte vor/nach Stabilitätsverlust')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
else:
    ax2.text(0.5, 0.5, 'Keine Unit-Daten', ha='center', va='center')
    ax2.set_title('Aktive Geräte (keine Daten)')

# Plot 3: Outdoor Temp vs Power
ax3 = axes[1][0]
if 'outdoor_before' in res_df.columns:
    ax3.scatter(res_df['outdoor_before'], res_df['power_before'], alpha=0.6, c='green', label='Stabil', s=50)
    ax3.scatter(res_df['outdoor_after'], res_df['power_after'], alpha=0.6, c='red', label='Instabil', s=50)
    ax3.set_xlabel('Außentemperatur (°C)')
    ax3.set_ylabel('Power (W)')
    ax3.set_title('Außentemperatur vs. Power bei Übergängen')
    ax3.legend()
    ax3.grid(True, alpha=0.3)

# Plot 4: Top Correlations
ax4 = axes[1][1]
top_factors = [name for name, _ in sorted_corr[:8]]
if top_factors:
    corr_values = [correlations[f] for f in top_factors]
    colors = ['red' if v > 0 else 'blue' for v in corr_values]
    ax4.barh(top_factors, corr_values, color=colors, alpha=0.7)
    ax4.set_xlabel('Korrelation mit Power-Anstieg')
    ax4.set_title('Top Faktoren für Instabilität')
    ax4.axvline(x=0, color='black', linewidth=0.5)
    ax4.grid(True, alpha=0.3)

plt.tight_layout()
output_path = '/home/diyon/.openclaw/workspace/climatiq/data/stability_transition_analysis.png'
plt.savefig(output_path, dpi=150)
print(f"✓ Gespeichert: {output_path}")

# ===== STABILE KOMBINATIONEN =====
print("\n=== STABILE PARAMETER-KOMBINATIONEN ===\n")

df['stable_run'] = (df['phase'] == 'stable').astype(int)
df['stable_group'] = (df['stable_run'] != df['stable_run'].shift()).cumsum()

stable_runs = df[df['phase'] == 'stable'].groupby('stable_group')

long_stable = []
for gid, group in stable_runs:
    if len(group) >= 6:  # >= 30 min
        row = {
            'start': group.index[0],
            'end': group.index[-1],
            'duration_min': len(group) * 5,
            'power_mean': group['power'].mean(),
            'power_std': group['power_std'].mean(),
        }
        if 'outdoor_temp' in group.columns:
            row['outdoor'] = group['outdoor_temp'].mean()
        row['active_units'] = group['active_units'].mean()
        
        for path in ['path_eg', 'path_sz', 'path_az', 'path_kz', 'path_ak']:
            if path in group.columns:
                row[path] = group[path].mean()
        
        long_stable.append(row)

stable_df = pd.DataFrame(long_stable)

if len(stable_df) > 0:
    print(f"Gefunden: {len(stable_df)} stabile Episoden (>30 min)\n")
    print(f"Durchschnittliche stabile Konfiguration:")
    print(f"  Power: {stable_df['power_mean'].mean():.0f} W (Std: {stable_df['power_std'].mean():.1f} W)")
    print(f"  Dauer: {stable_df['duration_min'].mean():.0f} min (min: {stable_df['duration_min'].min():.0f}, max: {stable_df['duration_min'].max():.0f})")
    print(f"  Aktive Geräte: {stable_df['active_units'].mean():.2f}")
    if 'outdoor' in stable_df.columns:
        print(f"  Außentemp: {stable_df['outdoor'].mean():.1f} °C")
    
    for path in ['path_eg', 'path_sz', 'path_az', 'path_kz', 'path_ak']:
        if path in stable_df.columns:
            room = path.replace('path_', '')
            print(f"  Path Temp {room}: {stable_df[path].mean():.1f} °C")
else:
    print("Keine stabilen Episoden >30 min gefunden!")

print("\n✅ Analyse abgeschlossen.")
