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

### Project Structure

```
climatiq/
├── appdaemon/apps/          # Home Assistant AppDaemon Integration
│   ├── climatiq_controller.py   # Main Controller App
│   └── climatiq.yaml            # Configuration
├── climatiq/                # Core Logic
│   ├── controller/          # Rule-based logic
│   ├── analysis/            # Cycling detection & ML
│   └── data/                # InfluxDB connectors
├── scripts/                 # Analysis & Utility scripts
└── docs/                    # Detailed documentation
```

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/kreativmonkey/climatiq.git
   ```
2. **Setup AppDaemon:**
   Copy the contents of `appdaemon/apps/` to your Home Assistant `/config/appdaemon/apps/` directory.
3. **Configure:**
   Edit `climatiq.yaml` to match your entities and InfluxDB credentials.

### Development

#### Using Nix Flakes (Recommended)
The easiest way to get a reproducible development environment:

```bash
nix develop
```

This provides an isolated shell with Python 3.11, all dependencies (influxdb, scikit-learn, numpy, pandas, pydantic), and development tools (black, ruff, pytest, mypy).

**Optional:** Use [direnv](https://direnv.net/) for automatic environment activation:
```bash
echo "use flake" > .envrc
direnv allow
```

#### Manual Setup
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### Running Tests
```bash
pytest                    # Run all tests
black . && ruff check .   # Format & lint
mypy climatiq/            # Type checking
```

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

### Entwicklung

#### Mit Nix Flakes (Empfohlen)
Der einfachste Weg für eine reproduzierbare Entwicklungsumgebung:

```bash
nix develop
```

Dies stellt eine isolierte Shell mit Python 3.11, allen Dependencies (influxdb, scikit-learn, numpy, pandas, pydantic) und Entwicklungstools (black, ruff, pytest, mypy) bereit.

**Optional:** [direnv](https://direnv.net/) für automatische Aktivierung:
```bash
echo "use flake" > .envrc
direnv allow
```

#### Manuelle Installation
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## License
MIT License - see [LICENSE](LICENSE)

## Author
Developed by Sebastian Müller ([kreativmonkey](https://github.com/kreativmonkey)) with support from [OpenClaw](https://openclaw.ai).
