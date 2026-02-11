"""Predictor module for forecasting cycling events.

Uses machine learning to predict when the compressor will start cycling,
allowing preemptive action to prevent it.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import precision_recall_fscore_support
from sklearn.model_selection import cross_val_score, train_test_split

logger = logging.getLogger(__name__)


class CyclingPredictor:
    """Predicts cycling events using supervised learning.

    The model learns from historical data to predict:
    "Will the system start cycling in the next N minutes?"
    """

    PREDICTION_HORIZON_MINUTES = 10  # Predict cycling within next 10 min
    MIN_TRAINING_SAMPLES = 500
    FEATURE_COLUMNS = [
        "power",
        "power_trend",
        "power_std",
        "outdoor_temp",
        "avg_room_temp",
        "temp_diff",
        "hour",
        "active_units",
        "compressor_runtime",
    ]

    def __init__(self, model_path: Path | None = None):
        self.model_path = model_path
        self.model: RandomForestClassifier | None = None
        self.is_trained = False
        self.feature_importance: dict[str, float] = {}
        self.metrics: dict[str, float] = {}
        self._load_model()

    def _load_model(self):
        """Try to load existing model from disk."""
        if self.model_path and self.model_path.exists():
            try:
                data = joblib.load(self.model_path)
                self.model = data["model"]
                self.feature_importance = data.get("feature_importance", {})
                self.metrics = data.get("metrics", {})
                self.is_trained = True
                logger.info(f"Loaded model from {self.model_path}")
            except Exception as e:
                logger.warning(f"Could not load model: {e}")

    def save_model(self):
        """Save model to disk."""
        if self.model and self.model_path:
            data = {
                "model": self.model,
                "feature_importance": self.feature_importance,
                "metrics": self.metrics,
                "saved_at": datetime.now(UTC).isoformat(),
            }
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(data, self.model_path)
            logger.info(f"Saved model to {self.model_path}")

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Prepare feature matrix from raw data.

        Args:
            df: DataFrame with columns like 'power', 'outdoor_temp', etc.

        Returns:
            DataFrame with engineered features
        """
        features = pd.DataFrame(index=df.index)

        # Power features
        features["power"] = df["power"]
        features["power_trend"] = df["power"].diff(5).fillna(0)  # 5-min trend
        features["power_std"] = df["power"].rolling(10, min_periods=1).std().fillna(0)

        # Temperature features
        if "outdoor_temp" in df.columns:
            features["outdoor_temp"] = df["outdoor_temp"].ffill().bfill().fillna(10.0)
        else:
            features["outdoor_temp"] = 10.0  # Default

        # Room temperatures - average if multiple
        room_cols = [c for c in df.columns if "room_temp" in c or c.endswith("_temp")]
        room_cols = [c for c in room_cols if c != "outdoor_temp"]
        if room_cols:
            features["avg_room_temp"] = df[room_cols].mean(axis=1).fillna(21.0)
        else:
            features["avg_room_temp"] = 21.0

        # Temperature difference from target (assumed 21°C)
        target_temp = 21.0
        features["temp_diff"] = features["avg_room_temp"] - target_temp

        # Time features
        features["hour"] = df.index.hour

        # Active units (if available)
        if "active_units" in df.columns:
            features["active_units"] = df["active_units"]
        else:
            features["active_units"] = 1

        # Compressor runtime (minutes since last start)
        if "compressor_on" in df.columns:
            starts = df["compressor_on"].diff() == 1
            runtime = pd.Series(0, index=df.index)
            current_runtime = 0
            for i, (idx, is_start) in enumerate(starts.items()):
                if is_start:
                    current_runtime = 0
                elif df.loc[idx, "compressor_on"]:
                    current_runtime += 1
                runtime.iloc[i] = current_runtime
            features["compressor_runtime"] = runtime
        else:
            features["compressor_runtime"] = 0

        return features

    def prepare_labels(self, df: pd.DataFrame) -> pd.Series:
        """Create labels: 1 if cycling occurs within prediction horizon."""
        if "state_change" not in df.columns:
            raise ValueError("DataFrame must have 'state_change' column")

        # Rolling sum of state changes in next N minutes
        horizon = self.PREDICTION_HORIZON_MINUTES
        future_cycles = (
            df["state_change"].iloc[::-1].rolling(horizon, min_periods=1).sum().iloc[::-1]
        )

        # Label is 1 if any cycling in the horizon
        labels = (future_cycles >= 2).astype(int)  # 2 changes = 1 full cycle

        return labels

    def train(self, df: pd.DataFrame) -> dict[str, Any]:
        """Train the prediction model on historical data.

        Args:
            df: DataFrame with power, temperatures, and cycling info

        Returns:
            Dict with training metrics
        """
        logger.info(f"Starting training with {len(df)} samples")

        if len(df) < self.MIN_TRAINING_SAMPLES:
            return {
                "success": False,
                "error": f"Nicht genug Daten: {len(df)} < {self.MIN_TRAINING_SAMPLES}",
            }

        # Prepare features and labels
        X = self.prepare_features(df)
        y = self.prepare_labels(df)

        # Align and clean
        common_idx = X.index.intersection(y.index)
        X = X.loc[common_idx]
        y = y.loc[common_idx]

        # Drop NaN
        mask = ~(X.isna().any(axis=1) | y.isna())
        X = X[mask]
        y = y[mask]

        if len(X) < self.MIN_TRAINING_SAMPLES:
            return {"success": False, "error": f"Nach Bereinigung nur {len(X)} Samples übrig"}

        # Select only available feature columns
        available_features = [c for c in self.FEATURE_COLUMNS if c in X.columns]
        X = X[available_features]

        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        # Train model
        self.model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            min_samples_leaf=10,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )

        self.model.fit(X_train, y_train)

        # Evaluate
        y_pred = self.model.predict(X_test)
        precision, recall, f1, _ = precision_recall_fscore_support(
            y_test, y_pred, average="binary", zero_division=0
        )

        # Cross-validation
        cv_scores = cross_val_score(self.model, X, y, cv=5, scoring="f1")

        # Feature importance
        self.feature_importance = dict(zip(available_features, self.model.feature_importances_))

        self.metrics = {
            "precision": float(precision),
            "recall": float(recall),
            "f1_score": float(f1),
            "cv_f1_mean": float(cv_scores.mean()),
            "cv_f1_std": float(cv_scores.std()),
            "training_samples": len(X_train),
            "test_samples": len(X_test),
            "positive_ratio": float(y.mean()),
        }

        self.is_trained = True
        self.save_model()

        logger.info(f"Training complete. F1 Score: {f1:.3f}")

        return {
            "success": True,
            "metrics": self.metrics,
            "feature_importance": self.feature_importance,
        }

    def predict(self, current_state: pd.DataFrame) -> dict[str, Any]:
        """Predict if cycling will occur soon.

        Args:
            current_state: Recent data (last ~30 minutes)

        Returns:
            Dict with prediction and confidence
        """
        if not self.is_trained or self.model is None:
            return {
                "cycling_predicted": False,
                "probability": 0.0,
                "confidence": 0.0,
                "status": "model_not_trained",
            }

        # Prepare features from most recent data point
        features = self.prepare_features(current_state)

        if features.empty:
            return {
                "cycling_predicted": False,
                "probability": 0.0,
                "confidence": 0.0,
                "status": "no_data",
            }

        # Use last row
        X = features.iloc[[-1]]

        # Select available features
        available = [c for c in self.FEATURE_COLUMNS if c in X.columns]
        X = X[available]

        # Handle missing features
        for col in self.FEATURE_COLUMNS:
            if col not in X.columns:
                X[col] = 0

        X = X[self.FEATURE_COLUMNS]

        # Predict
        try:
            proba = self.model.predict_proba(X)[0]
            cycling_prob = proba[1] if len(proba) > 1 else proba[0]
            prediction = cycling_prob > 0.5

            return {
                "cycling_predicted": bool(prediction),
                "probability": float(cycling_prob),
                "confidence": float(abs(cycling_prob - 0.5) * 2),  # 0 at 50%, 1 at 0% or 100%
                "status": "ok",
                "horizon_minutes": self.PREDICTION_HORIZON_MINUTES,
            }
        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            return {
                "cycling_predicted": False,
                "probability": 0.0,
                "confidence": 0.0,
                "status": f"error: {str(e)}",
            }

    def get_dashboard_data(self) -> dict[str, Any]:
        """Get data for Home Assistant dashboard."""
        return {
            "is_trained": self.is_trained,
            "metrics": self.metrics,
            "feature_importance": self.feature_importance,
            "prediction_horizon": self.PREDICTION_HORIZON_MINUTES,
        }
