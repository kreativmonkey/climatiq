"""Tests for the Observer module and Cycling analysis."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from climatiq.analysis.cycling_detector import CyclingDetector
from climatiq.core.entities import SystemMode
from climatiq.core.observer import Observer


@pytest.fixture
def observer():
    """Create an Observer instance with default config."""
    config = {
        "cycling": {
            "power_on_threshold": 300,
            "power_off_threshold": 150,
            "fluctuation_threshold_watts": 200,
            "fluctuation_threshold_pct": 0.4,
            "jump_delta": 200.0,
        }
    }
    return Observer(config)


class TestObserver:
    """Tests for Observer class."""

    def test_initialization(self, observer):
        """Test observer initializes correctly."""
        assert observer.status.mode == SystemMode.OBSERVATION
        assert observer.status.power_consumption == 0.0
        assert not observer.status.is_cycling
        assert observer.status.cycling_risk == 0.0
        assert observer._instability_score == 0.0
        assert observer._recent_jumps == []

    def test_update_power(self, observer):
        """Test power update works."""
        observer.update_power(500.0)
        assert observer.status.power_consumption == 500.0
        assert observer.status.last_update is not None

    def test_cycling_risk_with_fluctuations(self, observer):
        """Test that fluctuations increase cycling risk.

        Power oscillates 400W ↔ 800W — both above 'on' threshold but
        highly unstable.  The instability_score-based risk should fire.
        """
        now = datetime.now(UTC)
        for i in range(10):
            ts = now + timedelta(seconds=30 * i)
            value = 800.0 if i % 2 == 0 else 400.0
            observer.update_power(value, timestamp=ts)

        # Risk should be elevated due to amplitude & rolling std
        assert observer.status.cycling_risk > 0.3
        assert observer._instability_score > 0.3

    def test_stable_power_has_low_risk(self, observer):
        """Test that stable high power has low cycling risk."""
        now = datetime.now(UTC)
        for i in range(20):
            ts = now + timedelta(seconds=30 * i)
            observer.update_power(1200.0 + np.random.normal(0, 10), timestamp=ts)

        assert observer.status.cycling_risk < 0.3
        assert observer._instability_score < 0.3
        assert not observer.status.is_cycling

    def test_is_cycling_on_short_cycles(self, observer):
        """Traditional on/off cycling should still trigger is_cycling."""
        now = datetime.now(UTC)
        for i in range(20):
            ts = now + timedelta(seconds=30 * i)
            value = 500.0 if i % 4 < 2 else 50.0  # on 2 samples, off 2 samples
            observer.update_power(value, timestamp=ts)

        assert observer.status.is_cycling is True

    def test_get_summary_contains_new_fields(self, observer):
        """Test summary includes instability_score and recent_jumps."""
        observer.update_power(500.0)
        observer.update_unit("room1", {"is_on": True, "entity_id": "climate.room1"})

        summary = observer.get_summary()

        assert "mode" in summary
        assert "power" in summary
        assert "active_units" in summary
        assert "instability_score" in summary
        assert "recent_jumps" in summary
        assert summary["power"] == 500.0
        assert summary["active_units"] == 1
        assert isinstance(summary["instability_score"], float)
        assert isinstance(summary["recent_jumps"], list)

    def test_recent_jumps_populated(self, observer):
        """Test that recent_jumps are populated on large power swings."""
        now = datetime.now(UTC)
        values = [500, 500, 1000, 500, 500, 1000, 500, 500, 1000, 500]
        for i, v in enumerate(values):
            ts = now + timedelta(seconds=30 * i)
            observer.update_power(float(v), timestamp=ts)

        summary = observer.get_summary()
        assert len(summary["recent_jumps"]) > 0
        # Each jump entry should have time and delta
        for j in summary["recent_jumps"]:
            assert "time" in j
            assert "delta" in j

    def test_cycling_risk_not_hardcoded(self, observer):
        """cycling_risk must NOT be based on hard-coded power bands.

        A constant 300W (previously in the 150-450 'danger' band) should
        have LOW risk if it's perfectly stable.
        """
        now = datetime.now(UTC)
        for i in range(20):
            ts = now + timedelta(seconds=30 * i)
            observer.update_power(300.0, timestamp=ts)

        # Perfectly stable at 300W → low risk
        assert observer.status.cycling_risk < 0.3


class TestCyclingDetectorV2:
    """Tests for the CyclingDetector with fluctuation/jump methods."""

    @pytest.fixture
    def detector(self):
        return CyclingDetector(
            power_on_threshold=300,
            power_off_threshold=150,
            fluctuation_threshold_watts=200,
            window_minutes=5,
        )

    def test_detect_fluctuations(self, detector):
        """Test detection of instability within 'on' state."""
        times = pd.date_range("2024-01-01", periods=20, freq="1min")
        power = [400, 900, 400, 900, 400, 900, 400, 900, 400, 900] * 2
        series = pd.Series(power, index=times)

        fluctuations = detector.detect_fluctuations(series)
        assert len(fluctuations) > 0
        # FluctuationEvent has mean_power, max_drop, max_rise, duration_minutes
        assert fluctuations[0].duration_minutes > 0

    def test_detect_power_jumps(self, detector):
        """Test detection of rapid power jumps."""
        times = pd.date_range("2024-01-01", periods=5, freq="1min")
        power = [500, 510, 1000, 1010, 500]  # Jump of +490W and -510W
        series = pd.Series(power, index=times)

        jumps = detector.detect_power_jumps(series)
        # Returns list[tuple[Timestamp, float]]
        assert len(jumps) >= 2
        deltas = [d for _, d in jumps]
        assert any(d > 400 for d in deltas)
        assert any(d < -400 for d in deltas)

    def test_analyze_cycling_compatibility(self, detector):
        """Ensure analyze_cycling still returns expected keys."""
        times = pd.date_range("2024-01-01", periods=10, freq="1min")
        series = pd.Series([100, 500, 500, 100, 100, 500, 500, 100, 100, 100], index=times)

        analysis = detector.analyze_cycling(series)
        assert "cycles" in analysis
        assert "total_cycles" in analysis
        assert "short_cycle_count" in analysis

    def test_empty_series(self, detector):
        """Empty series should return empty results."""
        series = pd.Series([], dtype=float)
        assert detector.detect_fluctuations(series) == []
        assert detector.detect_power_jumps(series) == []
        result = detector.analyze_cycling(series)
        assert result["total_cycles"] == 0


class TestInstabilityScore:
    """Tests for Observer._compute_instability_score."""

    def test_stable_signal(self):
        """A flat signal should have near-zero instability."""
        times = pd.date_range("2024-01-01", periods=30, freq="1min")
        series = pd.Series([1000.0] * 30, index=times)
        score = Observer._compute_instability_score(series, [])
        assert score < 0.1

    def test_highly_unstable_signal(self):
        """Large oscillations with many jumps → high score."""
        times = pd.date_range("2024-01-01", periods=30, freq="1min")
        power = [300.0, 1500.0] * 15
        series = pd.Series(power, index=times)
        jumps = [(times[i], power[i] - power[i - 1]) for i in range(1, 30)]
        score = Observer._compute_instability_score(series, jumps)
        assert score > 0.7

    def test_zero_power(self):
        """Off state (near zero) should return 0."""
        times = pd.date_range("2024-01-01", periods=10, freq="1min")
        series = pd.Series([0.0] * 10, index=times)
        score = Observer._compute_instability_score(series, [])
        assert score == 0.0
