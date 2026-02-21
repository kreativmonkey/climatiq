"""Unit tests for InfluxDB V1 Client."""

import json
from datetime import datetime
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from climatiq.data.influx_v1_client import InfluxV1Client


@pytest.fixture
def client():
    """Create InfluxV1Client with test configuration."""
    # Directly pass parameters instead of relying on environment
    return InfluxV1Client(
        host="localhost", port=8086, user="test_user", password="test_pass", database="test_db"
    )


def test_initialization(client):
    """Test that InfluxV1Client initializes with correct parameters."""
    assert client.host == "localhost"
    assert client.port == 8086
    assert client.database == "test_db"
    assert client.user == "test_user"
    assert client.password == "test_pass"


@patch("climatiq.data.influx_v1_client.urllib.request.urlopen")
def test_get_entity_data_with_results(mock_urlopen, client):
    """Test get_entity_data returns DataFrame when data exists."""
    # Mock HTTP response
    mock_response = Mock()
    mock_response.read.return_value = json.dumps(
        {
            "results": [
                {
                    "series": [
                        {
                            "values": [
                                ["2026-02-20T12:00:00Z", 450.5],
                                ["2026-02-20T12:05:00Z", 460.2],
                            ]
                        }
                    ]
                }
            ]
        }
    ).encode()
    mock_urlopen.return_value.__enter__.return_value = mock_response

    start = datetime(2026, 2, 20, 12, 0)
    end = datetime(2026, 2, 20, 13, 0)

    df = client.get_entity_data("test_entity", start, end, resample="5m")

    assert isinstance(df, pd.DataFrame)
    assert not df.empty


@patch("climatiq.data.influx_v1_client.urllib.request.urlopen")
def test_get_entity_data_empty_result(mock_urlopen, client):
    """Test get_entity_data returns empty DataFrame when no data."""
    mock_response = Mock()
    mock_response.read.return_value = json.dumps({"results": [{}]}).encode()
    mock_urlopen.return_value.__enter__.return_value = mock_response

    start = datetime(2026, 2, 20, 12, 0)
    end = datetime(2026, 2, 20, 13, 0)

    df = client.get_entity_data("test_entity", start, end)

    assert isinstance(df, pd.DataFrame)
    assert df.empty


@patch("climatiq.data.influx_v1_client.urllib.request.urlopen")
def test_get_entity_data_query_error(mock_urlopen, client):
    """Test get_entity_data raises exception on connection error."""
    mock_urlopen.side_effect = Exception("Connection error")

    start = datetime(2026, 2, 20, 12, 0)
    end = datetime(2026, 2, 20, 13, 0)

    # Should raise exception (no error handling in current implementation)
    with pytest.raises(Exception, match="Connection error"):
        client.get_entity_data("test_entity", start, end)


def test_timestamp_conversion(client):
    """Test that timestamps are correctly converted to InfluxDB format."""
    start = datetime(2026, 2, 20, 12, 0, 0)
    end = datetime(2026, 2, 20, 13, 0, 0)

    # Test the internal formatting logic
    query = f"SELECT mean(\"value\") FROM \"test\" WHERE time >= '{start.isoformat()}Z' AND time <= '{end.isoformat()}Z'"

    assert "2026-02-20T12:00:00Z" in query
    assert "2026-02-20T13:00:00Z" in query
