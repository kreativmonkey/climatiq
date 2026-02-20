#!/usr/bin/env python3
"""ClimatIQ Night Report Generator"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from climatiq.data.influx_v1_client import InfluxV1Client

client = InfluxV1Client()

# Zeitfenster: Letzte Nacht (22:00 bis 09:00)
now = datetime.now()
end = now.replace(hour=9, minute=0, second=0, microsecond=0)
start = (end - timedelta(days=1)).replace(hour=22, minute=0, second=0, microsecond=0)

# Gestern Vergleich (22:00 bis 09:00 vor 2 Tagen)
end_yest = start
start_yest = (end_yest - timedelta(days=1)).replace(hour=22, minute=0, second=0, microsecond=0)


def analyze_period(p_start, p_end, label):
    # Power laden
    df = client.get_entity_data("ac_current_energy", p_start, p_end, resample="1m")
    if df.empty:
        return None

    # Stabilität berechnen
    df["power_std"] = df["value"].rolling(10, min_periods=1).std()

    # Phasen:
    # - Off: < 50W
    # - Stable: > 50W und std < 40
    # - Unstable: > 50W und std >= 40
    df["is_on"] = df["value"] > 50
    df["is_stable"] = df["is_on"] & (df["power_std"] < 40)
    df["is_unstable"] = df["is_on"] & (df["power_std"] >= 40)

    total_on_minutes = df["is_on"].sum()
    if total_on_minutes == 0:
        return {"label": label, "on": 0, "unstable_pct": 0, "avg_power": 0}

    unstable_minutes = df["is_unstable"].sum()
    unstable_pct = (unstable_minutes / total_on_minutes) * 100

    avg_power_on = df[df["is_on"]]["value"].mean()

    # Takt-Events (Zyklen)
    # Ein Takt-Event ist hier als Übergang von Stable -> Unstable oder massive Power-Sprünge definiert
    # Oder klassisch: An/Aus Zyklen
    df["on_change"] = df["is_on"].astype(int).diff().abs()
    cycles = df["on_change"].sum() / 2

    # 450W Check (Wieviel % der Zeit zwischen 400W und 500W?)
    df["is_target_zone"] = df["is_on"] & (df["value"] >= 400) & (df["value"] <= 500)
    target_zone_pct = (
        (df["is_target_zone"].sum() / total_on_minutes) * 100 if total_on_minutes > 0 else 0
    )

    return {
        "label": label,
        "on_min": total_on_minutes,
        "unstable_pct": unstable_pct,
        "avg_power": avg_power_on,
        "cycles": cycles,
        "target_zone_pct": target_zone_pct,
        "min_power": df[df["is_on"]]["value"].min() if total_on_minutes > 0 else 0,
        "max_power": df[df["is_on"]]["value"].max() if total_on_minutes > 0 else 0,
    }


current_report = analyze_period(start, end, "Heute")
yesterday_report = analyze_period(start_yest, end_yest, "Gestern")

if not current_report:
    print("Keine Daten gefunden.")
    exit(1)

print(f"REPORT_START")
print(f"Periode: {start.strftime('%d.%m. %H:%M')} bis {end.strftime('%d.%m. %H:%M')}")
print(
    f"Stabilität (Instabil %): {current_report['unstable_pct']:.1f}% (Gestern: {yesterday_report['unstable_pct']:.1f}% if yesterday_report else 'N/A')"
)
print(f"Durchschnittliche Power: {current_report['avg_power']:.0f}W")
print(f"Takt-Events (An/Aus): {current_report['cycles']:.0f}")
print(f"450W Zonen-Treue: {current_report['target_zone_pct']:.1f}% der Laufzeit")
print(f"Power Range: {current_report['min_power']:.0f}W - {current_report['max_power']:.0f}W")
print(f"REPORT_END")
