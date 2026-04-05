"""
ClimatIQ Controller V3.2 - AppDaemon Integration

Features:
- Automatic zone detection at startup (GMM Clustering)
- Target temperature adjustment as primary strategy
- RL Logging (State-Action-Reward)
- Temperature Hysteresis: Prevents oscillation in comfort holding
- Power Zone Hysteresis: Prevents rapid zone transitions
- Heat Demand Inference: Knows the difference between idle and not-enough-heat
- Auto turn on/off rooms based on configuration
- True Oscillation Detection: Tracks power variance over time
- Stabilization for Neutral Rooms: Adjusts target even when all rooms are comfortable
"""

import appdaemon.plugins.hass.hassapi as hass
import json
import os
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum


class ActionDirection(str, Enum):
    """Direction of last action for hysteresis tracking."""

    HEATING = "heating"
    COOLING = "cooling"
    NONE = "none"


class ClimatIQController(hass.Hass):
    """Heat pump controller with automatic zone detection."""

    def initialize(self):
        """Initialize the controller and start control cycle."""

        self.rooms = self.args.get("rooms", {})
        self.sensors = self.args.get("sensors", {})
        self.rules = self.args.get("rules", {})
        self.influx_config = self.args.get("influxdb", {})
        self.default_target_temp = self.args.get("default_target_temp", 20.0)

        self.last_action_time = {}
        self.unstable_zones = []
        self.stable_zones = []

        self.room_action_direction: Dict[str, ActionDirection] = {}
        self.power_hysteresis_state: Optional[str] = None
        self.last_stabilization_room: Optional[str] = None
        self.last_stabilization_direction: Optional[str] = None
        self._power_readings: List[float] = []
        self._max_power_history = 20

        self.log("=== ClimatIQ Controller V3.2 ===")
        self.log("Starte automatische Zonen-Erkennung...")
        self.detect_zones_from_history()

        interval = self.args.get("interval_minutes", 5)
        self.run_every(self.control_cycle, datetime.now() + timedelta(seconds=30), interval * 60)

        self.run_daily(self.detect_zones_from_history, "03:00:00")

        self.log(
            f"Controller gestartet (Interval: {interval}min, Räume: {list(self.rooms.keys())})"
        )

    # =========================================================================
    # AUTOMATIC ZONE DETECTION
    # =========================================================================

    def detect_zones_from_history(self, kwargs=None):
        """Learn stable/unstable zones from InfluxDB history using GMM clustering."""
        self.log("Lade historische Daten für Zonen-Erkennung...")

        try:
            # Try to load InfluxDB data
            data = self._load_influx_history()

            if data is None or len(data) < 1000:
                self.log("Nicht genug Daten für Zonen-Erkennung, nutze Fallback", level="WARNING")
                self._use_fallback_zones()
                return

            # GMM Clustering
            zones = self._gmm_clustering(data)

            if zones:
                self.stable_zones = zones["stable"]
                self.unstable_zones = zones["unstable"]
                self.log(f"✓ Zonen erkannt:")
                self.log(f"  Stabile Zonen: {len(self.stable_zones)}")
                for z in self.stable_zones:
                    self.log(f"    - {z['power_mean']:.0f}W (±{z['power_std']:.0f}W)")
                self.log(f"  Instabile Zonen: {len(self.unstable_zones)}")
                for z in self.unstable_zones:
                    self.log(f"    - {z['min']:.0f}W - {z['max']:.0f}W")

                # Cache speichern
                self._save_zones_cache()
            else:
                self._use_fallback_zones()

        except Exception as e:
            self.log(f"Fehler bei Zonen-Erkennung: {e}", level="ERROR")
            self._use_fallback_zones()

    def _load_influx_history(self) -> Optional[List[Dict]]:
        """Load power history from InfluxDB."""

        # InfluxDB v1 Query
        from influxdb import InfluxDBClient

        cfg = self.influx_config
        if not cfg.get("host"):
            self.log("Keine InfluxDB Config, nutze HA History", level="WARNING")
            return self._load_ha_history()

        try:
            client = InfluxDBClient(
                host=cfg.get("host", "localhost"),
                port=cfg.get("port", 8086),
                username=cfg.get("username"),
                password=cfg.get("password"),
                database=cfg.get("database", "homeassistant"),
            )

            # Letzte 30 Tage, 5min Auflösung
            query = f"""
                SELECT mean("value") as power
                FROM "{cfg.get("measurement", "W")}"
                WHERE "entity_id" = '{cfg.get("power_entity", "ac_current_energy")}'
                AND time > now() - 30d
                GROUP BY time(5m)
                FILL(none)
            """

            result = client.query(query)
            points = list(result.get_points())

            self.log(f"InfluxDB: {len(points)} Datenpunkte geladen")
            return points
        except Exception as e:
            self.log(f"InfluxDB Fehler: {e} - nutze HA History", level="WARNING")
            return self._load_ha_history()

    def _load_ha_history(self) -> Optional[List[Dict]]:
        """Fallback: Load history from Home Assistant."""

        # HA History API (letzte 7 Tage max)
        end = datetime.now()
        start = end - timedelta(days=7)

        entity = self.sensors.get("power")
        if not entity:
            return None

        history = self.get_history(entity_id=entity, start_time=start, end_time=end)

        if not history or len(history) == 0:
            return None

        # Konvertiere zu einheitlichem Format
        points = []
        for state in history[0]:
            try:
                val = float(state["state"])
                points.append({"power": val})
            except:
                pass

        self.log(f"HA History: {len(points)} Datenpunkte geladen")
        return points

    def _gmm_clustering(self, data: List[Dict]) -> Optional[Dict]:
        """
        GMM Clustering um stabile/instabile Zonen zu finden.
        Basiert auf power_std in rollierenden Fenstern.
        """
        from sklearn.mixture import GaussianMixture

        # Power-Werte extrahieren
        powers = np.array([d.get("power", 0) for d in data if d.get("power", 0) > 50])

        if len(powers) < 1000:
            return None

        # Rollierende Statistiken (30 Punkte = 2.5h bei 5min Auflösung)
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

        # Features für Clustering
        X = np.array([[d["power_mean"], d["power_std"]] for d in rolling_data])

        # GMM mit automatischer Komponentenanzahl (2-5 Cluster)
        best_gmm = None
        best_bic = float("inf")

        for n in range(2, 6):
            gmm = GaussianMixture(n_components=n, random_state=42)
            gmm.fit(X)
            bic = gmm.bic(X)
            if bic < best_bic:
                best_bic = bic
                best_gmm = gmm

        # Cluster Labels
        labels = best_gmm.predict(X)

        # Analysiere Cluster
        stable_zones = []
        unstable_zones = []

        for cluster_id in range(best_gmm.n_components):
            mask = labels == cluster_id
            cluster_data = [rolling_data[i] for i in range(len(rolling_data)) if mask[i]]

            if len(cluster_data) < 10:
                continue

            avg_power = np.mean([d["power_mean"] for d in cluster_data])
            avg_std = np.mean([d["power_std"] for d in cluster_data])

            # Stabilität: power_std < 100W = stabil
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
                # Instabil: Bereich markieren (±1 Std)
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
        """Fallback when no data is available."""
        self.log("Nutze Fallback-Zonen (aus 90-Tage Analyse)", level="WARNING")
        self.unstable_zones = [{"min": 1000, "max": 1500, "reason": "fallback"}]
        self.stable_zones = [
            {"power_mean": 500, "power_std": 50},
            {"power_mean": 1800, "power_std": 80},
        ]

    def _save_zones_cache(self):
        cache_path = os.path.join(self.config_dir, "climatiq_zones_cache.json")
        cache = {
            "timestamp": datetime.now().isoformat(),
            "stable_zones": self.stable_zones,
            "unstable_zones": self.unstable_zones,
        }
        try:
            with open(cache_path, "w") as f:
                json.dump(cache, f, indent=2)
            self.log(f"Zonen-Cache gespeichert: {cache_path}")
        except Exception as e:
            self.log(f"Fehler beim Speichern des Cache: {e}", level="WARNING")

    # =========================================================================
    # CONTROL CYCLE
    # =========================================================================

    def control_cycle(self, kwargs):
        """Main control loop - runs every N minutes."""

        self.log("--- Control Cycle ---")

        try:
            state = self.get_current_state()
            if not state:
                self.log("State nicht verfügbar", level="WARNING")
                return

            self.log(
                f"Power: {state['power']:.0f}W | Outdoor: {state['outdoor_temp']:.1f}°C | Δ Total: {state['total_delta_abs']:.1f}K"
            )

            self._update_power_readings(state["power"])

            is_oscillating, osc_reason = self._detect_real_oscillation()

            if is_oscillating:
                self.log(
                    f"⚠️ Power OSZILLIEREND ({state['power']:.0f}W)! Starte Stabilisierung... ({osc_reason})",
                    level="WARNING",
                )
                actions = self._decide_stabilization_actions(state, True)
            else:
                actions = self.decide_actions(state)

            if not actions:
                self.log("Keine Actions nötig")

            for action in actions:
                self.execute_action(action)

            # Reward & Logging
            reward = self.calculate_reward(state)
            self.log(f"Reward: {reward['total']:.1f}")
            self.log_episode(state, actions, reward)

        except Exception as e:
            self.log(f"Fehler: {e}", level="ERROR")

    def _update_power_readings(self, power: float):
        self._power_readings.append(power)
        if len(self._power_readings) > self._max_power_history:
            self._power_readings.pop(0)

    def _detect_real_oscillation(self) -> tuple[bool, str]:
        if len(self._power_readings) < 10:
            return False, ""
        recent = self._power_readings[-10:]
        std = np.std(recent)
        spread = max(recent) - min(recent)
        osc_threshold_std = self.rules.get("stability", {}).get("oscillation_std_threshold", 100)
        osc_threshold_spread = self.rules.get("stability", {}).get(
            "oscillation_spread_threshold", 200
        )
        if std > osc_threshold_std or spread > osc_threshold_spread:
            return True, f"σ={std:.0f}W, spread={spread:.0f}W"
        return False, ""

    def _is_in_unstable_zone(self, power: float) -> bool:
        """Check if current power is in an unstable zone."""
        in_unstable, _ = self._check_unstable_zone_hysteresis(power)
        return in_unstable

    def _load_policy_table(self) -> dict:
        import yaml

        default_policy = os.path.join(self.config_dir, "climatiq_policy.yaml")
        policy_file = self.args.get("policy_file", default_policy)

        if not os.path.exists(policy_file):
            self.log(f"Policy file not found: {policy_file}", level="DEBUG")
            return {}

        try:
            with open(policy_file, "r") as f:
                policy = yaml.safe_load(f)
            self.log(f"Loaded policy table from {policy_file}")
            return policy
        except Exception as e:
            self.log(f"Error loading policy: {e}", level="WARNING")
            return {}

    def _get_policy_recommendation(self, state: Dict, policy: dict) -> Optional[dict]:
        """Get policy recommendation for current conditions."""
        if not policy:
            return None

        outdoor_temp = state.get("outdoor_temp", 15)
        hour = datetime.now().hour

        # Determine period
        if 23 <= hour or hour < 6:
            period = "night"
        elif 6 <= hour < 10:
            period = "morning"
        elif 17 <= hour < 22:
            period = "evening"
        else:
            period = "day"

        # Determine mode (heating vs cooling)
        mode = "heating" if outdoor_temp < 15 else "cooling"

        # Find bucket
        temp_bucket = round(outdoor_temp / 5) * 5
        key = f"{temp_bucket}C_{period}"

        policies = policy.get("policies", {}).get(mode, {})
        recommendation = policies.get(key)

        if recommendation:
            self.log(
                f"Policy match: {mode}/{key} → recommend {recommendation.get('best_rooms', '?')} rooms, "
                f"expect {recommendation.get('expect_power', '?')}W"
            )

        return recommendation

    def _decide_stabilization_actions(
        self, state: Dict, is_oscillating: bool = False
    ) -> List[Dict]:
        actions = []
        rules = self.rules
        rooms = state["rooms"]

        warm_threshold = rules["comfort"]["temp_tolerance_warm"]
        target_min = rules["adjustments"]["target_min"]
        target_max = rules["adjustments"]["target_max"]

        warm_rooms = [
            (name, room)
            for name, room in rooms.items()
            if room["delta"] > warm_threshold and room["target_temp"] > target_min
        ]
        warm_rooms.sort(key=lambda x: x[1]["delta"], reverse=True)

        if self.last_stabilization_room and len(warm_rooms) > 1:
            warm_rooms = [(n, r) for n, r in warm_rooms if n != self.last_stabilization_room]

        for name, room in warm_rooms[:1]:
            target = room["target_temp"]
            step = rules["adjustments"]["target_step"]
            new_target = max(target - step, target_min)
            if new_target != target:
                self.last_stabilization_room = name
                self.last_stabilization_direction = "cooling"
                actions.append(
                    {
                        "room": name,
                        "old_target": target,
                        "new_target": new_target,
                        "reason": f"Stabilisierung: Reduziere {room['delta']:.1f}K (warm)",
                        "action_direction": ActionDirection.COOLING,
                    }
                )
                self.log(
                    f"  → Strategie 1: Reduziere {name} Target {target}→{new_target}°C (war {room['delta']:.1f}K warm)"
                )
                return actions

        cold_threshold = rules["comfort"]["temp_tolerance_cold"]

        cold_rooms = [
            (name, room) for name, room in rooms.items() if room["delta"] < -cold_threshold
        ]
        cold_rooms.sort(key=lambda x: x[1]["delta"])

        if self.last_stabilization_room and len(cold_rooms) > 1:
            cold_rooms = [(n, r) for n, r in cold_rooms if n != self.last_stabilization_room]

        for name, room in cold_rooms[:1]:
            target = room["target_temp"]
            step = rules["adjustments"]["target_step"]
            new_target = min(target + step, target_max)
            if new_target != target:
                self.last_stabilization_room = name
                self.last_stabilization_direction = "heating"
                actions.append(
                    {
                        "room": name,
                        "old_target": target,
                        "new_target": new_target,
                        "reason": f"Stabilisierung: Erhöhe {name} für Idle",
                        "action_direction": ActionDirection.HEATING,
                    }
                )
                self.log(f"  → Strategie 2: Erhöhe {name} Target {target}→{new_target}°C")
                return actions

        off_candidates = [
            (name, room)
            for name, room in rooms.items()
            if room.get("is_on", False) and room["delta"] > 0.3 and room["target_temp"] > target_min
        ]

        auto_turn_off = rules.get("stability", {}).get("auto_turn_off", False)
        if auto_turn_off:
            off_candidates.sort(key=lambda x: x[1]["delta"], reverse=True)

            if self.last_stabilization_room and len(off_candidates) > 1:
                off_candidates = [
                    (n, r) for n, r in off_candidates if n != self.last_stabilization_room
                ]

            if off_candidates:
                name, room = off_candidates[0]
                target = room["target_temp"]
                new_target = target_min
                self.last_stabilization_room = name
                self.last_stabilization_direction = "cooling"
                actions.append(
                    {
                        "room": name,
                        "old_target": target,
                        "new_target": new_target,
                        "hvac_mode": "off",
                        "reason": f"Stabilisierung: Deaktiviere {name} (zu warm)",
                        "action_direction": ActionDirection.COOLING,
                    }
                )
                self.log(f"  → Strategie 3: Deaktiviere {name} (hvac_mode=off)")
                return actions

        if is_oscillating:
            neutral_rooms = [
                (name, room) for name, room in rooms.items() if room.get("is_on", False)
            ]
            if not neutral_rooms:
                neutral_rooms = [
                    (name, room)
                    for name, room in rooms.items()
                    if room.get("is_on", False) is False
                ]
            neutral_rooms.sort(
                key=lambda x: rules.get("unit_priorities", {}).get(x[0], 50), reverse=True
            )
            if neutral_rooms:
                name, room = neutral_rooms[0]
                target = room["target_temp"]
                step = rules["adjustments"]["target_step"]
                current_dir = self.last_stabilization_direction
                if current_dir == "cooling":
                    new_target = min(target + step, target_max)
                    direction = ActionDirection.HEATING
                elif current_dir == "heating":
                    new_target = max(target - step, target_min)
                    direction = ActionDirection.COOLING
                else:
                    if state["power"] < 400:
                        new_target = min(target + step, target_max)
                        direction = ActionDirection.HEATING
                    else:
                        new_target = max(target - step, target_min)
                        direction = ActionDirection.COOLING
                if new_target != target:
                    self.last_stabilization_room = name
                    self.last_stabilization_direction = (
                        "cooling" if direction == ActionDirection.COOLING else "heating"
                    )
                    actions.append(
                        {
                            "room": name,
                            "old_target": target,
                            "new_target": new_target,
                            "reason": f"Stabilisierung: {name} trotz neutral (Power oszilliert)",
                            "action_direction": direction,
                        }
                    )
                    self.log(
                        f"  → Strategie 4: {name} Target {target}→{new_target}°C (neutral rooms)"
                    )
                    return actions

        self.log(
            f"  → Keine Stabilisierung möglich (warm: {len(warm_rooms)}, cold: {len(cold_rooms)})"
        )
        return []

    def _check_unstable_zone_hysteresis(self, power: float) -> tuple[bool, str]:
        """Check unstable zone with hysteresis - prevents rapid zone transitions"""
        rules = self.rules
        hyst_buffer = rules.get("hysteresis", {}).get("power_hysteresis_watts", 100)

        # If we were already avoiding, check if we're far enough out
        if self.power_hysteresis_state == "avoiding_low":
            for zone in self.unstable_zones:
                zone_min = zone.get("min", 0)
                if power > zone_min + hyst_buffer:
                    self.power_hysteresis_state = None
                    return False, ""
            return True, "Hysterese: vorher low-avoid"

        if self.power_hysteresis_state == "avoiding_high":
            for zone in self.unstable_zones:
                zone_max = zone.get("max", float("inf"))
                if power < zone_max - hyst_buffer:
                    self.power_hysteresis_state = None
                    return False, ""
            return True, "Hysterese: vorher high-avoid"

        # Normal check: are we in an unstable zone?
        for zone in self.unstable_zones:
            zone_min = zone.get("min", 0)
            zone_max = zone.get("max", float("inf"))

            # Near boundary (in buffer zone)
            if zone_min - hyst_buffer <= power <= zone_min + hyst_buffer:
                self.power_hysteresis_state = "avoiding_low"
                return True, f"Nahe unterer Grenze ({zone_min}W), Hysterese aktiv"

            if zone_max - hyst_buffer <= power <= zone_max + hyst_buffer:
                self.power_hysteresis_state = "avoiding_high"
                return True, f"Nahe oberer Grenze ({zone_max}W), Hysterese aktiv"

            # Actually in zone
            if zone_min <= power <= zone_max:
                return True, f"In Zone ({zone_min}-{zone_max}W)"

        return False, ""

    def _calculate_min_stable_power(self, state: Dict) -> float:
        """Calculate minimum stable power based on ACTUAL heat demand.

        CRITICAL INSIGHT:
        - 3 units can be "ON" but power only 60W = ALL units are IDLE
        - We must INFER heat demand from temperature dynamics
        - delta >= -0.5°C: unit is IDLE (room satisfied)
        - delta < -0.5°C: unit is calling for heat
        """
        rooms_calling_for_heat = 0

        for name, room in state["rooms"].items():
            if not room.get("is_on", False):
                continue

            delta = room.get("delta", 0)
            # If room is close to or above target, it's not calling for heat
            if delta >= -0.5:
                pass
            else:
                rooms_calling_for_heat += 1

        # If NO units are calling for heat, power should be MINIMUM (just standby)
        if rooms_calling_for_heat == 0:
            return 100.0  # Very low threshold

        # Each unit calling for heat adds minimum load
        min_per_active_unit = 250

        return min_per_active_unit * rooms_calling_for_heat

    def _is_power_too_low_for_heat_demand(self, state: Dict) -> bool:
        """Check if power is abnormally low given the heat demand.

        Returns True ONLY if:
        - Power is below minimum AND
        - At least one unit SHOULD be calling for heat (but power is too low)

        Returns False (OK) if:
        - All rooms are satisfied (no heat needed, low power is normal)
        """
        current_power = state["power"]
        min_stable = self._calculate_min_stable_power(state)

        # Count how many rooms actually need heat
        rooms_needing_heat = sum(
            1 for r in state["rooms"].values() if r.get("is_on", False) and r.get("delta", 0) < -0.5
        )

        if rooms_needing_heat == 0:
            self.log(f"✓ Power {current_power:.0f}W OK: No rooms need heat (idle)")
            return False

        if current_power < min_stable:
            self.log(
                f"⚠️ Power TOO LOW: {current_power:.0f}W < {min_stable:.0f}W "
                f"({rooms_needing_heat} rooms need heat)"
            )
            return True

        self.log(f"✓ Power OK: {current_power:.0f}W >= {min_stable:.0f}W")
        return False

    def get_current_state(self) -> Optional[Dict]:
        """Get current state from Home Assistant."""

        try:
            power_state = self.get_state(self.sensors["power"])
            outdoor_state = self.get_state(self.sensors["outdoor_temp"])

            if power_state in ["unknown", "unavailable", None]:
                return None
            if outdoor_state in ["unknown", "unavailable", None]:
                return None

            power = float(power_state)
            outdoor_temp = float(outdoor_state)

            rooms = {}
            for name, cfg in self.rooms.items():
                curr = self.get_state(cfg["temp_sensor"])
                target_cfg = cfg.get("target_temp", self.default_target_temp)
                hvac_mode = self.get_state(cfg["climate_entity"])

                if curr in ["unknown", "unavailable", None]:
                    continue

                if isinstance(target_cfg, str):
                    targ = self.get_state(target_cfg)
                    if targ in ["unknown", "unavailable", None]:
                        targ = self.default_target_temp
                    else:
                        targ = float(targ)
                else:
                    targ = float(target_cfg)

                rooms[name] = {
                    "current_temp": float(curr),
                    "target_temp": targ,
                    "delta": float(curr) - targ,
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
            self.log(f"State-Fehler: {e}", level="ERROR")
            return None

    def decide_actions(self, state: Dict) -> List[Dict]:
        """Decide which target temperature adjustments are needed."""

        actions = []
        rules = self.rules
        auto_turn_on = rules.get("stability", {}).get("auto_turn_on", False)
        cold_threshold = rules["comfort"]["temp_tolerance_cold"]

        for name, room in state["rooms"].items():
            last = self.last_action_time.get(name, datetime.min)
            cooldown = timedelta(minutes=rules["hysteresis"]["min_action_interval_minutes"])
            if (datetime.now() - last) < cooldown:
                continue

            delta = room["delta"]
            target = room["target_temp"]
            step = rules["adjustments"]["target_step"]
            is_on = room.get("is_on", False)

            if not is_on:
                if auto_turn_on and delta < -cold_threshold:
                    self.log(f"⚡ {name}: OFF but zu kalt ({delta:.1f}K) - schalte ein")
                    actions.append(
                        {
                            "room": name,
                            "old_target": target,
                            "new_target": target,
                            "hvac_mode": "heat",
                            "reason": f"Zu kalt ({delta:.1f}K), schalte ein",
                            "action_direction": ActionDirection.HEATING,
                        }
                    )
                continue

            # Temperature hysteresis check - prevents oscillation
            hyst_reverse = rules.get("hysteresis", {}).get("temp_hysteresis_reverse", 0.5)
            current_dir = self.room_action_direction.get(name, ActionDirection.NONE)

            if current_dir == ActionDirection.HEATING:
                # After heating, room must be warmer than target + hysteresis BEFORE cooling
                # This means delta must be > +hyst_reverse (room is above target + hysteresis)
                if delta > hyst_reverse:
                    self.room_action_direction[name] = ActionDirection.NONE
                else:
                    # BLOCK opposite-direction action - room not warm enough yet
                    self.log(
                        f"⏳ {name}: Hysteresis active (heating, warte bis delta > +{hyst_reverse}K)",
                        level="DEBUG",
                    )
                    continue  # Skip creating cooling action

            elif current_dir == ActionDirection.COOLING:
                # After cooling, room must be cooler than target - hysteresis BEFORE heating
                # This means delta must be < -hyst_reverse (room is below target - hysteresis)
                if delta < -hyst_reverse:
                    self.room_action_direction[name] = ActionDirection.NONE
                else:
                    # BLOCK opposite-direction action - room not cool enough yet
                    self.log(
                        f"⏳ {name}: Hysteresis active (cooling, warte bis delta < -{hyst_reverse}K)",
                        level="DEBUG",
                    )
                    continue  # Skip creating heating action

            # Zu kalt → Target erhöhen
            if delta < -rules["comfort"]["temp_tolerance_cold"]:
                new_target = min(target + step, rules["adjustments"]["target_max"])
                if new_target != target:
                    actions.append(
                        {
                            "room": name,
                            "old_target": target,
                            "new_target": new_target,
                            "reason": f"Zu kalt ({delta:.1f}K)",
                            "action_direction": ActionDirection.HEATING,
                        }
                    )

            # Zu warm → Target senken
            elif delta > rules["comfort"]["temp_tolerance_warm"]:
                new_target = max(target - step, rules["adjustments"]["target_min"])
                if new_target != target:
                    actions.append(
                        {
                            "room": name,
                            "old_target": target,
                            "new_target": new_target,
                            "reason": f"Zu warm ({delta:.1f}K)",
                            "action_direction": ActionDirection.COOLING,
                        }
                    )

        # Max Actions pro Cycle
        max_actions = rules["stability"]["max_actions_per_cycle"]
        if len(actions) > max_actions:
            # Priorisiere nach größter Abweichung
            actions = sorted(
                actions, key=lambda a: abs(state["rooms"][a["room"]]["delta"]), reverse=True
            )
            actions = actions[:max_actions]

        return actions

    def execute_action(self, action: Dict):
        """Execute target temperature adjustment in Home Assistant."""

        room_name = action["room"]
        new_target = action["new_target"]
        old_target = action["old_target"]
        entity = self.rooms[room_name]["climate_entity"]
        action_direction = action.get("action_direction")
        hvac_mode = action.get("hvac_mode")

        if hvac_mode == "off":
            self.log(f"→ {room_name}: {old_target:.1f}°C → OFF")

        self.log(f"→ {room_name}: {old_target:.1f}°C → {new_target:.1f}°C ({action['reason']})")

        try:
            if hvac_mode == "off":
                self.call_service("climate/set_hvac_mode", entity_id=entity, hvac_mode="off")
            elif hvac_mode in ["heat", "cool"]:
                self.call_service("climate/set_hvac_mode", entity_id=entity, hvac_mode=hvac_mode)
            else:
                current_state = self.get_current_state()
                if current_state is None:
                    current_state = {"rooms": {}}
                current_room = current_state["rooms"].get(room_name, {})
                if current_room.get("hvac_mode") in ["off", "unknown", "unavailable", None]:
                    common_mode = self._get_common_hvac_mode()
                    if common_mode and common_mode != "off":
                        self.log(f"  → Sync HVAC mode to {common_mode} (other devices)")
                        self.call_service(
                            "climate/set_hvac_mode", entity_id=entity, hvac_mode=common_mode
                        )

            self.call_service("climate/set_temperature", entity_id=entity, temperature=new_target)
            self.last_action_time[room_name] = datetime.now()

            if action_direction:
                self.room_action_direction[room_name] = action_direction

        except Exception as e:
            self.log(f"Fehler bei Action: {e}", level="ERROR")

    def _get_common_hvac_mode(self) -> Optional[str]:
        current_state = self.get_current_state()
        if current_state is None:
            return None
        rooms = current_state.get("rooms", {})
        modes = []
        for name, room in rooms.items():
            mode = room.get("hvac_mode")
            if mode and mode not in ["off", "unknown", "unavailable", None]:
                modes.append(mode)
        if not modes:
            return None
        return modes[0]

    def calculate_reward(self, state: Dict, in_unstable: bool = False) -> Dict:
        """Calculate reward for RL training / policy learning.

        Goal: Find optimal settings for each condition:
        - outdoor_temp + time → best settings → minimum power while stable
        """

        # Comfort: Distance from target temps (closer to 0 = better)
        comfort = -state["total_delta_abs"]

        # Stability: Power variance matters more than absolute value
        power_variance = self._get_recent_power_variance()
        stability = -10 if in_unstable else 0
        if power_variance is not None:
            stability -= min(power_variance / 50, 10)

        # Energy Efficiency: Lower power is better, but NOT at cost of comfort
        energy = -(state["power"] / 500)

        # Combined reward (weighted)
        total = comfort + stability + energy

        return {
            "total": total,
            "comfort": comfort,
            "stability": stability,
            "energy": energy,
            "power_variance": power_variance,
        }

    def _get_recent_power_variance(self) -> Optional[float]:
        """Calculate power variance from recent history for stability metric."""
        # Could query InfluxDB for last 15 min power variance
        # For now, return None (simpler)
        return None

    def log_episode(self, state: Dict, actions: List[Dict], reward: Dict):
        """Log episode for RL / policy learning (JSONL).

        Enhanced logging for building policy table:
        - outdoor_temp + time → best actions
        - We'll analyze this later to extract: "If temp=X, time=Y → do Z"
        """
        from datetime import datetime

        default_log = os.path.join(self.config_dir, "climatiq_rl.jsonl")
        log_file = self.args.get("log_file", default_log)

        # Extract time features for policy learning
        try:
            dt = datetime.fromisoformat(state["timestamp"])
            hour = dt.hour
            is_night = 23 <= hour or hour < 6
            is_morning = 6 <= hour < 10
            is_evening = 17 <= hour < 22
        except:
            hour = 0
            is_night = is_morning = is_evening = False

        episode = {
            "timestamp": state["timestamp"],
            "hour": hour,
            "is_night": is_night,
            "is_morning": is_morning,
            "is_evening": is_evening,
            "state": {
                "power": state["power"],
                "outdoor_temp": state["outdoor_temp"],
                "total_delta_abs": state["total_delta_abs"],
                "rooms": {k: v["delta"] for k, v in state["rooms"].items()},
                "rooms_on": sum(1 for r in state["rooms"].values() if r.get("is_on", False)),
            },
            "actions": actions,
            "reward": reward,
            "unstable_zones": self.unstable_zones,
        }

        try:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            with open(log_file, "a") as f:
                f.write(json.dumps(episode) + "\n")
        except Exception as e:
            self.log(f"Log-Fehler: {e}", level="WARNING")
