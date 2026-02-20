# ClimatIQ Controller Documentation

## Sprint 4: Rule-based Controller mit Target-Anpassung

### Konzept

Der Controller nutzt **Target-Anpassung** als Hauptstrategie statt stupide Units ein/auszuschalten:

**Strategie-Hierarchie:**
1. **Primär: Target-Anpassung** - Passe Soll-Temperaturen an (Wärmepumpe regelt selbst)
2. **Sekundär: Stabilität** - Vermeide instabile Zonen (1000-1500W)
3. **Tertiär: Units schalten** - Nur bei Bedarf (später implementiert)

### Architektur

```
State → Rules → Actions → Execution → Reward → Log
  ↓                                              ↓
  └─────────────── RL Training (später) ────────┘
```

**Komponenten:**
- `RuleBasedController` - Hauptklasse
- `controller_config.json` - Rules & Room-Definitionen
- `rl_training_log.jsonl` - State-Action-Reward Log für RL

### Rules (aktuell)

#### 1. Comfort Rules
- **Zu kalt** (delta < -1.5K): Target +0.5°C
- **Zu warm** (delta > +1.0K): Target -0.5°C

#### 2. Stability Constraints
- **Max Actions**: 2 pro Cycle (nicht alles gleichzeitig)
- **Power-Zone**: Vermeide Actions bei 1000-1500W (instabil)
- **Total Delta**: Wenn > 10K, nur größte Abweichung korrigieren

#### 3. Hysterese
- **Cooldown**: Min. 15 Minuten zwischen Actions pro Raum

### State

```python
{
  "timestamp": "2026-02-19T11:00:00",
  "power": 850.0,
  "outdoor_temp": 2.5,
  "rooms": {
    "erdgeschoss": {
      "current_temp": 21.5,
      "target_temp": 21.0,
      "delta": +0.5
    },
    ...
  },
  "total_delta_abs": 3.2
}
```

### Actions

```python
{
  "room": "kinderzimmer",
  "old_target": 20.0,
  "new_target": 20.5,
  "reason": "Zu kalt (delta=-1.8K)"
}
```

### Reward (für RL später)

```python
{
  "comfort_score": -3.5,    # Summe aller |delta|
  "stability_score": -10.0,  # Penalty für instabile Zonen
  "energy_score": -8.5,      # Power-basiert
  "total": -22.0
}
```

Höherer Reward = besser

### Kausale Faktoren (aus Sprint 3.2 V3)

Der Controller nutzt Erkenntnisse aus der ML-Analyse:

**Top Ursachen für Instabilität:**
1. **power_level (19.7%)** - Manche Last-Levels sind instabiler
2. **delta_eg (9.5%)** - Erdgeschoss-Abweichung
3. **delta_kz_abs (7.6%)** - Kinderzimmer-Abweichung
4. **total_delta_abs (7.5%)** - Gesamtabweichung
5. **outdoor_temp (7.4%)** - Außentemperatur

→ Controller vermeidet hohe total_delta und instabile Power-Zonen.

### Usage

#### Test (Dry-Run):
```bash
python scripts/test_controller.py
```

#### Single Cycle:
```bash
python climatiq/controller/rule_based_controller.py config/controller_config.json --dry-run
```

#### Daemon (kontinuierlich):
```bash
python scripts/controller_daemon.py config/controller_config.json
# Läuft alle 5 Minuten
```

### Config

```json
{
  "rules": {
    "comfort": {
      "temp_tolerance_cold": 1.5,  // Unter -1.5K → Action
      "temp_tolerance_warm": 1.0   // Über +1.0K → Action
    },
    "adjustments": {
      "target_step": 0.5,           // Schrittweite
      "target_min": 16.0,
      "target_max": 24.0
    },
    "hysteresis": {
      "min_action_interval_minutes": 15
    },
    "stability": {
      "max_actions_per_cycle": 2,
      "max_total_delta": 10.0,
      "unstable_power_min": 1000,   // Instabile Zone
      "unstable_power_max": 1500
    }
  }
}
```

### Logs für RL

Jeder Cycle loggt:
```json
{
  "timestamp": "...",
  "state": { ... },
  "actions": [ ... ],
  "reward": { ... }
}
```

Format: JSONL (newline-delimited JSON)

Diese Logs werden später für Reinforcement Learning genutzt:
- **State**: Input
- **Action**: Was Controller gemacht hat
- **Reward**: Wie gut war die Entscheidung

### Nächste Schritte

**Phase 1 (aktuell):**
- ✅ Rule-based Controller
- ✅ Target-Anpassung
- ✅ Stability Constraints
- ✅ State-Action-Reward Logging

**Phase 2 (bald):**
- [ ] Daemon mit kontinuierlichem Betrieb
- [ ] Metriken & Monitoring
- [ ] A/B Testing (Rule-based vs. Baseline)

**Phase 3 (später):**
- [ ] Reinforcement Learning
- [ ] Q-Learning oder PPO
- [ ] Training auf historischen Logs
- [ ] Hybrid: RL + Rule-based Fallback
