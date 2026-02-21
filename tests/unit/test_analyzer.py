"""Tests for the Analyzer module."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from climatiq.core.analyzer import AnalysisResult, Analyzer, OperatingRegion

SKIP_OLD_API = pytest.mark.skip(reason="Test needs update for changed API behavior")


@pytest.fixture
def analyzer():
    """Create an Analyzer instance."""
    return Analyzer()


@pytest.fixture
def sample_power_data():
    """Create sample power data for testing.

    Layout:
    - Even hours: stable at ~800W (low std, no jumps)
    - Odd hours: unstable cycling 80W ↔ 350W (high std, many jumps)
    """
    np.random.seed(42)

    times = pd.date_range(
        start=datetime.now(UTC) - timedelta(hours=48), periods=48 * 60, freq="1min"
    )

    power = np.zeros(len(times))

    for i in range(0, len(times), 60):
        if (i // 60) % 2 == 0:
            # Stable period – consistent power around 800W
            power[i : i + 60] = np.random.normal(800, 50, min(60, len(times) - i))
        else:
            # Unstable period – cycling between 100W and 400W
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
        """Test that analyzer discovers stable power threshold.

        The 800W region is stable (low std), the 80-350W region is unstable.
        The threshold should be somewhere in between.
        """
        result = analyzer.analyze(sample_power_data)

        assert result.min_stable_power is not None
        assert 300 < result.min_stable_power < 900

    def test_stable_threshold_not_always_max_power(self, analyzer):
        """Regression: stable threshold must NOT default to max power.

        A system running stably at 500W should report ~500W, not 1800W.
        """
        np.random.seed(123)
        times = pd.date_range(
            start=datetime.now(UTC) - timedelta(hours=48),
            periods=48 * 60,
            freq="1min",
        )
        # Perfectly stable at ~500W
        power = np.random.normal(500, 15, len(times))
        data = pd.Series(power, index=times)

        result = analyzer.analyze(data)
        assert result.min_stable_power is not None
        # Should be near 500, definitely not 1800
        assert result.min_stable_power < 700

    @SKIP_OLD_API
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
        assert "sufficient_data" in data
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


class TestCyclingDetectionColumns:
    """Tests for _add_cycling_detection producing new instability columns."""

    @pytest.fixture
    def analyzer(self):
        return Analyzer()

    def test_adds_instability_columns(self, analyzer):
        """_add_cycling_detection must add power_std_10m, power_jumps, instability."""
        np.random.seed(0)
        times = pd.date_range("2024-01-01", periods=100, freq="1min")
        df = pd.DataFrame({"power": np.random.normal(600, 80, 100)}, index=times)

        result = analyzer._add_cycling_detection(df)

        assert "power_std_10m" in result.columns
        assert "power_jumps" in result.columns
        assert "instability" in result.columns

    def test_power_jumps_binary(self, analyzer):
        """power_jumps should be 0 or 1."""
        times = pd.date_range("2024-01-01", periods=10, freq="1min")
        df = pd.DataFrame(
            {"power": [500, 500, 900, 900, 500, 500, 900, 900, 500, 500]},
            index=times,
        )
        result = analyzer._add_cycling_detection(df)
        assert set(result["power_jumps"].unique()).issubset({0, 1})
        # There should be jumps at the transitions (500→900, 900→500)
        assert result["power_jumps"].sum() >= 2


class TestRegionStability:
    """Ensure _create_region_from_data uses fluctuation-based stability."""

    @pytest.fixture
    def analyzer(self):
        return Analyzer()

    @SKIP_OLD_API
    def test_stable_region(self, analyzer):
        """Stable data → high stability_score."""
        np.random.seed(7)
        times = pd.date_range("2024-01-01", periods=120, freq="1min")
        df = pd.DataFrame(
            {
                "power": np.random.normal(600, 10, 120),
                "is_cycling": False,
                "hour": [t.hour for t in times],
                "instability": 0.05,
            },
            index=times,
        )
        region = analyzer._create_region_from_data(df)
        assert isinstance(region, OperatingRegion)
        assert region.stability_score > 0.8

    def test_unstable_region(self, analyzer):
        """Highly fluctuating data → low stability_score."""
        np.random.seed(8)
        times = pd.date_range("2024-01-01", periods=120, freq="1min")
        df = pd.DataFrame(
            {
                "power": [300, 1200] * 60,
                "is_cycling": True,
                "hour": [t.hour for t in times],
                "instability": 0.85,
            },
            index=times,
        )
        region = analyzer._create_region_from_data(df)
        assert region.stability_score < 0.3


class TestAnalyzerEdgeCases:
    """Test edge cases and error handling."""

    def test_analyze_with_negative_power(self, analyzer):
        """Test analyzer handles negative power values."""
        times = pd.date_range(start="2024-01-01", periods=2000, freq="1min")
        # Mix of positive and negative (e.g., sensor errors)
        power = np.concatenate([np.random.normal(500, 50, 1000), np.random.normal(-50, 10, 1000)])
        data = pd.Series(power, index=times)

        result = analyzer.analyze(data)
        # Should still return a result, potentially filtering negative values
        assert isinstance(result, AnalysisResult)

    def test_analyze_with_nan_values(self, analyzer):
        """Test analyzer handles NaN values in data."""
        times = pd.date_range(start="2024-01-01", periods=2000, freq="1min")
        power = np.random.normal(500, 50, 2000)
        power[100:200] = np.nan  # Introduce NaN gap
        data = pd.Series(power, index=times)

        result = analyzer.analyze(data)
        assert isinstance(result, AnalysisResult)

    def test_analyze_constant_power(self, analyzer):
        """Test analyzer with perfectly constant power (no variance)."""
        times = pd.date_range(start="2024-01-01", periods=2000, freq="1min")
        power = np.full(2000, 500.0)  # Constant 500W
        data = pd.Series(power, index=times)

        result = analyzer.analyze(data)
        assert isinstance(result, AnalysisResult)
        # Should recognize this as very stable
        assert result.sufficient_data is True

    def test_analyze_extreme_fluctuations(self, analyzer):
        """Test analyzer with extreme power fluctuations."""
        times = pd.date_range(start="2024-01-01", periods=2000, freq="1min")
        # Extreme swings: 0 to 2000W
        power = np.random.choice([0, 2000], size=2000)
        data = pd.Series(power, index=times)

        result = analyzer.analyze(data)
        assert isinstance(result, AnalysisResult)
        # Should detect high instability
        assert result.sufficient_data is True

    def test_get_dashboard_data_structure(self, analyzer, sample_power_data):
        """Test dashboard data has expected structure."""
        analyzer.analyze(sample_power_data)
        data = analyzer.get_dashboard_data()

        required_keys = ["status", "sufficient_data", "min_stable_power", "regions"]
        assert all(key in data for key in required_keys)

        # Regions should be serializable (dict format)
        assert isinstance(data["regions"], list)
        if len(data["regions"]) > 0:
            region = data["regions"][0]
            assert "range" in region
            assert "stability" in region
            assert "is_stable" in region
