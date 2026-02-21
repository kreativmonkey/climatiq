# ClimatIQ AppDaemon Setup

## 🏠 Installation in Home Assistant

### Voraussetzungen

1. **AppDaemon Add-on** muss installiert sein:
   - Einstellungen → Add-ons → Add-on Store
   - Suche "AppDaemon 4"
   - Installiere & Starte

2. **InfluxDB** mit historischen Daten (für Analyse)

---

## 📦 Installation

### 1. Dateien kopieren

Kopiere die AppDaemon-Dateien in deine Home Assistant Installation:

```bash
# Auf deinem Home Assistant Server (via SSH oder File Editor):

# App-Datei
cp /home/diyon/.openclaw/workspace/climatiq/appdaemon/apps/climatiq_controller.py \
   /config/appdaemon/apps/

# Config-Datei
cp /home/diyon/.openclaw/workspace/climatiq/appdaemon/apps/climatiq.yaml \
   /config/appdaemon/apps/
```

**Oder via Home Assistant File Editor:**
1. Öffne File Editor Add-on
2. Navigiere zu `/config/appdaemon/apps/`
3. Erstelle neue Dateien:
   - `climatiq_controller.py` (kopiere Inhalt)
   - `climatiq.yaml` (kopiere Inhalt)

---

### 2. Config anpassen

Editiere `/config/appdaemon/apps/climatiq.yaml`:

```yaml
climatiq_controller:
  module: climatiq_controller
  class: ClimatIQController
  
  interval_minutes: 5  # Anpassen nach Bedarf
  
  sensors:
    power: sensor.ac_current_energy          # ← Deine Entity-ID
    outdoor_temp: sensor.ac_temperatur_outdoor  # ← Deine Entity-ID
  
  rooms:
    erdgeschoss:
      temp_sensor: sensor.temperatur_wohnzimmer        # ← Deine Entity-ID
      climate_entity: climate.panasonic_climate_erdgeschoss  # ← Deine Entity-ID
    # ... weitere Räume
```

**Wichtig:** Entity-IDs müssen exakt mit deinen Home Assistant Entities übereinstimmen!

**Tipp:** Check Entity-IDs:
- Entwicklerwerkzeuge → Zustände → Suche nach "climate" und "sensor"

---

### 3. AppDaemon neustarten

```bash
# Via Home Assistant UI:
# Einstellungen → Add-ons → AppDaemon → Restart

# Oder via CLI:
ha addons restart a0d7b954_appdaemon
```

---

### 4. Logs prüfen

```bash
# AppDaemon Log:
tail -f /config/appdaemon/appdaemon.log

# ClimatIQ-spezifisch:
grep "ClimatIQ" /config/appdaemon/appdaemon.log

# RL Training Log:
tail -f /config/appdaemon/logs/climatiq_rl_training.jsonl
```

**Erwartete Ausgabe:**
```
INFO climatiq_controller: ClimatIQ Controller gestartet (Interval: 5min)
INFO climatiq_controller: Räume: ['erdgeschoss', 'schlafzimmer', ...]
INFO climatiq_controller: === CLIMATIQ CONTROL CYCLE START ===
INFO climatiq_controller: Power: 850W, Outdoor: 2.5°C, Total Delta: 3.2K
INFO climatiq_controller: Keine Actions nötig
INFO climatiq_controller: Reward: -12.5 (Comfort: -8.5, Stability: 0.0)
INFO climatiq_controller: === CLIMATIQ CONTROL CYCLE END ===
```

---

## 🎛️ Konfiguration

### Interval anpassen

```yaml
interval_minutes: 5  # Standard: 5 Minuten
```

**Empfehlung:**
- Start: 5 Minuten (konservativ)
- Wenn stabil: 3 Minuten (reaktiver)
- Bei Problemen: 10 Minuten (defensiv)

### Rules Tuning

Basierend auf 90-Tage Analyse (siehe `data/feature_importance_causal.csv`):

```yaml
rules:
  comfort:
    temp_tolerance_cold: 1.5  # Niedriger = aggressiver
    temp_tolerance_warm: 1.0  # Niedriger = aggressiver
  
  adjustments:
    target_step: 0.5  # 0.3 = sanfter, 1.0 = aggressiver
  
  hysteresis:
    min_action_interval_minutes: 15  # Cooldown
  
  stability:
    unstable_power_min: 1000  # Aus 90-Tage Analyse
    unstable_power_max: 1500
```

**Tuning-Prozess:**
1. Start mit Default-Werten (7 Tage laufen lassen)
2. Analysiere `climatiq_rl_training.jsonl`
3. Adjustiere Parameter
4. Teste weitere 7 Tage

---

## 📊 Monitoring

### Home Assistant Dashboard

Erstelle Sensor für Monitoring:

```yaml
# configuration.yaml
template:
  - sensor:
      - name: "ClimatIQ Total Delta"
        state: >
          {% set delta = 0 %}
          {% for room in ['erdgeschoss', 'schlafzimmer', 'arbeitszimmer', 'kinderzimmer', 'ankleide'] %}
            {% set current = states('sensor.temperatur_' ~ room) | float(0) %}
            {% set target = state_attr('climate.panasonic_climate_' ~ room, 'temperature') | float(0) %}
            {% set delta = delta + (current - target) | abs %}
          {% endfor %}
          {{ delta | round(1) }}
        unit_of_measurement: "K"
      
      - name: "ClimatIQ Reward"
        state: >
          {# Wird von AppDaemon aktualisiert #}
          {{ states('sensor.climatiq_reward') | float(0) }}
```

### Grafana Dashboard

Wenn du Grafana hast, visualisiere:
- `total_delta_abs` über Zeit
- `reward.total` über Zeit
- `power` mit Markierungen für Actions

---

## 📊 ClimatIQ Device & Sensors

ClimatIQ erstellt automatisch ein Home Assistant Gerät mit 12 Sensor-Entitäten:

### System-Metriken
- **sensor.climatiq_power** - Aktuelle Leistung (W)
- **sensor.climatiq_outdoor_temp** - Außentemperatur (°C)
- **sensor.climatiq_total_delta** - Gesamte Raumabweichung (K)
- **sensor.climatiq_stability_state** - Systemzustand (stable/unstable/transition)

### Performance-Metriken
- **sensor.climatiq_cycles_today** - Kompressor-Zyklen heute
- **sensor.climatiq_actions_today** - Controller-Aktionen heute
- **sensor.climatiq_last_reward** - Letzter Reward-Wert
- **sensor.climatiq_compressor_runtime** - Laufzeit % heute

### Status-Metriken
- **sensor.climatiq_emergency_active** - Emergency-Override aktiv (ja/nein)
- **sensor.climatiq_cooldown_active** - Cooldown aktiv (ja/nein)
- **sensor.climatiq_active_rooms** - Anzahl aktiver Räume
- **sensor.climatiq_critical_room** - Raum mit höchster Abweichung

### Verwendung

**Dashboard-Karte:**
```yaml
type: entities
title: ClimatIQ System
entities:
  - sensor.climatiq_power
  - sensor.climatiq_outdoor_temp
  - sensor.climatiq_total_delta
  - sensor.climatiq_stability_state
  - sensor.climatiq_cycles_today
  - sensor.climatiq_actions_today
  - sensor.climatiq_emergency_active
  - sensor.climatiq_critical_room
```

**Automatisierung (Beispiel):**
```yaml
automation:
  - alias: "ClimatIQ Emergency Alert"
    trigger:
      - platform: state
        entity_id: sensor.climatiq_emergency_active
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          message: "ClimatIQ Emergency! Delta: {{ states('sensor.climatiq_total_delta') }}K"
```

---

## 🐛 Troubleshooting

### Controller startet nicht

**Check 1: AppDaemon Log**
```bash
tail -n 50 /config/appdaemon/appdaemon.log | grep ERROR
```

**Häufige Fehler:**
- Syntax-Fehler in YAML → Check Indentation
- Modul nicht gefunden → Check Dateinamen (muss `climatiq_controller.py` sein)
- Import-Fehler → Check Python-Syntax

**Check 2: Entity-IDs**
```bash
# In Home Assistant:
# Entwicklerwerkzeuge → Zustände
# Suche nach deinen climate/sensor Entities
```

### Controller läuft, aber keine Actions

**Mögliche Gründe:**

1. **Cooldown aktiv:**
   - Check: Logs zeigen "Zu viele Actions" oder keine Meldung?
   - Lösung: Warte 15 Minuten oder reduziere `min_action_interval_minutes`

2. **Instabile Power-Zone:**
   - Check: Power zwischen 1000-1500W?
   - Lösung: Warte bis System aus dieser Zone ist

3. **Toleranzen zu hoch:**
   - Check: Alle Räume innerhalb ±1.5K / ±1.0K?
   - Lösung: Reduziere Toleranzen in Config

4. **Total Delta zu hoch:**
   - Check: `total_delta_abs > 10K`?
   - Lösung: System priorisiert größte Abweichung, andere warten

### Actions werden ausgeführt, aber wirken nicht

**Check:**
1. Sind climate entities wirklich erreichbar?
   ```bash
   # Test manuell:
   # Entwicklerwerkzeuge → Services
   # Service: climate.set_temperature
   # Entity: climate.panasonic_climate_erdgeschoss
   # Data: {"temperature": 21.5}
   ```

2. Logge `old_target` vs `new_target`:
   - Ist Änderung groß genug? (0.5°C sollte sichtbar sein)

### System wird instabiler

**Sofort:**
1. Stop AppDaemon: `ha addons stop a0d7b954_appdaemon`
2. Prüfe Logs auf Fehler
3. Reduziere Aggressivität:
   ```yaml
   target_step: 0.3  # Statt 0.5
   min_action_interval_minutes: 30  # Statt 15
   ```

---

## 📈 Evaluation (nach 7 Tagen)

### Baseline vs. Controller Vergleich

**Metriken:**

1. **Stabilität:** Durchschnittlicher `power_std`
   ```python
   # Aus InfluxDB
   SELECT mean(power_std) FROM ... WHERE time > now() - 7d
   ```

2. **Comfort:** Durchschnittlicher `total_delta_abs`
   ```python
   # Aus RL Log
   import json
   episodes = [json.loads(line) for line in open('climatiq_rl_training.jsonl')]
   avg_delta = sum(e['state']['total_delta_abs'] for e in episodes) / len(episodes)
   ```

3. **Energie:** Durchschnittliche Power
   ```python
   SELECT mean(power) FROM ... WHERE time > now() - 7d
   ```

**Erwartung:**
- ✅ Niedrigerer `power_std` (stabiler)
- ✅ Niedrigerer `total_delta_abs` (bessere Temps)
- ✅ Gleiche oder niedrigere `power` (effizienter)

---

## 🧠 Reinforcement Learning (später)

Die `climatiq_rl_training.jsonl` sammelt State-Action-Reward Tripel.

**Nach 30+ Tagen:**
1. Extrahiere alle Episoden
2. Trainiere RL Agent (Q-Learning / PPO)
3. Evaluiere gegen Rule-based Baseline
4. Deploy wenn besser

**Tools:**
- Stable Baselines3 (PPO, DQN)
- Gymnasium (RL Environment)
- TensorBoard (Training Monitoring)

---

## 🔐 Security

**Wichtig:**
- AppDaemon hat vollen Zugriff auf Home Assistant
- Controller kann alle climate Entities steuern
- **Test erst im dry-run Modus!** (siehe nächster Abschnitt)

### Dry-Run Modus (zum Testen)

Erstelle Test-Version ohne Execution:

```python
# In climatiq_controller.py, execute_action():
def execute_action(self, action: Dict, state: Dict):
    # Kommentiere aus für dry-run:
    # self.call_service(...)
    
    # Nur loggen:
    self.log(f"[DRY RUN] Würde {action['room']} auf {action['new_target']:.1f}°C setzen")
```

Test 24h im dry-run, dann echte Execution aktivieren.

---

## 📚 Weitere Ressourcen

- **AppDaemon Doku:** https://appdaemon.readthedocs.io/
- **Home Assistant API:** https://developers.home-assistant.io/docs/api/rest/
- **ClimatIQ Analyse:** `docs/SPRINT4.md`
- **Kausale Faktoren:** `data/feature_importance_causal.csv`
