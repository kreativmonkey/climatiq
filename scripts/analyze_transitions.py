#!/usr/bin/env python3
"""ClimatIQ Transition Analyzer.

Identifies transitions between stable and unstable states and correlates them
with external factors like unit state changes, temperatures, and fan modes.
"""

from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import pandas as pd

from climatiq.data.influx_v1_client import InfluxV1Client


def analyze_transitions(days=30):
    client = InfluxV1Client()

    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)

    print(f"Lade Daten für die letzten {days} Tage...")

    # 1. Power Daten (Basis für Stabilität)
    df_power = client.get_entity_data("ac_current_energy", start_time, end_time, resample="1m")
    if df_power.empty:
        print("Keine Power-Daten gefunden.")
        return

    # 2. Berechne Stabilität
    df_power["std"] = df_power["value"].rolling(10, min_periods=1).std()
    df_power["is_stable"] = df_power["std"] < 50
    df_power["is_unstable"] = df_power["std"] > 150

    # 3. Finde Übergänge (Stable -> Unstable)
    df_power["transition"] = df_power["is_stable"].shift(1) & df_power["is_unstable"]
    transitions = df_power[df_power["transition"]].index.tolist()

    print(f"Gefundene Übergänge (Stabil -> Instabil): {len(transitions)}")

    if not transitions:
        return

    # 4. Lade Kontext-Daten für die Übergänge
    # Wir laden Außentemperatur und Geräte-Status
    df_outdoor = client.get_entity_data(
        "ac_temperatur_outdoor", start_time, end_time, resample="1m"
    )

    # Beispielhafte Liste von Innengeräten
    units = ["erdgeschoss", "schlafzimmer", "arbeitszimmer", "kinderzimmer", "ankleide"]
    unit_entities = [f"climate.{u}" for u in units]

    # 5. Korrelations-Analyse pro Übergang
    results = []
    for t in transitions:
        # 10 min Fenster um den Übergang
        window_start = t - timedelta(minutes=10)
        window_end = t + timedelta(minutes=10)

        # Power Delta
        p_before = df_power.loc[window_start:t, "value"].mean()
        p_after = df_power.loc[t:window_end, "value"].mean()

        # Temp Delta
        t_out = (
            df_outdoor.loc[window_start:window_end, "value"].mean()
            if not df_outdoor.empty
            else None
        )

        results.append(
            {
                "timestamp": t,
                "power_before": p_before,
                "power_after": p_after,
                "outdoor_temp": t_out,
            }
        )

    res_df = pd.DataFrame(results)
    print("\n=== Durchschnittliche Werte bei Übergängen ===")
    print(res_df.describe())

    # Plotting
    plt.figure(figsize=(12, 6))
    plt.scatter(res_df["outdoor_temp"], res_df["power_before"], alpha=0.5)
    plt.title("Power vor Instabilität vs. Außentemperatur")
    plt.xlabel("Außentemperatur (°C)")
    plt.ylabel("Power (W)")
    plt.grid(True)
    plt.savefig("/home/diyon/.openclaw/workspace/climatiq/data/transition_correlation.png")
    print("\nVisualisierung unter data/transition_correlation.png gespeichert.")


if __name__ == "__main__":
    analyze_transitions(days=30)
