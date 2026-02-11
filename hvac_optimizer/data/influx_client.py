"""InfluxDB client for loading historical HVAC data."""

import os
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient


class HVACDataLoader:
    """Load HVAC data from InfluxDB."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        token: Optional[str] = None,
        org: str = "-",
        bucket: Optional[str] = None,
    ):
        """Initialize InfluxDB connection.
        
        Args:
            host: InfluxDB host (default from env)
            port: InfluxDB port (default from env)
            token: InfluxDB token or "user:password" for v1 compat
            org: InfluxDB organization (use "-" for v1 compat)
            bucket: InfluxDB bucket/database
        """
        load_dotenv()

        self.host = host or os.getenv("INFLUXDB_HOST", "localhost")
        self.port = port or int(os.getenv("INFLUXDB_PORT", "8086"))
        self.org = org
        self.bucket = bucket or os.getenv("INFLUXDB_DATABASE", "homeassistant")
        
        # Build token from user:password if not provided
        if token:
            self.token = token
        else:
            user = os.getenv("INFLUXDB_USER", "")
            password = os.getenv("INFLUXDB_PASSWORD", "")
            self.token = f"{user}:{password}"

        self.url = f"http://{self.host}:{self.port}"
        self._client: Optional[InfluxDBClient] = None

    @property
    def client(self) -> InfluxDBClient:
        """Lazy-load InfluxDB client."""
        if self._client is None:
            self._client = InfluxDBClient(
                url=self.url,
                token=self.token,
                org=self.org,
            )
        return self._client

    def test_connection(self) -> bool:
        """Test if connection to InfluxDB works."""
        try:
            health = self.client.health()
            return health.status == "pass"
        except Exception as e:
            print(f"Connection failed: {e}")
            return False

    def list_measurements(self) -> list[str]:
        """List available measurements in the bucket."""
        query = f'''
        import "influxdata/influxdb/schema"
        schema.measurements(bucket: "{self.bucket}")
        '''
        try:
            result = self.client.query_api().query(query, org=self.org)
            measurements = []
            for table in result:
                for record in table.records:
                    measurements.append(record.get_value())
            return sorted(measurements)
        except Exception as e:
            print(f"Error listing measurements: {e}")
            return []

    def list_fields(self, measurement: str) -> list[str]:
        """List available fields for a measurement."""
        query = f'''
        import "influxdata/influxdb/schema"
        schema.measurementFieldKeys(
            bucket: "{self.bucket}",
            measurement: "{measurement}"
        )
        '''
        try:
            result = self.client.query_api().query(query, org=self.org)
            fields = []
            for table in result:
                for record in table.records:
                    fields.append(record.get_value())
            return sorted(fields)
        except Exception as e:
            print(f"Error listing fields: {e}")
            return []

    def query_range(
        self,
        measurement: str,
        fields: list[str],
        start: datetime,
        stop: Optional[datetime] = None,
        entity_id: Optional[str] = None,
    ) -> pd.DataFrame:
        """Query data for a time range.
        
        Args:
            measurement: InfluxDB measurement name
            fields: List of fields to query
            start: Start datetime
            stop: End datetime (default: now)
            entity_id: Optional Home Assistant entity_id filter
            
        Returns:
            DataFrame with timestamp index and field columns
        """
        stop = stop or datetime.utcnow()
        
        # Build field filter
        field_filter = " or ".join([f'r._field == "{f}"' for f in fields])
        
        # Build entity filter
        entity_filter = ""
        if entity_id:
            entity_filter = f'|> filter(fn: (r) => r.entity_id == "{entity_id}")'

        query = f'''
        from(bucket: "{self.bucket}")
            |> range(start: {start.isoformat()}Z, stop: {stop.isoformat()}Z)
            |> filter(fn: (r) => r._measurement == "{measurement}")
            |> filter(fn: (r) => {field_filter})
            {entity_filter}
            |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
        '''
        
        try:
            result = self.client.query_api().query_data_frame(query, org=self.org)
            if isinstance(result, list):
                result = pd.concat(result, ignore_index=True)
            
            if "_time" in result.columns:
                result = result.set_index("_time")
                result.index = pd.to_datetime(result.index)
            
            return result
        except Exception as e:
            print(f"Query failed: {e}")
            return pd.DataFrame()

    def close(self):
        """Close the client connection."""
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Convenience function for quick testing
def test_influx_connection() -> dict:
    """Quick test of InfluxDB connection."""
    loader = HVACDataLoader()
    result = {
        "url": loader.url,
        "bucket": loader.bucket,
        "connected": loader.test_connection(),
        "measurements": [],
    }
    
    if result["connected"]:
        result["measurements"] = loader.list_measurements()[:20]  # First 20
    
    loader.close()
    return result


if __name__ == "__main__":
    # Quick connection test
    print("Testing InfluxDB connection...")
    result = test_influx_connection()
    print(f"URL: {result['url']}")
    print(f"Bucket: {result['bucket']}")
    print(f"Connected: {result['connected']}")
    if result["measurements"]:
        print(f"Sample measurements: {result['measurements']}")
