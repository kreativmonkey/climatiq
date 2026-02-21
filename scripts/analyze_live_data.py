"""Analyze live production data from the last 2 days."""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from climatiq.data.influx_v1_client import InfluxV1Client

load_dotenv()


def analyze_production_performance():
    """Analyze controller performance over last 2 days."""
    client = InfluxV1Client()
    
    # Last 2 days
    end = datetime.now()
    start = end - timedelta(days=2)
    
    print(f"Analyzing data from {start} to {end}")
    print("=" * 60)
    
    # Get key metrics (from AppDaemon config)
    entities = {
        "power": "ac_current_energy",
        "outdoor_temp": "ac_temperatur_outdoor",
        "temp_wohnzimmer": "temperatur_wohnzimmer",
        "temp_schlafzimmer": "temperatur_flur_og",
        "temp_arbeitszimmer": "rwm_arbeitszimmer_temperature",
        "temp_kinderzimmer": "0x000d6f0019c90b85_temperature",
        # Climate entities for target temps
        "climate_eg": "panasonic_climate_erdgeschoss",
        "climate_schlafzimmer": "panasonic_climate_schlafzimmer",
        "climate_arbeitszimmer": "panasonic_climate_arbeitszimmer",
    }
    
    data = {}
    for key, entity in entities.items():
        print(f"Loading {key} ({entity})...")
        try:
            df = client.get_entity_data(entity, start, end, resample="5m")
            if not df.empty:
                data[key] = df["value"]
                print(f"   ✅ {len(df)} points")
            else:
                print(f"   ⚠️ empty")
        except Exception as e:
            print(f"   ❌ Error: {e}")
    
    if not data:
        print("\n❌ No data available!")
        print("\nTip: Check entity names in InfluxDB:")
        print("   Available entities with 'ac_': ")
        test_entities = client.list_entities("ac_")
        for e in test_entities[:10]:
            print(f"      {e}")
        return
    
    # Combine into single DataFrame
    df = pd.DataFrame(data)
    df = df.dropna(subset=["power"])
    
    # Derive compressor state from power (>500W = ON)
    df["compressor"] = (df["power"] > 500).astype(int)
    
    print(f"\n✅ Loaded {len(df)} datapoints (5-min resolution)")
    print(f"   Timespan: {df.index[0]} to {df.index[-1]}")
    
    # === Analysis ===
    print("\n" + "=" * 60)
    print("PERFORMANCE METRICS")
    print("=" * 60)
    
    # 1. Compressor cycling
    state_changes = (df["compressor"].diff() != 0).sum()
    runtime_hours = len(df) * 5 / 60  # 5-min intervals
    cycles_per_day = state_changes / 2 / (runtime_hours / 24)  # ON+OFF = 1 cycle
    
    print(f"\n🔄 Cycling Behavior:")
    print(f"   State changes: {state_changes}")
    print(f"   Cycles per day: {cycles_per_day:.1f}")
    print(f"   Runtime: {runtime_hours:.1f}h")
    
    # Compressor runtime
    compressor_on = df["compressor"].sum() / len(df) * 100
    print(f"   Compressor ON: {compressor_on:.1f}% of time")
    
    # 2. Power consumption
    avg_power = df["power"].mean()
    power_std = df["power"].std()
    
    print(f"\n⚡ Power Consumption:")
    print(f"   Average: {avg_power:.0f}W ± {power_std:.0f}W")
    print(f"   Min: {df['power'].min():.0f}W")
    print(f"   Max: {df['power'].max():.0f}W")
    
    # Power zones
    zone_low = (df["power"] < 700).sum() / len(df) * 100
    zone_mid = ((df["power"] >= 700) & (df["power"] < 1200)).sum() / len(df) * 100
    zone_high = (df["power"] >= 1200).sum() / len(df) * 100
    
    print(f"\n   Power zones:")
    print(f"   <700W (stable low): {zone_low:.1f}%")
    print(f"   700-1200W (transition): {zone_mid:.1f}%")
    print(f"   >1200W (stable high): {zone_high:.1f}%")
    
    # 3. Temperature control
    temp_cols = [c for c in df.columns if c.startswith("temp_")]
    if temp_cols:
        print(f"\n🌡️ Temperature Sensors ({len(temp_cols)} rooms):")
        for col in temp_cols:
            avg_temp = df[col].mean()
            print(f"   {col}: {avg_temp:.1f}°C (avg)")
    
    # 4. Climate entity changes (if available)
    climate_cols = [c for c in df.columns if c.startswith("climate_")]
    total_adjustments = 0
    
    if climate_cols:
        print(f"\n🎯 Climate Control:")
        for col in climate_cols:
            changes = (df[col].diff().abs() > 0.1).sum()
            total_adjustments += changes
            print(f"   {col}: {changes} changes")
    
    adjustments_per_day = total_adjustments / (runtime_hours / 24) if runtime_hours > 0 else 0
    
    if total_adjustments > 0:
        print(f"\n📝 Summary:")
        print(f"   Total adjustments: {total_adjustments}")
        print(f"   Per day: {adjustments_per_day:.1f}")
    
    # 5. Weather conditions
    if "outdoor_temp" in df.columns:
        print(f"\n🌤️ Weather:")
        print(f"   Outdoor temp: {df['outdoor_temp'].mean():.1f}°C (avg)")
        print(f"   Range: {df['outdoor_temp'].min():.1f}°C to {df['outdoor_temp'].max():.1f}°C")
    
    # === Visualization ===
    fig, axes = plt.subplots(4, 1, figsize=(14, 12), sharex=True)
    
    # Plot 1: Power + Compressor
    ax1 = axes[0]
    ax1.plot(df.index, df["power"], label="Power", linewidth=0.8, alpha=0.7)
    ax1.axhline(700, color="green", linestyle="--", alpha=0.5, label="Zone boundaries")
    ax1.axhline(1200, color="red", linestyle="--", alpha=0.5)
    ax1.set_ylabel("Power (W)")
    ax1.legend(loc="upper left")
    ax1.grid(True, alpha=0.3)
    ax1.set_title("Power Consumption & Compressor State (Last 2 Days)")
    
    ax1_twin = ax1.twinx()
    ax1_twin.fill_between(df.index, 0, df["compressor"] * df["power"].max() * 0.3, 
                           alpha=0.2, color="red", label="Compressor ON")
    ax1_twin.set_ylabel("Compressor", color="red")
    ax1_twin.set_ylim(0, df["power"].max() * 0.5)
    
    # Plot 2: Temperatures
    ax2 = axes[1]
    temp_cols = [c for c in df.columns if c.startswith("temp_")]
    for col in temp_cols[:5]:  # Max 5 temps to avoid clutter
        ax2.plot(df.index, df[col], label=col.replace("temp_", ""), linewidth=1, alpha=0.7)
    if "outdoor_temp" in df.columns:
        ax2.plot(df.index, df["outdoor_temp"], label="Outdoor", linewidth=1.5, color="gray", alpha=0.8)
    ax2.set_ylabel("Temperature (°C)")
    ax2.legend(loc="best", fontsize=8)
    ax2.grid(True, alpha=0.3)
    ax2.set_title("Temperature Monitoring")
    
    # Plot 3: Power distribution (histogram)
    ax3 = axes[2]
    ax3.hist(df["power"], bins=50, alpha=0.7, edgecolor="black")
    ax3.axvline(700, color="green", linestyle="--", linewidth=2, label="Stable zones")
    ax3.axvline(1200, color="red", linestyle="--", linewidth=2)
    ax3.set_xlabel("Power (W)")
    ax3.set_ylabel("Frequency")
    ax3.legend()
    ax3.grid(True, alpha=0.3)
    ax3.set_title("Power Distribution")
    
    # Plot 4: Compressor duty cycle over time
    ax4 = axes[3]
    # Rolling average of compressor state (1-hour window)
    window = 12  # 12 * 5min = 1 hour
    df["compressor_duty"] = df["compressor"].rolling(window, center=True).mean() * 100
    ax4.plot(df.index, df["compressor_duty"], color="red", linewidth=1.5, alpha=0.7)
    ax4.fill_between(df.index, 0, df["compressor_duty"], alpha=0.2, color="red")
    ax4.set_xlabel("Time")
    ax4.set_ylabel("Duty Cycle (%)")
    ax4.grid(True, alpha=0.3)
    ax4.set_title("Compressor Duty Cycle (1h rolling average)")
    ax4.set_ylim(0, 100)
    
    plt.tight_layout()
    output_path = Path(__file__).parent.parent / "data" / "live_performance_2days.png"
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"\n📊 Plot saved: {output_path}")
    
    return df


if __name__ == "__main__":
    df = analyze_production_performance()
