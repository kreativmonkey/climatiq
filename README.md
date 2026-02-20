# ClimatIQ 🌡️

**Intelligente Wärmepumpen-Steuerung mit Machine Learning**

ClimatIQ analysiert das Verhalten deiner Wärmepumpe und optimiert automatisch die Raumtemperaturen für maximalen Komfort bei minimalem Energieverbrauch.

## Features

- 🔍 **Automatische Zonen-Erkennung**: Lernt stabile/instabile Betriebszonen aus InfluxDB-Historie (GMM Clustering)
- 🎯 **Intelligente Regelung**: Passt Soll-Temperaturen an statt On/Off-Schaltungen
- 📊 **ML-basierte Analyse**: Erkennt Cycling-Muster und deren Ursachen
- 🤖 **RL-Ready**: Loggt State-Action-Reward für zukünftiges Reinforcement Learning
- 🏠 **Home Assistant Integration**: Läuft als AppDaemon App

## Architektur

```
climatiq/
├── appdaemon/apps/          # Home Assistant AppDaemon Integration
│   ├── climatiq_controller.py   # Haupt-Controller
│   └── climatiq.yaml            # AppDaemon Konfiguration
├── climatiq/
│   ├── controller/          # Rule-based Controller
│   ├── analysis/            # Cycling Detection, ML Analysis
│   ├── core/                # Observer, Analyzer, Predictor
│   └── data/                # InfluxDB Client
├── scripts/                 # Analyse-Scripts
├── config/                  # Konfigurationsdateien
└── docs/                    # Dokumentation
```

## Quick Start

### 1. Installation

```bash
git clone https://github.com/kreativmonkey/climatiq.git
cd climatiq
pip install -r requirements.txt
```

### 2. Konfiguration

Kopiere die Beispiel-Konfiguration:
```bash
cp .env.example .env
# Bearbeite .env mit deinen InfluxDB-Zugangsdaten
```

### 3. AppDaemon Setup

Kopiere die AppDaemon-Dateien:
```bash
cp appdaemon/apps/* /config/appdaemon/apps/
```

Passe `climatiq.yaml` an deine Home Assistant Entities an.

## Wie es funktioniert

### Automatische Zonen-Erkennung

Beim Start analysiert ClimatIQ die letzten 30 Tage Wärmepumpen-Daten und erkennt automatisch:

- **Stabile Zonen**: Power-Bereiche wo das System ruhig läuft (z.B. ~500W, ~1800W)
- **Instabile Zonen**: Power-Bereiche mit häufigem Cycling (z.B. 1000-1500W)

Diese Zonen werden täglich neu gelernt - keine manuelle Konfiguration nötig!

### Regelstrategie

1. **Primär**: Soll-Temperatur-Anpassung (±0.5°C Schritte)
2. **Sekundär**: Vermeidung instabiler Power-Zonen
3. **Constraints**: Hysterese (15min Cooldown), max 2 Actions pro Cycle

### RL Logging

Jeder Control-Cycle wird geloggt:
```json
{
  "state": {"power": 1200, "outdoor_temp": 5.2, "rooms": {...}},
  "actions": [{"room": "wohnzimmer", "new_target": 21.5}],
  "reward": {"total": -3.2, "comfort": -1.5, "energy": -1.7}
}
```

Diese Daten können später für Reinforcement Learning verwendet werden.

## Dokumentation

- [Controller Dokumentation](docs/CONTROLLER.md)
- [AppDaemon Setup](docs/APPDAEMON_SETUP.md)
- [Entwicklungsplan](docs/PLAN.md)

## Lizenz

MIT License - siehe [LICENSE](LICENSE)

## Autor

Entwickelt mit Unterstützung von [OpenClaw](https://openclaw.ai)
