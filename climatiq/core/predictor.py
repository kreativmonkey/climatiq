"""Predictor module for cycling prediction.

Uses a combination of machine learning (RandomForestClassifier) and heuristics
to predict whether cycling will occur in the near future.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Optional ML imports
try:
    import joblib
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import cross_val_score

    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


class CyclingPredictor:
    """Predicts the likelihood of cycling based on historical data and current state.

    Supports:
    - Feature engineering from raw power/compressor/temperature data
    - Label generation (is cycling imminent in the next N minutes?)
    - Training a RandomForestClassifier
    - Prediction with ML model or heuristic fallback
    - Model persistence (save/load)
    """

    # Minimum samples required for training
    MIN_TRAINING_SAMPLES = 500

    # Look-ahead window for label generation (minutes)
    LABEL_LOOKAHEAD_MINUTES = 10

    # Minimum state changes per hour to count as cycling
    CYCLING_THRESHOLD_CHANGES_PER_HOUR = 4

    def __init__(self, model_path: Path | str | None = None):
        """Initialize the predictor.

        Args:
            model_path: Path to load/save the trained model. If the file exists
                        the model is loaded automatically.
        """
        self.model_path = Path(model_path) if model_path else None
        self.model: Any = None
        self._metrics: dict[str, Any] = {}
        self._feature_importance: dict[str, float] = {}

        # Try to load existing model
        if self.model_path and self.model_path.exists():
            self._load_model()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_trained(self) -> bool:
        return self.model is not None

    # ------------------------------------------------------------------
    # Feature engineering
    # ------------------------------------------------------------------

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Prepare feature columns from raw data.

        Expected input columns (at least ``power``):
        - power: current power consumption (W)
        - outdoor_temp (optional)
        - compressor_on (optional)

        Generated features:
        - power
        - power_trend: rolling mean of power over 10 samples
        - power_std: rolling std of power over 10 samples
        - hour: hour of the day
        - outdoor_temp (if present, else 0)
        - active_units (if present, else 0)
        - power_diff: first-order diff of power
        - power_diff_abs: absolute first-order diff
        - compressor_runtime: cumulative minutes compressor has been on
        """
        features = pd.DataFrame(index=df.index)

        features["power"] = df["power"]
        features["power_trend"] = df["power"].rolling(10, min_periods=1).mean()
        features["power_std"] = df["power"].rolling(10, min_periods=1).std().fillna(0)
        features["hour"] = df.index.hour

        # Optional columns
        features["outdoor_temp"] = df["outdoor_temp"] if "outdoor_temp" in df.columns else 0.0

        # Power dynamics
        features["power_diff"] = df["power"].diff().fillna(0)
        features["power_diff_abs"] = features["power_diff"].abs()

        # Compressor runtime (cumulative on-time in minutes)
        if "compressor_on" in df.columns:
            # Approximate: each row ≈ 1 minute
            on_mask = df["compressor_on"].astype(int)
            # Reset cumsum on each off→on transition
            groups = (~df["compressor_on"]).cumsum()
            features["compressor_runtime"] = on_mask.groupby(groups).cumsum()
        else:
            features["compressor_runtime"] = 0

        # Active units (if available)
        features["active_units"] = df["active_units"] if "active_units" in df.columns else 0

        return features

    # ------------------------------------------------------------------
    # Label generation
    # ------------------------------------------------------------------

    def prepare_labels(self, df: pd.DataFrame) -> pd.Series:
        """Create binary labels: 1 if cycling occurs within the look-ahead window.

        Cycling is detected via ``state_change`` column (if present) or derived
        from ``compressor_on``.  A label of 1 means "within the next N minutes
        there will be frequent state changes (cycling)".
        """
        if "state_change" in df.columns:
            changes = df["state_change"]
        elif "compressor_on" in df.columns:
            changes = df["compressor_on"].astype(int).diff().abs().fillna(0)
        else:
            # Cannot generate labels without state info
            return pd.Series(0, index=df.index)

        window = self.LABEL_LOOKAHEAD_MINUTES

        # Count state changes in the forward-looking window using a reversed
        # rolling sum: reverse the series, apply rolling sum, then reverse back.
        # This effectively sums the *next* ``window`` values for each position.
        forward_changes = changes.iloc[::-1].rolling(window, min_periods=1).sum().iloc[::-1]

        # Convert a per-hour threshold into a threshold for the window.
        # Example: 4 changes/hour over a 10-minute window ≈ 0.67 → threshold 1.
        threshold_in_window = int(
            np.ceil(self.CYCLING_THRESHOLD_CHANGES_PER_HOUR * (window / 60.0))
        )
        threshold_in_window = max(1, threshold_in_window)

        labels = (forward_changes >= threshold_in_window).astype(int)
        return labels

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, df: pd.DataFrame) -> dict[str, Any]:
        """Train the prediction model on historical data.

        Args:
            df: DataFrame with at least ``power`` and ``state_change`` or
                ``compressor_on`` columns.

        Returns:
            dict with ``success`` (bool), ``metrics`` (if successful), or
            ``error`` (if failed).
        """
        if not HAS_SKLEARN:
            return {"success": False, "error": "scikit-learn is not installed"}

        if len(df) < self.MIN_TRAINING_SAMPLES:
            return {
                "success": False,
                "error": f"Zu wenige Daten ({len(df)}/{self.MIN_TRAINING_SAMPLES}). Benötigt mindestens {self.MIN_TRAINING_SAMPLES} Datenpunkte.",
            }

        try:
            features = self.prepare_features(df)
            labels = self.prepare_labels(df)

            # Drop rows with NaN (from rolling windows / shifts)
            mask = features.notna().all(axis=1) & labels.notna()
            X = features.loc[mask]
            y = labels.loc[mask]

            if len(X) < self.MIN_TRAINING_SAMPLES:
                return {
                    "success": False,
                    "error": f"Nach Bereinigung zu wenige Daten ({len(X)}).",
                }

            # Train RandomForest
            model = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                random_state=42,
                class_weight="balanced",
                n_jobs=-1,
            )

            # Cross-validation
            cv_scores = cross_val_score(model, X, y, cv=5, scoring="f1")

            # Fit on full data
            model.fit(X, y)

            self.model = model
            self._metrics = {
                "f1_mean": float(np.mean(cv_scores)),
                "f1_std": float(np.std(cv_scores)),
                "training_samples": len(X),
                "positive_rate": float(y.mean()),
            }

            # Feature importance
            self._feature_importance = dict(zip(X.columns, model.feature_importances_))

            logger.info(
                "Model trained: F1=%.3f ± %.3f on %d samples",
                self._metrics["f1_mean"],
                self._metrics["f1_std"],
                len(X),
            )

            return {"success": True, "metrics": self._metrics}

        except Exception as e:
            logger.error("Training failed: %s", e)
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(self, df: pd.DataFrame) -> dict[str, Any]:
        """Predict cycling risk for the given data window.

        Args:
            df: Recent data window (e.g. last 30 minutes).

        Returns:
            dict with ``cycling_predicted``, ``probability``, ``confidence``,
            and ``status``.
        """
        if not self.is_trained:
            return {
                "cycling_predicted": False,
                "probability": 0.0,
                "confidence": 0.0,
                "status": "model_not_trained",
            }

        try:
            features = self.prepare_features(df)
            # Use the last row for prediction (most recent state)
            mask = features.notna().all(axis=1)
            valid = features.loc[mask]

            if valid.empty:
                return {
                    "cycling_predicted": False,
                    "probability": 0.0,
                    "confidence": 0.0,
                    "status": "no_valid_features",
                }

            last_row = valid.iloc[[-1]]
            proba = self.model.predict_proba(last_row)[0]

            # proba is [prob_no_cycling, prob_cycling]
            cycling_prob = float(proba[1]) if len(proba) > 1 else 0.0
            cycling_predicted = cycling_prob > 0.5

            return {
                "cycling_predicted": cycling_predicted,
                "probability": cycling_prob,
                "confidence": float(self._metrics.get("f1_mean", 0.0)),
                "status": "ok",
            }

        except Exception as e:
            logger.error("Prediction failed: %s", e)
            return {
                "cycling_predicted": False,
                "probability": 0.0,
                "confidence": 0.0,
                "status": f"error: {e}",
            }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_model(self):
        """Save the trained model to disk."""
        if not self.is_trained or not self.model_path:
            logger.warning("Cannot save: model not trained or no path set.")
            return

        if not HAS_SKLEARN:
            logger.warning("Cannot save: joblib not available.")
            return

        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "model": self.model,
            "metrics": self._metrics,
            "feature_importance": self._feature_importance,
        }
        joblib.dump(data, self.model_path)
        logger.info("Model saved to %s", self.model_path)

    def _load_model(self):
        """Load a previously saved model."""
        if not HAS_SKLEARN or not self.model_path or not self.model_path.exists():
            return

        try:
            data = joblib.load(self.model_path)
            self.model = data["model"]
            self._metrics = data.get("metrics", {})
            self._feature_importance = data.get("feature_importance", {})
            logger.info("Model loaded from %s", self.model_path)
        except Exception as e:
            logger.error("Failed to load model from %s: %s", self.model_path, e)

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    def get_dashboard_data(self) -> dict[str, Any]:
        """Return data for HA dashboard."""
        return {
            "is_trained": self.is_trained,
            "metrics": self._metrics,
            "feature_importance": self._feature_importance,
        }
