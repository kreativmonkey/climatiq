"""Tests for CyclingPredictor class."""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from climatiq.core.predictor import CyclingPredictor


@pytest.fixture
def predictor():
    """Create a Predictor instance without model path."""
    return CyclingPredictor(model_path=None)


@pytest.fixture
def training_data():
    """Create training data with cycling patterns."""
    np.random.seed(42)

    # Create 7 days of data
    times = pd.date_range(
        start=datetime.now(UTC) - timedelta(days=7), periods=7 * 24 * 60, freq="1min"
    )

    n = len(times)

    # Simulate power with cycling
    power = np.zeros(n)
    compressor_on = np.zeros(n, dtype=bool)

    i = 0
    while i < n:
        on_time = np.random.randint(5, 30)
        off_time = np.random.randint(2, 15)
        power[i : i + on_time] = np.random.normal(600, 100, min(on_time, n - i))
        compressor_on[i : i + on_time] = True
        i += on_time
        if i >= n:
            break
        power[i : i + off_time] = np.random.normal(50, 20, min(off_time, n - i))
        compressor_on[i : i + off_time] = False
        i += off_time

    df = pd.DataFrame(
        {
            "power": power,
            "compressor_on": compressor_on,
            "outdoor_temp": np.random.normal(5, 3, n),
        },
        index=times,
    )

    df["state_change"] = df["compressor_on"].astype(int).diff().abs().fillna(0)

    return df


class TestPredictor:
    """Tests for CyclingPredictor class."""

    def test_initialization(self, predictor):
        assert predictor.is_trained is False
        assert predictor.model is None

    def test_prepare_features(self, predictor, training_data):
        features = predictor.prepare_features(training_data)
        assert "power" in features.columns
        assert "power_trend" in features.columns
        assert "power_std" in features.columns
        assert "hour" in features.columns
        assert len(features) == len(training_data)

    def test_prepare_labels(self, predictor, training_data):
        labels = predictor.prepare_labels(training_data)
        assert len(labels) == len(training_data)
        assert labels.sum() > 0
        assert labels.sum() < len(labels)

    def test_train_insufficient_data(self, predictor):
        small_data = pd.DataFrame(
            {"power": [100, 200, 300], "state_change": [0, 1, 0]},
            index=pd.date_range("2024-01-01", periods=3, freq="1min"),
        )

        result = predictor.train(small_data)
        assert result["success"] is False
        assert "error" in result

    def test_train_success(self, predictor, training_data):
        result = predictor.train(training_data)
        assert result["success"] is True
        assert "metrics" in result
        assert predictor.is_trained is True
        assert predictor.model is not None

    def test_predict_untrained(self, predictor, training_data):
        result = predictor.predict(training_data.tail(30))
        assert result["cycling_predicted"] is False
        assert result["status"] == "model_not_trained"

    def test_predict_after_training(self, predictor, training_data):
        predictor.train(training_data)
        recent = training_data.tail(30)
        result = predictor.predict(recent)
        assert "cycling_predicted" in result
        assert "probability" in result
        assert "confidence" in result
        assert result["status"] == "ok"
        assert 0 <= result["probability"] <= 1

    def test_model_persistence(self, training_data):
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "model.joblib"
            predictor1 = CyclingPredictor(model_path=model_path)
            predictor1.train(training_data)
            predictor1.save_model()
            predictor2 = CyclingPredictor(model_path=model_path)
            assert predictor2.is_trained is True
            assert predictor2.model is not None

    def test_get_dashboard_data_untrained(self, predictor):
        data = predictor.get_dashboard_data()
        assert data["is_trained"] is False
        assert data["metrics"] == {}

    def test_get_dashboard_data_trained(self, predictor, training_data):
        predictor.train(training_data)
        data = predictor.get_dashboard_data()
        assert data["is_trained"] is True
        assert "metrics" in data
        assert "feature_importance" in data
