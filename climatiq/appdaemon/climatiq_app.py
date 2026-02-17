"""AppDaemon App for HVAC Optimizer.

This is the main entry point for Home Assistant integration.
Copy this file to your AppDaemon apps folder.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    import appdaemon.plugins.hass.hassapi as hass
except ImportError:
    # For testing outside AppDaemon
    class hass:
        class Hass:
            pass


from climatiq.core.analyzer import Analyzer
from climatiq.core.controller import ActionType, ControlAction, Controller
from climatiq.core.entities import SystemMode
from climatiq.core.observer import Observer
from climatiq.core.predictor import CyclingPredictor
from climatiq.data.influx_v1_client import InfluxV1Client


class ClimatIQ(hass.Hass):
    """AppDaemon App for intelligent HVAC control."""

    def initialize(self):
        """Initialize the app - called by AppDaemon."""
        self.log("Initializing HVAC Optimizer...")

        # Load configuration from app args
        self.config = self._load_config()

        # Initialize components
        self.observer = Observer(self.config)
        self.analyzer = Analyzer(self.config)
        self.predictor = CyclingPredictor(
            model_path=Path(
                self.config.get("learning", {}).get("model_path", "models/predictor.joblib")
            )
        )
        self.controller = Controller(self.config)
        self.controller.set_action_callback(self._execute_ha_action)

        # Initialize InfluxDB client
        influx_config = self.config.get("influxdb", {})
        self.influx = InfluxV1Client(
            host=influx_config.get("host", "localhost"),
            port=influx_config.get("port", 8086),
            user=influx_config.get("user", ""),
            password=influx_config.get("password", ""),
            database=influx_config.get("database", "homeassistant"),
        )

        # Determine initial mode
        self._determine_initial_mode()

        # Set up state listeners
        self._setup_listeners()

        # Set up periodic tasks
        self._setup_schedules()

        # Create HA sensors for dashboard
        self._create_sensors()

        self.log(f"HVAC Optimizer initialized in {self.observer.status.mode.value} mode")

    def _load_config(self) -> dict[str, Any]:
        """Load configuration from AppDaemon app args."""
        config = {
            "indoor_units": self.args.get("indoor_units", []),
            "power_sensor": self.args.get("power_sensor", ""),
            "outdoor_temp_sensor": self.args.get("outdoor_temp", ""),
            "influxdb": self.args.get("influxdb", {}),
            "comfort": self.args.get("comfort", {}),
            "cycling": self.args.get("cycling", {}),
            "learning": self.args.get("learning", {}),
            "unit_priorities": {},
        }

        # Build priority map from indoor units
        for unit in config["indoor_units"]:
            priority_map = {"low": 10, "medium": 50, "high": 90}
            config["unit_priorities"][unit.get("name", "")] = priority_map.get(
                unit.get("priority", "medium"), 50
            )

        return config

    def _determine_initial_mode(self):
        """Determine initial operating mode based on data availability."""
        try:
            # Check how much historical data we have
            end = datetime.now(UTC)
            start = end - timedelta(hours=24)

            power_sensor = self.config.get("power_sensor", "")
            if not power_sensor:
                self.log("No power sensor configured - staying in OBSERVATION mode")
                self.observer.status.mode = SystemMode.OBSERVATION
                return

            # Try to get data from InfluxDB
            df = self.influx.get_entity_data(
                power_sensor.replace("sensor.", ""), start, end, resample="5m"
            )

            sufficient, message = self.analyzer.check_data_sufficiency(df)

            if not sufficient:
                self.log(f"Insufficient data: {message}")
                self.observer.status.mode = SystemMode.OBSERVATION
            else:
                # Check if we have a trained model
                if self.predictor.is_trained:
                    self.log("Model loaded - starting in ACTIVE mode")
                    self.observer.status.mode = SystemMode.ACTIVE
                else:
                    self.log("Data available but no model - starting in LEARNING mode")
                    self.observer.status.mode = SystemMode.LEARNING
                    # Trigger initial training
                    self.run_in(self._train_model, 60)  # Train after 1 minute

        except Exception as e:
            self.log(f"Error determining initial mode: {e}")
            self.observer.status.mode = SystemMode.OBSERVATION

    def _setup_listeners(self):
        """Set up Home Assistant state change listeners."""
        # Listen to power sensor
        power_sensor = self.config.get("power_sensor")
        if power_sensor:
            self.listen_state(self._on_power_change, power_sensor)

        # Listen to each indoor unit
        for unit in self.config.get("indoor_units", []):
            entity_id = unit.get("entity_id")
            if entity_id:
                self.listen_state(self._on_unit_change, entity_id)

            # Also listen to temperature sensor if configured
            temp_sensor = unit.get("temp_sensor")
            if temp_sensor:
                self.listen_state(self._on_temp_change, temp_sensor, unit_name=unit.get("name"))

        # Listen to outdoor temperature
        outdoor_sensor = self.config.get("outdoor_temp_sensor")
        if outdoor_sensor:
            self.listen_state(self._on_outdoor_temp_change, outdoor_sensor)

    def _setup_schedules(self):
        """Set up periodic tasks."""
        # Main control loop - every minute
        self.run_every(self._control_loop, datetime.now() + timedelta(seconds=30), 60)

        # Analysis update - every hour
        self.run_every(self._update_analysis, datetime.now() + timedelta(minutes=5), 3600)

        # Dashboard update - every 30 seconds
        self.run_every(self._update_dashboard, datetime.now() + timedelta(seconds=10), 30)

        # Model retraining - daily
        self.run_daily(self._train_model, datetime.now().replace(hour=3, minute=0))

    def _create_sensors(self):
        """Create Home Assistant sensors for dashboard."""
        # These would be created via MQTT or similar in real implementation
        # For now, we'll use set_state (requires trust)
        pass

    def _on_power_change(self, entity, attribute, old, new, kwargs):
        """Handle power sensor state change."""
        try:
            power = float(new)
            self.observer.update_power(power)
        except (ValueError, TypeError):
            pass

    def _on_unit_change(self, entity, attribute, old, new, kwargs):
        """Handle climate entity state change."""
        try:
            # Get full state
            state = self.get_state(entity, attribute="all")
            attrs = state.get("attributes", {})

            # Find unit name from entity_id
            unit_name = None
            for unit in self.config.get("indoor_units", []):
                if unit.get("entity_id") == entity:
                    unit_name = unit.get("name")
                    break

            if unit_name:
                self.observer.update_unit(
                    unit_name,
                    {
                        "entity_id": entity,
                        "is_on": new not in ("off", "unavailable"),
                        "current_temp": attrs.get("current_temperature"),
                        "target_temp": attrs.get("temperature"),
                        "fan_mode": attrs.get("fan_mode"),
                        "hvac_mode": new,
                    },
                )
        except Exception as e:
            self.log(f"Error handling unit change: {e}")

    def _on_temp_change(self, entity, attribute, old, new, kwargs):
        """Handle temperature sensor change."""
        unit_name = kwargs.get("unit_name")
        if unit_name:
            try:
                self.observer.update_unit(unit_name, {"current_temp": float(new)})
            except (ValueError, TypeError):
                pass

    def _on_outdoor_temp_change(self, entity, attribute, old, new, kwargs):
        """Handle outdoor temperature change."""
        # Store for analysis
        pass

    def _control_loop(self, kwargs):
        """Main control loop - runs every minute."""
        status = self.observer.status

        # Skip if not in active mode
        if status.mode != SystemMode.ACTIVE:
            return

        # Get prediction
        import pandas as pd

        # Build current state dataframe from observer
        current_data = pd.DataFrame(
            {
                "power": [status.power_consumption],
                "outdoor_temp": [10.0],  # TODO: get from sensor
                "active_units": [sum(1 for u in status.units.values() if u.is_on)],
            },
            index=[datetime.now(UTC)],
        )

        prediction = self.predictor.predict(current_data)

        # Get analysis results
        analysis = self.analyzer.get_dashboard_data()

        # Decide action
        if self.controller.should_act(status):
            action = self.controller.decide_action(status, prediction, analysis)

            if action.action_type != ActionType.NO_ACTION:
                result = self.controller.execute_action(action)
                self.log(f"Action: {action.reason} - {'Success' if result.success else 'Failed'}")

    def _execute_ha_action(self, action: ControlAction) -> bool:
        """Execute a control action via Home Assistant services."""
        try:
            if action.action_type == ActionType.ENABLE_UNIT:
                # Find entity_id for unit
                entity_id = self._get_entity_for_unit(action.target_unit)
                if entity_id:
                    self.call_service(
                        "climate/set_temperature",
                        entity_id=entity_id,
                        temperature=action.parameters.get("temperature", 20),
                    )
                    if "fan_mode" in action.parameters:
                        self.call_service(
                            "climate/set_fan_mode",
                            entity_id=entity_id,
                            fan_mode=action.parameters["fan_mode"],
                        )
                    return True

            elif action.action_type == ActionType.ADJUST_TEMP:
                entity_id = self._get_entity_for_unit(action.target_unit)
                if entity_id:
                    self.call_service(
                        "climate/set_temperature",
                        entity_id=entity_id,
                        temperature=action.parameters.get("temperature"),
                    )
                    return True

            elif action.action_type == ActionType.ADJUST_FAN:
                entity_id = self._get_entity_for_unit(action.target_unit)
                if entity_id:
                    self.call_service(
                        "climate/set_fan_mode",
                        entity_id=entity_id,
                        fan_mode=action.parameters.get("fan_mode", "low"),
                    )
                    return True

            return False

        except Exception as e:
            self.log(f"Error executing action: {e}")
            return False

    def _get_entity_for_unit(self, unit_name: str) -> str | None:
        """Get Home Assistant entity_id for a unit name."""
        for unit in self.config.get("indoor_units", []):
            if unit.get("name") == unit_name:
                return unit.get("entity_id")
        return None

    def _update_analysis(self, kwargs):
        """Periodic analysis update."""
        try:
            end = datetime.now(UTC)
            start = end - timedelta(days=7)

            power_sensor = self.config.get("power_sensor", "").replace("sensor.", "")
            df = self.influx.get_entity_data(power_sensor, start, end, resample="1m")

            if not df.empty:
                result = self.analyzer.analyze(df["value"])
                self.log(f"Analysis updated: {result.recommendation}")

                # Update mode if we now have sufficient data
                if result.sufficient_data and self.observer.status.mode == SystemMode.OBSERVATION:
                    self.observer.status.mode = SystemMode.LEARNING
                    self._train_model(None)

        except Exception as e:
            self.log(f"Error updating analysis: {e}")

    def _train_model(self, kwargs):
        """Train or retrain the prediction model."""
        try:
            end = datetime.now(UTC)
            start = end - timedelta(days=14)  # Use 2 weeks of data

            power_sensor = self.config.get("power_sensor", "").replace("sensor.", "")
            df = self.influx.get_entity_data(power_sensor, start, end, resample="1m")

            if df.empty:
                self.log("No data available for training")
                return

            # Add cycling detection
            df.columns = ["power"]
            df["compressor_on"] = df["power"] > self.config.get("cycling", {}).get(
                "power_on_threshold", 300
            )
            df["state_change"] = df["compressor_on"].astype(int).diff().abs().fillna(0)

            result = self.predictor.train(df)

            if result.get("success"):
                self.log(f"Model trained. F1 Score: {result['metrics']['f1_mean']:.3f}")

                # Switch to active mode
                if self.observer.status.mode == SystemMode.LEARNING:
                    self.observer.status.mode = SystemMode.ACTIVE
                    self.log("Switched to ACTIVE mode")
            else:
                self.log(f"Training failed: {result.get('error')}")

        except Exception as e:
            self.log(f"Error training model: {e}")

    def _update_dashboard(self, kwargs):
        """Update dashboard sensors."""
        try:
            # Collect all dashboard data
            data = {
                "observer": self.observer.get_summary(),
                "analyzer": self.analyzer.get_dashboard_data(),
                "predictor": self.predictor.get_dashboard_data(),
                "controller": self.controller.get_dashboard_data(),
            }

            # Set state for main sensor
            self.set_state(
                "sensor.climatiq_status",
                state=self.observer.status.mode.value,
                attributes={
                    "power": data["observer"]["power"],
                    "cycling_risk": data["observer"]["cycling_risk"],
                    "is_cycling": data["observer"]["is_cycling"],
                    "avoided_cycles": data["observer"]["avoided_cycles"],
                    "min_stable_power": data["analyzer"].get("min_stable_power"),
                    "data_quality": data["analyzer"].get("data_quality"),
                    "model_trained": data["predictor"]["is_trained"],
                    "actions_taken": data["controller"]["stats"]["actions_taken"],
                    "cycles_prevented": data["controller"]["stats"]["cycles_prevented"],
                },
            )

        except Exception:
            # Sensor creation might fail without proper setup
            pass
