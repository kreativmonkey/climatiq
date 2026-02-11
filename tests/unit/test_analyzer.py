"""Tests for the Analyzer module."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from climatiq.core.analyzer import AnalysisResult, Analyzer


@pytest.fixture
def analyzer():
    """Create an Analyzer instance."""
    return Analyzer()


@pytest.fixture
def sample_power_data():
    """Create sample power data for testing."""
    np.random.seed(42)

    # Create 48 hours of data at 1-minute resolution
    times = pd.date_range(
        start=datetime.now(UTC) - timedelta(hours=48), periods=48 * 60, freq="1min"
    )

    # Simulate cycling pattern with stable and unstable periods
    power = np.zeros(len(times))

    for i in range(0, len(times), 60):
        # Every hour, alternate between stable (high power) and unstable (low power)
        if (i // 60) % 2 == 0:
            # Stable period - consistent power around 800W
            power[i : i + 60] = np.random.normal(800, 50, min(60, len(times) - i))
        else:
            # Unstable period - cycling between 100W and 400W
            cycle_len = np.random.randint(3, 10)
            j = i
            state = False
            while j < min(i + 60, len(times)):
                if state:
                    power[j : j + cycle_len] = np.random.normal(
                        350, 30, min(cycle_len, len(times) - j)
                    )
                else:
                    power[j : j + cycle_len] = np.random.normal(
                        80, 20, min(cycle_len, len(times) - j)
                    )
                state = not state
                j += cycle_len

    return pd.Series(power, index=times)


class TestAnalyzer:
    """Tests for Analyzer class."""

    def test_initialization(self, analyzer):
        """Test analyzer initializes correctly."""
        assert analyzer.MIN_HOURS_FOR_ANALYSIS == 24
        assert analyzer.MIN_DATAPOINTS == 1000

    def test_check_data_sufficiency_empty(self, analyzer):
        """Test insufficient data detection with empty DataFrame."""
        df = pd.DataFrame()
        sufficient, message = analyzer.check_data_sufficiency(df)

        assert sufficient is False
        assert "Keine Daten" in message

    def test_check_data_sufficiency_too_few_points(self, analyzer):
        """Test insufficient data with too few points."""
        times = pd.date_range(start="2024-01-01", periods=100, freq="1min")
        df = pd.DataFrame({"power": np.random.randn(100)}, index=times)

        sufficient, message = analyzer.check_data_sufficiency(df)

        assert sufficient is False
        assert "Benötigt" in message

    def test_check_data_sufficiency_ok(self, analyzer, sample_power_data):
        """Test sufficient data detection."""
        df = pd.DataFrame({"power": sample_power_data})
        sufficient, message = analyzer.check_data_sufficiency(df)

        assert sufficient is True
        assert "Ausreichend" in message

    def test_analyze_returns_result(self, analyzer, sample_power_data):
        """Test that analyze returns an AnalysisResult."""
        result = analyzer.analyze(sample_power_data)

        assert isinstance(result, AnalysisResult)
        assert result.sufficient_data is True
        assert result.min_stable_power is not None
        assert len(result.regions) > 0

    def test_analyze_discovers_stable_threshold(self, analyzer, sample_power_data):
        """Test that analyzer discovers stable power threshold."""
        result = analyzer.analyze(sample_power_data)

        # The synthetic data has stable operation around 800W
        # and unstable around 350W, so threshold should be in between
        assert result.min_stable_power is not None
        assert 300 < result.min_stable_power < 700

    def test_analyze_insufficient_data(self, analyzer):
        """Test analyze with insufficient data stays in observation mode."""
        times = pd.date_range(start="2024-01-01", periods=100, freq="1min")
        short_data = pd.Series(np.random.randn(100) * 100 + 500, index=times)

        result = analyzer.analyze(short_data)

        assert result.sufficient_data is False
        assert "beobachten" in result.recommendation.lower()

    def test_get_dashboard_data_before_analysis(self, analyzer):
        """Test dashboard data before any analysis."""
        data = analyzer.get_dashboard_data()

        assert data["status"] == "waiting"
        assert data["sufficient_data"] is False

    def test_get_dashboard_data_after_analysis(self, analyzer, sample_power_data):
        """Test dashboard data after analysis."""
        analyzer.analyze(sample_power_data)
        data = analyzer.get_dashboard_data()

        assert data["status"] == "ready"
        assert data["sufficient_data"] is True
        assert "min_stable_power" in data
        assert "regions" in data
        assert len(data["regions"]) > 0
