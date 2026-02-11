"""InfluxDB 1.x client for loading historical HVAC data."""

import base64
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

import pandas as pd
from dotenv import load_dotenv


class InfluxV1Client:
    """Client for InfluxDB 1.x using InfluxQL."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ):
        """Initialize InfluxDB connection."""
        load_dotenv()

        self.host = host or os.getenv("INFLUXDB_HOST", "localhost")
        self.port = port or int(os.getenv("INFLUXDB_PORT", "8086"))
        self.user = user or os.getenv("INFLUXDB_USER", "")
        self.password = password or os.getenv("INFLUXDB_PASSWORD", "")
        self.database = database or os.getenv("INFLUXDB_DATABASE", "homeassistant")

        self.base_url = f"http://{self.host}:{self.port}"
        self._auth_header = (
            f'Basic {base64.b64encode(f"{self.user}:{self.password}".encode()).decode()}'
        )

    def _query(self, influxql: str) -> dict[str, Any]:
        """Execute an InfluxQL query."""
        url = f"{self.base_url}/query?db={self.database}&q={urllib.parse.quote(influxql)}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", self._auth_header)

        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode())

    def test_connection(self) -> bool:
        """Test connection to InfluxDB."""
        try:
            result = self._query("SHOW DATABASES")
            return "results" in result
        except Exception as e:
            print(f"Connection failed: {e}")
            return False

    def list_entities(self, pattern: str | None = None) -> list[str]:
        """List all entity_ids, optionally filtered by pattern."""
        result = self._query('SHOW TAG VALUES WITH KEY = "entity_id"')

        entities = []
        if "results" in result and result["results"]:
            for series in result["results"][0].get("series", []):
                values = series.get("values", [])
                entities.extend([v[1] for v in values])

        if pattern:
            entities = [e for e in entities if pattern.lower() in e.lower()]

        return sorted(set(entities))

    def get_entity_data(
        self,
        entity_id: str,
        start: datetime,
        end: datetime | None = None,
        measurement: str | None = None,
        resample: str | None = None,
    ) -> pd.DataFrame:
        """Get data for a specific entity.

        Args:
            entity_id: The entity_id to query
            start: Start datetime
            end: End datetime (default: now)
            measurement: Specific measurement (unit) to query, or None for auto-detect
            resample: Resample interval (e.g., '1m', '5m', '1h')

        Returns:
            DataFrame with timestamp index and 'value' column
        """
        end = end or datetime.utcnow()

        # Format times for InfluxQL
        start_str = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = end.strftime("%Y-%m-%dT%H:%M:%SZ")

        # If measurement not specified, try common ones
        measurements_to_try = (
            [measurement] if measurement else ["W", "°C", "kW", "kWh", "%", "state", " "]
        )

        for meas in measurements_to_try:
            if resample:
                # Convert resample string to InfluxQL format
                q = f"""SELECT mean("value") as value FROM "{meas}" 
                        WHERE "entity_id" = '{entity_id}' 
                        AND time >= '{start_str}' AND time <= '{end_str}' 
                        GROUP BY time({resample}) fill(none)"""
            else:
                q = f"""SELECT "value" FROM "{meas}" 
                        WHERE "entity_id" = '{entity_id}' 
                        AND time >= '{start_str}' AND time <= '{end_str}' """

            result = self._query(q)

            if "results" in result and result["results"]:
                series = result["results"][0].get("series", [])
                if series and series[0].get("values"):
                    values = series[0]["values"]
                    df = pd.DataFrame(values, columns=["time", "value"])
                    df["time"] = pd.to_datetime(df["time"])
                    df = df.set_index("time")
                    df["value"] = pd.to_numeric(df["value"], errors="coerce")
                    return df

        return pd.DataFrame(columns=["value"])

    def get_multiple_entities(
        self,
        entity_ids: list[str],
        start: datetime,
        end: datetime | None = None,
        resample: str = "1m",
    ) -> pd.DataFrame:
        """Get data for multiple entities, aligned by timestamp.

        Returns DataFrame with entity_ids as columns.
        """
        dfs = {}
        for entity_id in entity_ids:
            df = self.get_entity_data(entity_id, start, end, resample=resample)
            if not df.empty:
                dfs[entity_id] = df["value"]

        if not dfs:
            return pd.DataFrame()

        result = pd.DataFrame(dfs)
        result = result.sort_index()
        return result


def test_connection_quick():
    """Quick connection test."""
    client = InfluxV1Client()
    print(f"Testing connection to {client.base_url}...")
    if client.test_connection():
        print("✓ Connected!")
        entities = client.list_entities("ac_")
        print(f"Found {len(entities)} AC entities")
        return True
    else:
        print("✗ Connection failed")
        return False


if __name__ == "__main__":
    test_connection_quick()
