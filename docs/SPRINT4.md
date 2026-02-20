# Sprint 4: Rule-based Controller

## 🎯 Ziel

Intelligenter Controller der **Target-Temperaturen anpasst** statt stupide Units ein/auszuschalten.

**Primäre Strategie:** Target-Anpassung (Wärmepumpe regelt selbst)  
**Constraint:** Stabilität wahren (instabile Power-Zonen vermeiden)  
**Vorbereitung:** State-Action-Reward Logging für RL später

---

## 📦 Dateien

```
climatiq/
├── climatiq/controller/
│   └── rule_based_controller.py    # Haupt-Controller
├── config/
│   └── controller_config.json      # Rules & Room-Config
├── scripts/
│   ├── test_controller.py          # Dry-Run Test
│   └── controller_daemon.py        # Kontinuierlicher Betrieb
└── docs/
    ├── CONTROLLER.md                # Technische Doku
    └── SPRINT4.md                   # Dieses Dokument
```

---

## 🚀 Setup

### 1. Home Assistant Token

Erstelle einen Long-Lived Access Token in Home Assistant:
1. Gehe zu Profil → Security → Long-Lived Access Tokens
2. Erstelle Token
3. Setze als Umgebungsvariable:

```bash
export HA_TOKEN="dein_token_hier"
```

### 2. Config anpassen

Editiere `config/controller_config.json`:

```json
{
  "home_assistant": {
    "url": "http://localhost:8123",
    "token": "${HA_TOKEN}"
  },
  "rooms": { ... },
  "rules": { ... }
}
```

Token wird automatisch aus `$HA_TOKEN` geladen.

---

## 🧪 Testing

### Dry-Run (keine echten Actions):

```bash
cd ~/.openclaw/workspace/climatiq
source venv/bin/activate
python scripts/test_controller.py
```

**Output:**
```
=== CONTROL CYCLE START ===
State: Power=850W, Outdoor=2.5°C, TotalDelta=3.2K
  erdgeschoss: 21.5°C (Target: 21.0°C, Delta: +0.5K)
  kinderzimmer: 18.2°C (Target: 20.0°C, Delta: -1.8K)
  ...
DRY RUN: Würde 1 Actions ausführen:
  - kinderzimmer: 20.0°C → 20.5°C (Zu kalt (delta=-1.8K))
Reward: Total=-12.5 (Comfort=-8.5, Stability=0.0, Energy=-4.0)
=== CONTROL CYCLE END ===
```

---

## ▶️ Production

### Daemon starten (kontinuierlich):

```bash
# Alle 5 Minuten (Standard)
python scripts/controller_daemon.py config/controller_config.json

# Alle 10 Minuten
python scripts/controller_daemon.py config/controller_config.json --interval=600
```

**Graceful Shutdown:**
```bash
# CTRL+C oder:
kill -SIGTERM <pid>
```

---

## 📊 Monitoring

### Logs

**Controller Log:**
```bash
tail -f logs/rl_training_YYYYMMDD.jsonl
```

**Format (JSONL):**
```json
{"timestamp": "...", "state": {...}, "actions": [...], "reward": {...}}
```

### Metriken (aus Logs extrahieren)

```python
import json

with open('logs/rl_training_20260219.jsonl') as f:
    episodes = [json.loads(line) for line in f]

# Durchschnittlicher Reward
avg_reward = sum(e['reward']['total'] for e in episodes) / len(episodes)
print(f"Avg Reward: {avg_reward:.1f}")

# Anzahl Actions pro Cycle
action_counts = [len(e['actions']) for e in episodes]
print(f"Avg Actions: {sum(action_counts)/len(action_counts):.1f}")
```

---

## 🎛️ Rules Tuning

Die Rules in `controller_config.json` sind Ausgangspunkt - **diese sollten getuned werden!**

**Wichtige Parameter:**

### Comfort Toleranzen
```json
"comfort": {
  "temp_tolerance_cold": 1.5,  // Wann Action bei "zu kalt"?
  "temp_tolerance_warm": 1.0   // Wann Action bei "zu warm"?
}
```

**Empfehlung:** Start konservativ (1.5K/1.0K), dann reduzieren wenn stabil.

### Target-Schritte
```json
"adjustments": {
  "target_step": 0.5  // Schrittweite pro Action
}
```

**Empfehlung:** 0.5°C = sanft, 1.0°C = aggressiver

### Hysterese
```json
"hysteresis": {
  "min_action_interval_minutes": 15  // Cooldown pro Raum
}
```

**Empfehlung:** Start bei 15min, reduziere wenn zu träge.

### Stability
```json
"stability": {
  "unstable_power_min": 1000,  // Instabile Zone
  "unstable_power_max": 1500
}
```

**Basis:** Aus Sprint 3.2 V3 (kausale Analyse)

---

## 📈 Evaluation

### Baseline (vor Controller)

Miss über 7 Tage:
- Durchschnittlicher `power_std`
- Durchschnittlicher `total_delta_abs`
- Comfort-Score (Summe aller |delta|)

### Mit Controller (nach 7 Tagen)

Miss gleiche Metriken → Vergleich!

**Erwartung:**
- ✅ Niedrigerer `power_std` (stabiler)
- ✅ Niedrigerer `total_delta_abs` (bessere Raumtemps)
- ✅ Höherer Reward

---

## 🧠 RL Vorbereitung

Der Controller loggt **alle** Cycles in `logs/rl_training_*.jsonl`.

**State-Action-Reward Tripel** sind perfekt für RL:

### Später: Q-Learning

```python
# Pseudocode
Q[state, action] = reward + gamma * max(Q[next_state, :])

# Oder: Deep Q-Network (DQN)
# Oder: Proximal Policy Optimization (PPO)
```

**Training:**
1. Lade alle Logs (10k+ Episodes)
2. Trainiere RL-Agent
3. Evaluiere gegen Rule-based Baseline
4. Deploy wenn besser

---

## ⚠️ Safety

### Failsafes

Der Controller hat eingebaute Limits:

1. **Target Bounds:** 16-24°C (config)
2. **Max Actions:** 2 pro Cycle (nicht alles gleichzeitig)
3. **Cooldown:** 15min pro Raum (keine Oszillation)
4. **Instabile Zonen:** Keine Actions bei 1000-1500W

### Manual Override

Home Assistant hat **immer Vorrang**:
- User kann jederzeit Targets manuell ändern
- Controller respektiert neue Werte im nächsten Cycle

### Kill Switch

```bash
# Stop Daemon
kill -SIGTERM <pid>

# Oder: Disable in Config
"enabled": false
```

---

## 🐛 Debugging

### Controller startet nicht

```bash
# Check Config
python -c "import json; print(json.load(open('config/controller_config.json')))"

# Check HA Connection
curl -H "Authorization: Bearer $HA_TOKEN" http://localhost:8123/api/states
```

### Actions werden nicht ausgeführt

1. Check HA Token
2. Check Entity-IDs (müssen exakt matchen)
3. Check Cooldown (15min default)
4. Check Logs für Fehler

### System wird instabiler

1. Reduziere `target_step` (z.B. 0.3 statt 0.5)
2. Erhöhe `min_action_interval_minutes` (z.B. 30min)
3. Erhöhe Toleranzen (weniger Actions)

---

## 🎯 Nächste Schritte

**Sprint 4.1 (aktuell):**
- [x] Rule-based Controller
- [x] Target-Anpassung
- [x] Stability Constraints
- [x] State-Action-Reward Logging

**Sprint 4.2 (bald):**
- [ ] 7 Tage Test-Run
- [ ] Baseline vs. Controller Vergleich
- [ ] Rules Tuning basierend auf Ergebnissen

**Sprint 5 (später):**
- [ ] Reinforcement Learning
- [ ] Training auf historischen Logs
- [ ] RL Agent Deployment

---

## 📚 Weitere Doku

- **Technische Details:** `docs/CONTROLLER.md`
- **Kausale Analyse:** `docs/PLAN.md` (Sprint 3.2 V3)
- **ML Erkenntnisse:** `data/feature_importance_causal.csv`
