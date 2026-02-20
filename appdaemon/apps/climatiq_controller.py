"""
ClimatIQ Controller V2 - AppDaemon Integration

Features:
- AUTOMATISCHE Zonen-Erkennung beim Start (GMM Clustering)
- Target-Anpassung als Hauptstrategie
- RL Logging (State-Action-Reward)
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import appdaemon.plugins.hass.hassapi as hass
import numpy as np


class ClimatIQController(hass.Hass):
    """Intelligenter Wärmepumpen-Controller mit automatischer Zonen-Erkennung"""

    def initialize(self):
        """AppDaemon Initialisierung"""

        self.rooms = self.args.get("rooms", {})
        self.sensors = self.args.get("sensors", {})
        self.rules = self.args.get("rules", {})
        self.influx_config = self.args.get("influxdb", {})

        self.last_action_time = {}
        self.unstable_zones = []
        self.stable_zones = []

        # 1. Automatische Zonen-Erkennung beim Start
        self.log("=== ClimatIQ Controller V2 ===")
        self.log("Starte automatische Zonen-Erkennung...")
        self.detect_zones_from_history()

        # 2. Control Cycle starten
        interval = self.args.get("interval_minutes", 5)
        self.run_every(self.control_cycle, datetime.now() + timedelta(seconds=30), interval * 60)

        # 3. Zonen täglich neu lernen (03:00 Uhr)
        self.run_daily(self.detect_zones_from_history, "03:00:00")

        self.log(
            f"Controller gestartet (Interval: {interval}min, Räume: {list(self.rooms.keys())})"
        )

    # =========================================================================
    # AUTOMATISCHE ZONEN-ERKENNUNG
    # =========================================================================

    def detect_zones_from_history(self, kwargs=None):
        """
        Lernt stabile/instabile Zonen aus InfluxDB Historie.
        Nutzt GMM (Gaussian Mixture Model) Clustering.
        """
        self.log("Lade historische Daten für Zonen-Erkennung...")

        try:
            # Versuche InfluxDB Daten zu laden
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
                self.log("✓ Zonen erkannt:")
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
        """Lädt Power-Historie aus InfluxDB"""

        # InfluxDB v1 Client importieren
        from influxdb import InfluxDBClient

        cfg = self.influx_config
        if not cfg.get("host"):
            self.log("Keine InfluxDB Config, nutze HA History", level="WARNING")
            return self._load_ha_history()

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
            FROM "{cfg.get('measurement', 'W')}"
            WHERE "entity_id" = '{cfg.get('power_entity', 'ac_current_energy')}'
            AND time > now() - 30d
            GROUP BY time(5m)
            FILL(none)
        """

        result = client.query(query)
        points = list(result.get_points())

        self.log(f"InfluxDB: {len(points)} Datenpunkte geladen")
        return points

    def _load_ha_history(self) -> Optional[List[Dict]]:
        """Fallback: Lade History aus Home Assistant"""

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
            except (ValueError, KeyError, TypeError):
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
        """Fallback wenn keine Daten verfügbar"""
        self.log("Nutze Fallback-Zonen (aus 90-Tage Analyse)", level="WARNING")
        self.unstable_zones = [{"min": 1000, "max": 1500, "reason": "fallback"}]
        self.stable_zones = [
            {"power_mean": 500, "power_std": 50},
            {"power_mean": 1800, "power_std": 80},
        ]

    def _save_zones_cache(self):
        """Speichert erkannte Zonen in Cache-Datei"""
        cache_path = "/config/appdaemon/apps/climatiq_zones_cache.json"
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
        """Hauptschleife - wird alle N Minuten ausgeführt"""

        self.log("--- Control Cycle ---")

        try:
            state = self.get_current_state()
            if not state:
                self.log("State nicht verfügbar", level="WARNING")
                return

            self.log(
                f"Power: {state['power']:.0f}W | Outdoor: {state['outdoor_temp']:.1f}°C | Δ Total: {state['total_delta_abs']:.1f}K"
            )

            # Check: Sind wir in instabiler Zone?
            in_unstable = self._is_in_unstable_zone(state["power"])
            if in_unstable:
                self.log(
                    f"⚠️ Instabile Zone ({state['power']:.0f}W) - keine Actions", level="WARNING"
                )
                self.log_episode(state, [], self.calculate_reward(state, in_unstable=True))
                return

            # Actions entscheiden & ausführen
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

    def _is_in_unstable_zone(self, power: float) -> bool:
        """Prüft ob aktuelle Power in instabiler Zone liegt"""
        for zone in self.unstable_zones:
            if zone["min"] <= power <= zone["max"]:
                return True
        return False

    def get_current_state(self) -> Optional[Dict]:
        """Liest aktuellen Zustand aus Home Assistant"""

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
                targ = self.get_state(cfg["climate_entity"], attribute="temperature")

                if curr in ["unknown", "unavailable", None]:
                    continue
                if targ in ["unknown", "unavailable", None]:
                    continue

                rooms[name] = {
                    "current_temp": float(curr),
                    "target_temp": float(targ),
                    "delta": float(curr) - float(targ),
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
        """Entscheidet welche Target-Anpassungen nötig sind"""

        actions = []
        rules = self.rules

        for name, room in state["rooms"].items():
            # Cooldown prüfen
            last = self.last_action_time.get(name, datetime.min)
            cooldown = timedelta(minutes=rules["hysteresis"]["min_action_interval_minutes"])
            if (datetime.now() - last) < cooldown:
                continue

            delta = room["delta"]
            target = room["target_temp"]
            step = rules["adjustments"]["target_step"]

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
        """Führt Target-Anpassung in Home Assistant aus"""

        room_name = action["room"]
        new_target = action["new_target"]
        entity = self.rooms[room_name]["climate_entity"]

        self.log(
            f"→ {room_name}: {action['old_target']:.1f}°C → {new_target:.1f}°C ({action['reason']})"
        )

        try:
            self.call_service("climate/set_temperature", entity_id=entity, temperature=new_target)
            self.last_action_time[room_name] = datetime.now()
        except Exception as e:
            self.log(f"Fehler bei Action: {e}", level="ERROR")

    def calculate_reward(self, state: Dict, in_unstable: bool = False) -> Dict:
        """Berechnet Reward für RL Training"""

        # Comfort: Nähe zu Soll-Temps
        comfort = -state["total_delta_abs"]

        # Stability Penalty
        stability = -20 if in_unstable else 0

        # Energy: Geringerer Verbrauch = besser
        energy = -(state["power"] / 500)

        total = comfort + stability + energy

        return {"total": total, "comfort": comfort, "stability": stability, "energy": energy}

    def log_episode(self, state: Dict, actions: List[Dict], reward: Dict):
        """Loggt Episode für RL Training (JSONL)"""

        log_file = self.args.get("log_file", "/config/appdaemon/logs/climatiq_rl.jsonl")

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
        }

        try:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            with open(log_file, "a") as f:
                f.write(json.dumps(episode) + "\n")
        except Exception as e:
            self.log(f"Log-Fehler: {e}", level="WARNING")
