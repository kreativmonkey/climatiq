#!/usr/bin/env python3
"""Validate the new Analyzer logic with real data."""

import os

import pandas as pd

from climatiq.core.analyzer import Analyzer

# Load data
data_path = "/home/diyon/.openclaw/workspace/climatiq/data/power_last_5days.csv"
if not os.path.exists(data_path):
    print("Data file not found!")
    exit(1)

df = pd.read_csv(data_path, index_col=0, parse_dates=True)
power_series = df["value"]

print(f"Analyzing {len(df)} datapoints with new Analyzer v2...")

analyzer = Analyzer()
result = analyzer.analyze(power_series)

print("\n=== Analysis Results ===")
print(f"Data sufficient: {result.sufficient_data}")
print(f"Data quality: {result.data_quality_score:.2f}")
print(f"Min Stable Power: {result.min_stable_power:.1f} W")
print(f"Recommendation: {result.recommendation}")

print("\n=== Discovered Regions ===")
for r in result.regions:
    status = "STABLE" if r.stability_score > 0.7 else "UNSTABLE"
    print(f"- {r.name}: Stability={r.stability_score:.2f} ({status}), Count={r.sample_count}")

if result.min_stable_power and result.min_stable_power < 700:
    print("\n✅ SUCCESS: Analyzer correctly identified a low-power stable zone!")
else:
    print("\n❌ FAILURE: Analyzer still fails to identify the low-power stable zone.")
