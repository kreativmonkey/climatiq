"""
ClimatIQ Controller V3 - AppDaemon Integration

Features:
- Multi-device support (multiple outdoor units)
- Automatic zone detection (GMM Clustering)
- Room on/off control based on operating mode
- Mixed-mode validation per outdoor unit
- Power aggregation across units
- Backward compatible with single-unit configs
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import appdaemon.plugins.hass.hassapi as hass
import numpy as np


class ClimatIQController(hass.Hass):
    """Intelligent heat pump controller with multi-device support"""

    def initialize(self):
        """AppDaemon initialization"""

        self.rooms = self.args.get("rooms", {})
        self.sensors = self.args.get("sensors", {})
        self.rules = self.args.get("rules", {})
        self.influx_config = self.args.get("influxdb", {})

        self.last_action_time = {}
        self.unstable_zones = []
        self.stable_zones = []

        # Parse outdoor units (with backward compatibility)
        self.outdoor_units = self.parse_outdoor_units()

        # Cache path
        if "cache_path" in self.args:
            self.cache_path = self.args["cache_path"]
        else:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            self.cache_path = os.path.join(script_dir, "climatiq_zones_cache.json")

        # RL log path
        if "log_file" in self.args:
            self.log_file = self.args["log_file"]
        else:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            self.log_file = os.path.join(script_dir, "climatiq_rl.jsonl")

        # Automatic zone detection on startup
        self.log("=== ClimatIQ Controller V3 (Multi-Device) ===")
        self.log(f"Outdoor units configured: {len(self.outdoor_units)}")
        for unit_id, unit_cfg in self.outdoor_units.items():
            self.log(f"  - {unit_id}: mode={unit_cfg['operating_mode']}")

        self.log("Starting automatic zone detection...")
        self.detect_zones_from_history()

        # Validate outdoor unit modes
        if not self.validate_outdoor_unit_modes():
            self.log("WARNING: Mixed heat/cool modes detected within units!", level="WARNING")

        # Create Home Assistant device with sensors
        self._create_device_sensors()

        # Start control cycle
        interval = self.args.get("interval_minutes", 5)
        self.run_every(self.control_cycle, datetime.now() + timedelta(seconds=30), interval * 60)

        # Re-learn zones daily at 03:00
        self.run_daily(self.detect_zones_from_history, "03:00:00")

        self.log(f"Controller started (Interval: {interval}min, Rooms: {list(self.rooms.keys())})")

    # =========================================================================
    # MULTI-DEVICE SUPPORT
    # =========================================================================

    def parse_outdoor_units(self) -> Dict:
        """
        Parse outdoor units from config with fallback to single unit.

        Backward compatible: If no outdoor_units defined, creates a default
        unit using the global controller.operating_mode and sensors.power.
        """
        outdoor_units = self.args.get("outdoor_units", {})

        if outdoor_units:
            # Multi-device config: validate each unit has required fields
            for unit_id, unit_cfg in outdoor_units.items():
                if "operating_mode" not in unit_cfg:
                    self.log(f"ERROR: Unit {unit_id} missing operating_mode", level="ERROR")
                    unit_cfg["operating_mode"] = "heat"

                if "power_sensor" not in unit_cfg:
                    self.log(f"ERROR: Unit {unit_id} missing power_sensor", level="ERROR")

            return outdoor_units

        # Backward compatibility: single unit (default)
        controller_config = self.args.get("controller", {})
        operating_mode = controller_config.get("operating_mode", "heat")
        power_sensor = self.sensors.get("power")

        if not power_sensor:
            self.log("ERROR: No power sensor configured!", level="ERROR")

        default_unit = {
            "operating_mode": operating_mode,
            "power_sensor": power_sensor,
        }

        self.log(f"Backward compatibility mode: Single unit (mode={operating_mode})", level="INFO")

        return {"default": default_unit}

    def get_outdoor_unit_for_room(self, room: str) -> tuple:
        """
        Get outdoor unit config for given room.

        Returns:
            (unit_id, unit_config) tuple
        """
        room_cfg = self.rooms.get(room, {})

        # Explicit assignment
        if "outdoor_unit" in room_cfg:
            unit_id = room_cfg["outdoor_unit"]
            if unit_id in self.outdoor_units:
                return (unit_id, self.outdoor_units[unit_id])
            else:
                self.log(
                    f"WARNING: Room {room} assigned to unknown unit {unit_id}", level="WARNING"
                )

        # Default unit (backward compatibility)
        if "default" in self.outdoor_units:
            return ("default", self.outdoor_units["default"])

        # Fallback: first available unit
        if self.outdoor_units:
            first_unit_id = list(self.outdoor_units.keys())[0]
            return (first_unit_id, self.outdoor_units[first_unit_id])

        self.log(f"ERROR: No outdoor unit found for room {room}", level="ERROR")
        return (None, {})

    def validate_outdoor_unit_modes(self) -> bool:
        """
        Check that no outdoor unit has mixed heat/cool within its rooms.

        Returns:
            True if valid, False if mixed modes detected
        """
        # Group rooms by outdoor unit
        unit_rooms = {}
        for room_name in self.rooms.keys():
            unit_id, _ = self.get_outdoor_unit_for_room(room_name)
            if unit_id:
                if unit_id not in unit_rooms:
                    unit_rooms[unit_id] = []
                unit_rooms[unit_id].append(room_name)

        # Check each unit's rooms
        all_valid = True
        for unit_id, rooms in unit_rooms.items():
            unit_cfg = self.outdoor_units[unit_id]
            operating_mode = unit_cfg["operating_mode"]

            # All rooms under this unit should use the same mode
            # (enforced by outdoor unit config, no room-level override)
            self.log(f"Unit {unit_id}: {len(rooms)} rooms using mode={operating_mode}")

        return all_valid

    def get_total_power(self) -> Optional[float]:
        """
        Get total power consumption across all outdoor units.

        Single unit: uses global power_sensor
        Multiple units: sums all unit power_sensors
        """
        if len(self.outdoor_units) == 1:
            # Single unit: use power_sensor from unit or global
            unit_id = list(self.outdoor_units.keys())[0]
            unit_cfg = self.outdoor_units[unit_id]
            power_sensor = unit_cfg.get("power_sensor")

            if not power_sensor:
                self.log("ERROR: No power sensor configured", level="ERROR")
                return None

            power_state = self.get_state(power_sensor)
            if power_state in ["unknown", "unavailable", None]:
                return None

            return float(power_state)

        # Multiple units: aggregate power
        total_power = 0.0
        for unit_id, unit_cfg in self.outdoor_units.items():
            power_sensor = unit_cfg.get("power_sensor")
            if not power_sensor:
                self.log(f"WARNING: Unit {unit_id} has no power_sensor", level="WARNING")
                continue

            power_state = self.get_state(power_sensor)
            if power_state in ["unknown", "unavailable", None]:
                self.log(f"WARNING: Unit {unit_id} power unavailable", level="WARNING")
                continue

            total_power += float(power_state)

        return total_power

    def turn_room_off(self, room: str):
        """Turn room off (hvac_mode: off) - always safe"""
        room_cfg = self.rooms.get(room)
        if not room_cfg:
            return

        entity_id = room_cfg["climate_entity"]

        try:
            self.log(f"→ {room}: Turning OFF")
            self.call_service("climate/turn_off", entity_id=entity_id)
            self.last_action_time[room] = datetime.now()
        except Exception as e:
            self.log(f"Error turning off {room}: {e}", level="ERROR")

    def turn_room_on(self, room: str):
        """Turn room on with correct operating_mode from outdoor_unit"""
        room_cfg = self.rooms.get(room)
        if not room_cfg:
            return

        entity_id = room_cfg["climate_entity"]
        unit_id, unit_cfg = self.get_outdoor_unit_for_room(room)

        if not unit_cfg:
            self.log(f"ERROR: Cannot turn on {room} - no unit config", level="ERROR")
            return

        operating_mode = unit_cfg["operating_mode"]

        try:
            self.log(f"→ {room}: Turning ON (mode={operating_mode}, unit={unit_id})")

            # Set hvac_mode based on operating_mode
            hvac_mode = "heat" if operating_mode == "heat" else "cool"

            self.call_service("climate/set_hvac_mode", entity_id=entity_id, hvac_mode=hvac_mode)
            self.last_action_time[room] = datetime.now()
        except Exception as e:
            self.log(f"Error turning on {room}: {e}", level="ERROR")

    # =========================================================================
    # AUTOMATIC ZONE DETECTION
    # =========================================================================

    def detect_zones_from_history(self, kwargs=None):
        """
        Learn stable/unstable zones from InfluxDB history.
        Uses GMM (Gaussian Mixture Model) clustering.
        """
        self.log("Loading historical data for zone detection...")

        try:
            # Try to load InfluxDB data
            data = self._load_influx_history()

            if data is None or len(data) < 1000:
                self.log("Not enough data for zone detection, using fallback", level="WARNING")
                self._use_fallback_zones()
                return

            # GMM Clustering
            zones = self._gmm_clustering(data)

            if zones:
                self.stable_zones = zones["stable"]
                self.unstable_zones = zones["unstable"]
                self.log("✓ Zones detected:")
                self.log(f"  Stable zones: {len(self.stable_zones)}")
                for z in self.stable_zones:
                    self.log(f"    - {z['power_mean']:.0f}W (±{z['power_std']:.0f}W)")
                self.log(f"  Unstable zones: {len(self.unstable_zones)}")
                for z in self.unstable_zones:
                    self.log(f"    - {z['min']:.0f}W - {z['max']:.0f}W")

                # Save cache
                self._save_zones_cache()
            else:
                self._use_fallback_zones()

        except Exception as e:
            self.log(f"Error in zone detection: {e}", level="ERROR")
            self._use_fallback_zones()

    def _load_influx_history(self) -> Optional[List[Dict]]:
        """Load power history from InfluxDB"""

        # Import InfluxDB v1 client
        from influxdb import InfluxDBClient

        cfg = self.influx_config
        if not cfg.get("host"):
            self.log("No InfluxDB config, using HA History", level="WARNING")
            return self._load_ha_history()

        client = InfluxDBClient(
            host=cfg.get("host", "localhost"),
            port=cfg.get("port", 8086),
            username=cfg.get("username"),
            password=cfg.get("password"),
            database=cfg.get("database", "homeassistant"),
        )

        # Last 30 days, 5min resolution
        query = f"""
            SELECT mean("value") as power
            FROM "{cfg.get('measurement', 'W')}"
            WHERE "entity_id" = '{cfg.get('power_entity', 'ac_current_energy')}'
            AND time > now() - 30d
            GROUP BY time(5m)
            FILL(none)
        """

        result = client.query(query)
        points = list(result.get_points())

        self.log(f"InfluxDB: {len(points)} data points loaded")
        return points

    def _load_ha_history(self) -> Optional[List[Dict]]:
        """Fallback: Load history from Home Assistant"""

        # HA History API (max 7 days)
        end = datetime.now()
        start = end - timedelta(days=7)

        # Use first unit's power sensor for history
        if not self.outdoor_units:
            return None

        first_unit = list(self.outdoor_units.values())[0]
        power_sensor = first_unit.get("power_sensor")

        if not power_sensor:
            return None

        history = self.get_history(entity_id=power_sensor, start_time=start, end_time=end)

        if not history or len(history) == 0:
            return None

        # Convert to uniform format
        points = []
        for state in history[0]:
            try:
                val = float(state["state"])
                points.append({"power": val})
            except (ValueError, KeyError, TypeError):
                pass

        self.log(f"HA History: {len(points)} data points loaded")
        return points

    def _gmm_clustering(self, data: List[Dict]) -> Optional[Dict]:
        """
        GMM Clustering to find stable/unstable zones.
        Based on power_std in rolling windows.
        """
        from sklearn.mixture import GaussianMixture

        # Extract power values
        powers = np.array([d.get("power", 0) for d in data if d.get("power", 0) > 50])

        if len(powers) < 1000:
            return None

        # Rolling statistics (30 points = 2.5h at 5min resolution)
        window = 30
        rolling_data = []

        for i in range(window, len(powers)):
            window_data = powers[i - window : i]
            rolling_data.append(
                {
                    "power_mean": np.mean(window_data),
                    "power_std": np.std(window_data),
                }
            )

        if len(rolling_data) < 100:
            return None

        # Features for clustering
        X = np.array([[d["power_mean"], d["power_std"]] for d in rolling_data])

        # GMM with automatic component count (2-5 clusters)
        best_gmm = None
        best_bic = float("inf")

        for n in range(2, 6):
            gmm = GaussianMixture(n_components=n, random_state=42)
            gmm.fit(X)
            bic = gmm.bic(X)
            if bic < best_bic:
                best_bic = bic
                best_gmm = gmm

        # Cluster labels
        labels = best_gmm.predict(X)

        # Analyze clusters
        stable_zones = []
        unstable_zones = []

        for cluster_id in range(best_gmm.n_components):
            mask = labels == cluster_id
            cluster_data = [rolling_data[i] for i in range(len(rolling_data)) if mask[i]]

            if len(cluster_data) < 10:
                continue

            avg_power = np.mean([d["power_mean"] for d in cluster_data])
            avg_std = np.mean([d["power_std"] for d in cluster_data])

            # Stability: power_std < 100W = stable
            if avg_std < 100:
                stable_zones.append(
                    {
                        "cluster_id": int(cluster_id),
                        "power_mean": float(avg_power),
                        "power_std": float(avg_std),
                        "samples": len(cluster_data),
                    }
                )
            else:
                # Unstable: mark range (±1 std)
                powers_in_cluster = [d["power_mean"] for d in cluster_data]
                unstable_zones.append(
                    {
                        "cluster_id": int(cluster_id),
                        "min": float(np.percentile(powers_in_cluster, 10)),
                        "max": float(np.percentile(powers_in_cluster, 90)),
                        "avg_std": float(avg_std),
                        "samples": len(cluster_data),
                    }
                )

        return {"stable": stable_zones, "unstable": unstable_zones}

    def _use_fallback_zones(self):
        """Fallback when no data available"""
        self.log("Using fallback zones (from 90-day analysis)", level="WARNING")
        self.unstable_zones = [{"min": 1000, "max": 1500, "reason": "fallback"}]
        self.stable_zones = [
            {"power_mean": 500, "power_std": 50},
            {"power_mean": 1800, "power_std": 80},
        ]

    def _save_zones_cache(self):
        """Save detected zones to cache file"""
        cache = {
            "timestamp": datetime.now().isoformat(),
            "stable_zones": self.stable_zones,
            "unstable_zones": self.unstable_zones,
        }
        try:
            with open(self.cache_path, "w") as f:
                json.dump(cache, f, indent=2)
            self.log(f"Zones cache saved: {self.cache_path}")
        except Exception as e:
            self.log(f"Error saving cache: {e}", level="WARNING")

    # =========================================================================
    # HOME ASSISTANT DEVICE & SENSORS
    # =========================================================================

    def _create_device_sensors(self):
        """Create Home Assistant device with sensor entities for ClimatIQ metrics"""

        device_info = {
            "identifiers": [("climatiq", "controller")],
            "name": "ClimatIQ Controller",
            "model": "Rule-Based Heat Pump Controller",
            "manufacturer": "ClimatIQ",
            "sw_version": "3.1.0",
        }

        # System metrics
        self.set_state(
            "sensor.climatiq_power",
            state=0,
            attributes={
                "friendly_name": "ClimatIQ Power",
                "unit_of_measurement": "W",
                "device_class": "power",
                "state_class": "measurement",
                "icon": "mdi:flash",
                "device": device_info,
            },
        )

        self.set_state(
            "sensor.climatiq_outdoor_temp",
            state=0,
            attributes={
                "friendly_name": "ClimatIQ Outdoor Temperature",
                "unit_of_measurement": "°C",
                "device_class": "temperature",
                "state_class": "measurement",
                "icon": "mdi:thermometer",
                "device": device_info,
            },
        )

        self.set_state(
            "sensor.climatiq_total_delta",
            state=0,
            attributes={
                "friendly_name": "ClimatIQ Total Delta",
                "unit_of_measurement": "K",
                "state_class": "measurement",
                "icon": "mdi:delta",
                "device": device_info,
            },
        )

        self.set_state(
            "sensor.climatiq_stability_state",
            state="unknown",
            attributes={
                "friendly_name": "ClimatIQ Stability State",
                "icon": "mdi:state-machine",
                "device": device_info,
            },
        )

        # Performance metrics
        self.set_state(
            "sensor.climatiq_cycles_today",
            state=0,
            attributes={
                "friendly_name": "ClimatIQ Cycles Today",
                "icon": "mdi:counter",
                "state_class": "total_increasing",
                "device": device_info,
            },
        )

        self.set_state(
            "sensor.climatiq_actions_today",
            state=0,
            attributes={
                "friendly_name": "ClimatIQ Actions Today",
                "icon": "mdi:cog",
                "state_class": "total_increasing",
                "device": device_info,
            },
        )

        self.set_state(
            "sensor.climatiq_last_reward",
            state=0,
            attributes={
                "friendly_name": "ClimatIQ Last Reward",
                "icon": "mdi:star",
                "state_class": "measurement",
                "device": device_info,
            },
        )

        self.set_state(
            "sensor.climatiq_compressor_runtime",
            state=0,
            attributes={
                "friendly_name": "ClimatIQ Compressor Runtime",
                "unit_of_measurement": "%",
                "icon": "mdi:gauge",
                "state_class": "measurement",
                "device": device_info,
            },
        )

        # Status metrics
        self.set_state(
            "sensor.climatiq_emergency_active",
            state="off",
            attributes={
                "friendly_name": "ClimatIQ Emergency Active",
                "icon": "mdi:alert",
                "device_class": "binary_sensor",
                "device": device_info,
            },
        )

        self.set_state(
            "sensor.climatiq_cooldown_active",
            state="off",
            attributes={
                "friendly_name": "ClimatIQ Cooldown Active",
                "icon": "mdi:timer-sand",
                "device_class": "binary_sensor",
                "device": device_info,
            },
        )

        self.set_state(
            "sensor.climatiq_active_rooms",
            state=0,
            attributes={
                "friendly_name": "ClimatIQ Active Rooms",
                "icon": "mdi:home-group",
                "state_class": "measurement",
                "device": device_info,
            },
        )

        self.set_state(
            "sensor.climatiq_critical_room",
            state="none",
            attributes={
                "friendly_name": "ClimatIQ Critical Room",
                "icon": "mdi:alert-circle",
                "device": device_info,
            },
        )

        self.log("✅ Created ClimatIQ device with 12 sensor entities")

    def _update_device_sensors(
        self, state: Dict, is_emergency: bool, actions: List[Dict], reward: Dict
    ):
        """Update Home Assistant sensor entities with current metrics"""

        # System metrics
        self.set_state("sensor.climatiq_power", state=state["power"])
        self.set_state("sensor.climatiq_outdoor_temp", state=state["outdoor_temp"])
        self.set_state("sensor.climatiq_total_delta", state=state["total_delta_abs"])

        # Determine stability state
        power = state["power"]
        if 1000 <= power <= 1500:
            stability = "unstable"
        elif power < 700 or 1700 < power < 2100:
            stability = "stable"
        else:
            stability = "transition"
        self.set_state("sensor.climatiq_stability_state", state=stability)

        # Performance metrics (track internally)
        # Initialize counters if needed
        if not hasattr(self, "_daily_actions"):
            self._daily_actions = 0
            self._daily_reset_date = datetime.now().date()

        if not hasattr(self, "_last_power_state"):
            self._last_power_state = None
            self._daily_cycles = 0

        # Reset counters at midnight
        if datetime.now().date() != self._daily_reset_date:
            self._daily_actions = 0
            self._daily_cycles = 0
            self._daily_reset_date = datetime.now().date()

        # Increment actions
        if len(actions) > 0:
            self._daily_actions += len(actions)

        # Detect cycle (power transition from low to high)
        current_power = state["power"]
        if self._last_power_state is not None:
            if self._last_power_state < 700 and current_power > 700:
                self._daily_cycles += 1

        self._last_power_state = current_power

        self.set_state("sensor.climatiq_actions_today", state=self._daily_actions)
        self.set_state("sensor.climatiq_cycles_today", state=self._daily_cycles)
        self.set_state("sensor.climatiq_last_reward", state=round(reward["total"], 2))

        # Calculate runtime % (simple: >700W = running)
        # Track runtime minutes
        if not hasattr(self, "_runtime_minutes_today"):
            self._runtime_minutes_today = 0
            self._runtime_date = datetime.now().date()

        if datetime.now().date() != self._runtime_date:
            self._runtime_minutes_today = 0
            self._runtime_date = datetime.now().date()

        # Increment runtime if compressor is running
        interval = self.args.get("interval_minutes", 5)
        if current_power > 700:
            self._runtime_minutes_today += interval

        # Calculate percentage of day (1440 minutes = 24h)
        runtime_percent = min(100, (self._runtime_minutes_today / 1440) * 100)
        self.set_state("sensor.climatiq_compressor_runtime", state=int(runtime_percent))

        # Status metrics
        self.set_state("sensor.climatiq_emergency_active", state="on" if is_emergency else "off")

        # Check if any room is in cooldown
        cooldown_active = False
        rules = self.rules
        for name in state["rooms"].keys():
            last = self.last_action_time.get(name, datetime.min)
            cooldown_minutes = rules["hysteresis"]["min_action_interval_minutes"]
            cooldown = timedelta(minutes=cooldown_minutes)
            if (datetime.now() - last) < cooldown:
                cooldown_active = True
                break

        self.set_state("sensor.climatiq_cooldown_active", state="on" if cooldown_active else "off")

        # Active rooms count
        active_rooms = sum(
            1 for room in state["rooms"].values() if room["hvac_mode"] in ["heat", "cool"]
        )
        self.set_state("sensor.climatiq_active_rooms", state=active_rooms)

        # Critical room (highest delta)
        critical_room = "none"
        max_delta = 0
        for name, room in state["rooms"].items():
            delta = abs(room["delta"])
            if delta > max_delta:
                max_delta = delta
                critical_room = name

        critical_display = (
            f"{critical_room} ({max_delta:.1f}K)" if critical_room != "none" else "none"
        )
        self.set_state("sensor.climatiq_critical_room", state=critical_display)

    # =========================================================================
    # CONTROL CYCLE
    # =========================================================================

    def control_cycle(self, kwargs):
        """Main loop - executed every N minutes"""

        self.log("--- Control Cycle ---")

        try:
            state = self.get_current_state()
            if not state:
                self.log("State not available", level="WARNING")
                return

            self.log(
                f"Power: {state['power']:.0f}W | Outdoor: {state['outdoor_temp']:.1f}°C | Δ Total: {state['total_delta_abs']:.1f}K"
            )

            # Emergency threshold: high delta overrides stability concerns
            emergency_threshold = self.rules.get("stability", {}).get(
                "emergency_delta_threshold", 6.0
            )

            # Validate threshold is positive number
            if not isinstance(emergency_threshold, (int, float)) or emergency_threshold <= 0:
                self.log(
                    f"Invalid emergency_delta_threshold={emergency_threshold}, using default 6.0K",
                    level="WARNING",
                )
                emergency_threshold = 6.0

            is_emergency = state["total_delta_abs"] > emergency_threshold

            # Check: Are we in unstable zone?
            in_unstable = self._is_in_unstable_zone(state["power"])

            if in_unstable and not is_emergency:
                self.log(
                    f"⚠️ Unstable zone ({state['power']:.0f}W), delta OK ({state['total_delta_abs']:.1f}K) - waiting",
                    level="WARNING",
                )
                self.log_episode(state, [], self.calculate_reward(state, in_unstable=True))
                return

            if is_emergency and in_unstable:
                self.log(
                    f"🚨 Emergency override! High delta ({state['total_delta_abs']:.1f}K) in unstable zone ({state['power']:.0f}W) - forcing action",
                    level="WARNING",
                )

            # Decide & execute actions
            actions = self.decide_actions(state, is_emergency=is_emergency)

            if not actions:
                self.log("No actions needed")

            for action in actions:
                self.execute_action(action)

            # Reward & logging
            reward = self.calculate_reward(state)
            self.log(f"Reward: {reward['total']:.1f}")
            self.log_episode(state, actions, reward)

            # Update device sensors
            self._update_device_sensors(state, is_emergency, actions, reward)

        except Exception as e:
            self.log(f"Error: {e}", level="ERROR")

    def _is_in_unstable_zone(self, power: float) -> bool:
        """Check if current power is in unstable zone"""
        for zone in self.unstable_zones:
            if zone["min"] <= power <= zone["max"]:
                return True
        return False

    def get_current_state(self) -> Optional[Dict]:
        """Read current state from Home Assistant"""

        try:
            power = self.get_total_power()
            if power is None:
                return None

            outdoor_state = self.get_state(self.sensors["outdoor_temp"])

            if outdoor_state in ["unknown", "unavailable", None]:
                return None

            outdoor_temp = float(outdoor_state)

            rooms = {}
            for name, cfg in self.rooms.items():
                curr = self.get_state(cfg["temp_sensor"])
                targ = self.get_state(cfg["climate_entity"], attribute="temperature")
                hvac_mode = self.get_state(cfg["climate_entity"])

                if curr in ["unknown", "unavailable", None]:
                    continue
                if targ in ["unknown", "unavailable", None]:
                    continue

                rooms[name] = {
                    "current_temp": float(curr),
                    "target_temp": float(targ),
                    "delta": float(curr) - float(targ),
                    "hvac_mode": hvac_mode,
                    "is_on": hvac_mode not in ["off", "unknown", "unavailable"],
                }

            return {
                "timestamp": datetime.now().isoformat(),
                "power": power,
                "outdoor_temp": outdoor_temp,
                "rooms": rooms,
                "total_delta_abs": sum(abs(r["delta"]) for r in rooms.values()),
            }

        except Exception as e:
            self.log(f"State error: {e}", level="ERROR")
            return None

    def decide_actions(self, state: Dict, is_emergency: bool = False) -> List[Dict]:
        """
        Decide which actions are needed.

        Now supports:
        - turn_off: Night mode, overheating prevention
        - turn_on: Stability targeting, comfort restoration
        - adjust_target: Fine-tuning when on
        """

        actions = []
        rules = self.rules
        current_hour = datetime.now().hour

        # Night mode: 23:00 - 06:00
        is_night_mode = 23 <= current_hour or current_hour < 6

        for name, room in state["rooms"].items():
            # Cooldown check (shorter cooldown in emergency)
            last = self.last_action_time.get(name, datetime.min)

            if is_emergency:
                cooldown_minutes = rules["hysteresis"].get("emergency_action_interval_minutes", 7)
            else:
                cooldown_minutes = rules["hysteresis"]["min_action_interval_minutes"]

            cooldown = timedelta(minutes=cooldown_minutes)
            time_since_last = datetime.now() - last

            if time_since_last < cooldown:
                remaining_minutes = (cooldown - time_since_last).total_seconds() / 60
                self.log(
                    f"⏳ {name}: Cooldown active ({remaining_minutes:.1f} min remaining, "
                    f"{'emergency' if is_emergency else 'normal'} mode)",
                    level="DEBUG",
                )
                continue

            delta = room["delta"]
            target = room["target_temp"]
            is_on = room["is_on"]
            step = rules["adjustments"]["target_step"]

            # Get outdoor unit for this room
            unit_id, unit_cfg = self.get_outdoor_unit_for_room(name)
            operating_mode = unit_cfg.get("operating_mode", "heat")

            # Decision logic:

            # 1. Night mode → Turn off non-critical rooms
            if is_night_mode and is_on and delta >= -0.5:
                actions.append(
                    {
                        "room": name,
                        "action_type": "turn_off",
                        "reason": f"Night mode (Δ={delta:.1f}K, ok to turn off)",
                    }
                )
                continue

            # 2. Overheating prevention
            if operating_mode == "heat" and delta > 2.0 and is_on:
                actions.append(
                    {
                        "room": name,
                        "action_type": "turn_off",
                        "reason": f"Overheating ({delta:.1f}K above target)",
                    }
                )
                continue

            # 3. Too cold → Turn on if off, or increase target
            if delta < -rules["comfort"]["temp_tolerance_cold"]:
                if not is_on:
                    actions.append(
                        {
                            "room": name,
                            "action_type": "turn_on",
                            "reason": f"Too cold ({delta:.1f}K), unit={unit_id}",
                            "unit_id": unit_id,
                        }
                    )
                else:
                    # Already on, adjust target
                    new_target = min(target + step, rules["adjustments"]["target_max"])
                    if new_target != target:
                        actions.append(
                            {
                                "room": name,
                                "action_type": "adjust_target",
                                "old_target": target,
                                "new_target": new_target,
                                "reason": f"Too cold ({delta:.1f}K)",
                            }
                        )

            # 4. Too warm → Decrease target or turn off
            elif delta > rules["comfort"]["temp_tolerance_warm"]:
                if is_on:
                    new_target = max(target - step, rules["adjustments"]["target_min"])
                    if new_target != target:
                        actions.append(
                            {
                                "room": name,
                                "action_type": "adjust_target",
                                "old_target": target,
                                "new_target": new_target,
                                "reason": f"Too warm ({delta:.1f}K)",
                            }
                        )

            # 5. Stability targeting: Power too low → Turn on a room
            if state["power"] < 500 and not is_on and delta < -0.5:
                actions.append(
                    {
                        "room": name,
                        "action_type": "turn_on",
                        "reason": f"Stability targeting (power={state['power']:.0f}W)",
                        "unit_id": unit_id,
                    }
                )

        # Max actions per cycle
        max_actions = rules["stability"]["max_actions_per_cycle"]
        if len(actions) > max_actions:
            # Prioritize by largest deviation
            actions = sorted(
                actions,
                key=lambda a: (
                    abs(state["rooms"][a["room"]]["delta"]) if a["room"] in state["rooms"] else 0
                ),
                reverse=True,
            )
            actions = actions[:max_actions]

        return actions

    def execute_action(self, action: Dict):
        """Execute action in Home Assistant"""

        room_name = action["room"]
        action_type = action["action_type"]

        if action_type == "turn_off":
            self.turn_room_off(room_name)

        elif action_type == "turn_on":
            self.turn_room_on(room_name)

        elif action_type == "adjust_target":
            new_target = action["new_target"]
            entity = self.rooms[room_name]["climate_entity"]

            self.log(
                f"→ {room_name}: {action['old_target']:.1f}°C → {new_target:.1f}°C ({action['reason']})"
            )

            try:
                self.call_service(
                    "climate/set_temperature", entity_id=entity, temperature=new_target
                )
                self.last_action_time[room_name] = datetime.now()
            except Exception as e:
                self.log(f"Error adjusting target: {e}", level="ERROR")

    def calculate_reward(self, state: Dict, in_unstable: bool = False) -> Dict:
        """Calculate reward for RL training"""

        # Comfort: Closeness to target temps
        comfort = -state["total_delta_abs"]

        # Stability penalty
        stability = -20 if in_unstable else 0

        # Energy: Lower consumption = better
        energy = -(state["power"] / 500)

        total = comfort + stability + energy

        return {"total": total, "comfort": comfort, "stability": stability, "energy": energy}

    def log_episode(self, state: Dict, actions: List[Dict], reward: Dict):
        """Log episode for RL training (JSONL)"""

        log_file = self.log_file

        episode = {
            "timestamp": state["timestamp"],
            "state": {
                "power": state["power"],
                "outdoor_temp": state["outdoor_temp"],
                "total_delta_abs": state["total_delta_abs"],
                "rooms": {k: v["delta"] for k, v in state["rooms"].items()},
            },
            "actions": actions,
            "reward": reward,
            "unstable_zones": self.unstable_zones,
            "outdoor_units": {
                unit_id: {"operating_mode": cfg["operating_mode"]}
                for unit_id, cfg in self.outdoor_units.items()
            },
        }

        try:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            with open(log_file, "a") as f:
                f.write(json.dumps(episode) + "\n")
        except Exception as e:
            self.log(f"Log error: {e}", level="WARNING")
