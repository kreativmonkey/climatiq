# ClimatIQ 🌡️

[![CI](https://github.com/kreativmonkey/climatiq/actions/workflows/ci.yml/badge.svg)](https://github.com/kreativmonkey/climatiq/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

**Intelligent Heat Pump Control with Machine Learning**

ClimatIQ analyzes your heat pump's behavior and automatically optimizes room temperatures to ensure maximum comfort while minimizing energy consumption and preventing compressor short-cycling.

---
[Deutsch](#deutsch) | [English](#english)

<a name="english"></a>
## English

### Features

- 🔍 **Automatic Zone Detection**: Learns stable and unstable operating zones from InfluxDB history using GMM Clustering.
- 🎯 **Intelligent Control**: Adjusts target temperatures gradually instead of aggressive On/Off switching.
- 📊 **ML-based Analysis**: Identifies cycling patterns and their causal factors (not just symptoms).
- 🤖 **RL-Ready**: Logs State-Action-Reward data for future Reinforcement Learning optimization.
- 🏠 **Home Assistant Integration**: Designed to run as a native AppDaemon app.
- 🏢 **Multi-Device Support (NEW in v3.1)**: Control multiple outdoor units with independent operating modes.

### 🏢 Multi-Device Support (NEW in v3.1)

ClimatIQ now supports **multiple outdoor units** with independent operating modes!

- ✅ Each outdoor unit has its own power sensor
- ✅ Independent heat/cool modes per unit
- ✅ Automatic room on/off control
- ✅ Night-mode optimization
- ✅ 100% backward compatible with single-unit configs

**Use Case:** Ground floor heating while upstairs cooling.

[Read full documentation →](docs/MULTI_DEVICE.md)

### How it Works

ClimatIQ operates on a simple but powerful principle: **Self-Learning Stability**.
Upon startup, it analyzes the last 30 days of heat pump power data to identify:
- **Stable Zones**: Power ranges where the unit runs efficiently (e.g., ~500W, ~1800W).
- **Unstable Zones**: Power ranges prone to cycling (e.g., 1000-1500W).

The controller then uses these insights to nudge room temperatures, steering the system toward stable operation.

### 🚀 Quick Installation (Home Assistant)

**You only need 2 files!**

#### Requirements
- Home Assistant with AppDaemon Add-on installed
- InfluxDB (for historical data analysis)

#### Installation Steps

1. **Download the controller files:**
   - [`appdaemon/apps/climatiq_controller.py`](appdaemon/apps/climatiq_controller.py) - The controller code
   - [`appdaemon/apps/climatiq.yaml`](appdaemon/apps/climatiq.yaml) - Configuration template

2. **Copy to Home Assistant:**
   ```bash
   # Place files in your AppDaemon apps directory
   /config/appdaemon/apps/climatiq_controller.py
   /config/appdaemon/apps/climatiq.yaml
   ```

3. **Configure:** Edit `climatiq.yaml` with your entity IDs
4. **Restart:** AppDaemon Add-on
5. **Done!** Check logs: `/config/appdaemon/appdaemon.log`

**Full setup guide:** See [docs/APPDAEMON_SETUP.md](docs/APPDAEMON_SETUP.md)

---

### 📁 Project Structure

**What each folder is for:**

```
climatiq/
├── appdaemon/apps/          # ← HOME ASSISTANT USERS: Copy these 2 files!
│   ├── climatiq_controller.py   # The controller (copy to HA)
│   └── climatiq.yaml             # Config template (copy to HA)
│
├── climatiq/                # ← DEVELOPERS ONLY: Python package
│   ├── core/                    # Controller classes (for testing)
│   ├── data/                    # InfluxDB client
│   ├── models/                  # ML models (future RL)
│   └── analysis/                # Analysis tools
│
├── tests/                   # ← DEVELOPERS ONLY: Unit tests
├── scripts/                 # ← OPTIONAL: Analysis scripts
├── docs/                    # ← REFERENCE: Documentation
├── data/                    # ← REFERENCE: Research artifacts
└── models/                  # ← FUTURE: Trained ML models
```

**Key takeaway:**
- **Home Assistant users:** Only need `appdaemon/apps/` (2 files)
- **Developers:** Need full repo for testing/development
- **`climatiq/` folder:** Python package for development, NOT for Home Assistant

---

### 🛠️ Development Setup

**For developers who want to work on the code:**

#### Clone Repository
```bash
git clone https://github.com/kreativmonkey/climatiq.git
cd climatiq
```

#### Setup Development Environment

**Option A: Nix (Recommended)**
```bash
echo "use flake" > .envrc
direnv allow
```

**Option B: Manual**
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### Run Tests
```bash
pytest tests/ -v
```

**For comprehensive development documentation, see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)**

---

<a name="deutsch"></a>
## Deutsch

### Funktionen

- 🔍 **Automatische Zonen-Erkennung**: Lernt stabile und instabile Betriebsbereiche aus der InfluxDB-Historie mittels GMM-Clustering.
- 🎯 **Intelligente Regelung**: Passt Soll-Temperaturen schrittweise an, um Takten (Cycling) zu vermeiden.
- 📊 **ML-Analyse**: Erkennt Takt-Muster und deren kausale Ursachen.
- 🤖 **RL-Ready**: Protokolliert State-Action-Reward-Daten für zukünftiges Reinforcement Learning.
- 🏠 **Home Assistant Integration**: Läuft als AppDaemon-App.
- 🏢 **Multi-Geräte-Unterstützung (NEU in v3.1)**: Steuerung mehrerer Außeneinheiten mit unabhängigen Betriebsmodi.

### 🏢 Multi-Geräte-Unterstützung (NEU in v3.1)

ClimatIQ unterstützt jetzt **mehrere Außeneinheiten** mit unabhängigen Betriebsmodi!

- ✅ Jede Außeneinheit hat ihren eigenen Leistungssensor
- ✅ Unabhängige Heiz-/Kühl-Modi pro Einheit
- ✅ Automatische Raum Ein-/Aus-Steuerung
- ✅ Nachtmodus-Optimierung
- ✅ 100% rückwärtskompatibel mit Einzel-Einheit-Konfigurationen

**Anwendungsfall:** Erdgeschoss heizt, während Obergeschoss kühlt.

[Vollständige Dokumentation →](docs/MULTI_DEVICE.md)

### Funktionsweise

ClimatIQ basiert auf dem Prinzip der **selbstlernenden Stabilität**.
Beim Start analysiert die App die Leistungsdaten der letzten 30 Tage und erkennt:
- **Stabile Zonen**: Leistungsbereiche, in denen die WP effizient läuft.
- **Instabile Zonen**: Bereiche, die zu häufigem Ein-/Ausschalten führen.

Der Controller nutzt diese Daten, um die Raumtemperaturen minimal anzupassen und das System so in einen stabilen Betriebsbereich zu lenken.

### 🚀 Schnell-Installation (Home Assistant)

**Du brauchst nur 2 Dateien!**

#### Voraussetzungen
- Home Assistant mit AppDaemon Add-on
- InfluxDB (für historische Datenanalyse)

#### Installations-Schritte

1. **Controller-Dateien herunterladen:**
   - [`appdaemon/apps/climatiq_controller.py`](appdaemon/apps/climatiq_controller.py) - Der Controller-Code
   - [`appdaemon/apps/climatiq.yaml`](appdaemon/apps/climatiq.yaml) - Konfigurations-Template

2. **Nach Home Assistant kopieren:**
   ```bash
   # Dateien ins AppDaemon apps-Verzeichnis
   /config/appdaemon/apps/climatiq_controller.py
   /config/appdaemon/apps/climatiq.yaml
   ```

3. **Konfigurieren:** `climatiq.yaml` mit deinen Entity-IDs anpassen
4. **Neustarten:** AppDaemon Add-on
5. **Fertig!** Logs prüfen: `/config/appdaemon/appdaemon.log`

**Vollständige Anleitung:** Siehe [docs/APPDAEMON_SETUP.md](docs/APPDAEMON_SETUP.md)

---

### 📁 Projekt-Struktur

**Wofür jeder Ordner ist:**

```
climatiq/
├── appdaemon/apps/          # ← HOME ASSISTANT NUTZER: Diese 2 Dateien kopieren!
│   ├── climatiq_controller.py   # Der Controller (nach HA kopieren)
│   └── climatiq.yaml             # Config-Template (nach HA kopieren)
│
├── climatiq/                # ← NUR FÜR ENTWICKLER: Python-Package
│   ├── core/                    # Controller-Klassen (für Tests)
│   ├── data/                    # InfluxDB-Client
│   ├── models/                  # ML-Modelle (zukünftig RL)
│   └── analysis/                # Analyse-Tools
│
├── tests/                   # ← NUR FÜR ENTWICKLER: Unit-Tests
├── scripts/                 # ← OPTIONAL: Analyse-Scripts
├── docs/                    # ← REFERENZ: Dokumentation
├── data/                    # ← REFERENZ: Research-Artefakte
└── models/                  # ← ZUKUNFT: Trainierte ML-Modelle
```

**Wichtig:**
- **Home Assistant Nutzer:** Nur `appdaemon/apps/` nötig (2 Dateien)
- **Entwickler:** Vollständiges Repo für Tests/Entwicklung
- **`climatiq/` Ordner:** Python-Package für Entwicklung, NICHT für Home Assistant

---

### 🛠️ Entwicklungs-Setup

**Für Entwickler, die am Code arbeiten wollen:**

#### Repository klonen
```bash
git clone https://github.com/kreativmonkey/climatiq.git
cd climatiq
```

#### Entwicklungsumgebung einrichten

**Option A: Nix (Empfohlen)**
```bash
echo "use flake" > .envrc
direnv allow
```

**Option B: Manuell**
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### Tests ausführen
```bash
pytest tests/ -v
```

**Für umfassende Entwicklungs-Dokumentation, siehe [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)**

---

## License
MIT License - see [LICENSE](LICENSE)

## Author
Developed by Sebastian Müller ([kreativmonkey](https://github.com/kreativmonkey)) with support from [OpenClaw](https://openclaw.ai).
