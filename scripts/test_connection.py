#!/usr/bin/env python3
"""Quick script to test InfluxDB connection and explore available data."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from climatiq.data.influx_client import HVACDataLoader


def main():
    print("=" * 60)
    print("HVAC Optimizer - InfluxDB Connection Test")
    print("=" * 60)

    loader = HVACDataLoader()

    print(f"\nConnecting to: {loader.url}")
    print(f"Bucket/Database: {loader.bucket}")

    # Test connection
    print("\nTesting connection...", end=" ")
    if loader.test_connection():
        print("✓ SUCCESS")
    else:
        print("✗ FAILED")
        print("\nPlease check your .env file and InfluxDB server.")
        return 1

    # List measurements
    print("\n" + "-" * 40)
    print("Available measurements:")
    print("-" * 40)

    measurements = loader.list_measurements()
    if measurements:
        for m in measurements[:30]:  # Show first 30
            print(f"  - {m}")
        if len(measurements) > 30:
            print(f"  ... and {len(measurements) - 30} more")
    else:
        print("  No measurements found (or query failed)")

    # Look for climate/HVAC related measurements
    print("\n" + "-" * 40)
    print("Looking for HVAC-related data...")
    print("-" * 40)

    hvac_keywords = ["climate", "hvac", "temperature", "temp", "power", "energy", "heat", "cool"]
    hvac_measurements = [m for m in measurements if any(kw in m.lower() for kw in hvac_keywords)]

    if hvac_measurements:
        print("Found potentially relevant measurements:")
        for m in hvac_measurements[:20]:
            print(f"  - {m}")
            # Show fields for this measurement
            fields = loader.list_fields(m)
            if fields:
                print(f"    Fields: {', '.join(fields[:5])}")
                if len(fields) > 5:
                    print(f"    ... and {len(fields) - 5} more fields")
    else:
        print("No obvious HVAC measurements found.")
        print("Please check measurement names manually.")

    loader.close()
    print("\n" + "=" * 60)
    print("Connection test complete!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
