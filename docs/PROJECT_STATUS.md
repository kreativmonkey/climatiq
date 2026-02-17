# ClimatIQ - Projektstatus & Quick Reference

> Letzte Aktualisierung: 2026-02-12

## Projektstruktur (ohne venv/.git)

```
climatiq/
├── climatiq/                        # Haupt-Python-Package
│   ├── __init__.py
│   ├── config.py                    # Pydantic-basierte Konfiguration (YAML + ENV)
│   ├── analysis/
│   │   ├── __init__.py
│   │   └── cycling_detector.py      # Takterkennung aus Power-Daten (⚠️ ÜBERARBEITUNG NÖTIG)
│   ├── appdaemon/
│   │   ├── __init__.py
│   │   └── climatiq_app.py          # AppDaemon Entry-Point (ClimatIQ Klasse)
│   ├── core/
│   │   ├── __init__.py
│   │   ├── entities.py              # Pydantic-Models (SystemMode, UnitStatus, OptimizerStatus)
│   │   ├── observer.py              # Echtzeit-Überwachung + Takt-Erkennung
│   │   ├── analyzer.py              # Auto-Discovery stabiler Betriebsbereiche (Clustering)
│   │   ├── controller.py            # Steuerungslogik (Load Balancing, Temp, Fan)
│   │   └── predictor.py             # ML-Vorhersage (RandomForest) + Heuristik-Fallback
│   ├── data/
│   │   ├── __init__.py
│   │   ├── influx_client.py         # InfluxDB 2.x Client (Flux-Queries)
│   │   └── influx_v1_client.py      # InfluxDB 1.x Client (InfluxQL) ← WIRD VERWENDET
│   ├── control/
│   │   └── __init__.py              # Leer (Platzhalter)
│   └── models/
│       └── __init__.py              # Leer (Platzhalter)
├── config/
│   ├── config.example.yaml          # Beispiel-Konfiguration
│   └── apps.yaml.example            # AppDaemon apps.yaml Beispiel
├── data/
│   └── .gitkeep                     # Platzhalter für lokale Daten
├── docs/
│   ├── CONCEPT.md                   # Konzept & Architektur
│   └── PROJECT_STATUS.md            # ← Diese Datei
├── models/
│   └── .gitkeep                     # Platzhalter für trainierte Modelle
├── scripts/
│   └── test_connection.py           # InfluxDB Verbindungstest
├── tests/
│   ├── __init__.py
│   └── unit/
│       ├── __init__.py
│       ├── test_analyzer.py
│       ├── test_controller.py
│       ├── test_observer.py
│       └── test_predictor.py
├── .env                             # InfluxDB Credentials (NICHT committen!)
├── .env.example                     # Beispiel .env
├── .github/workflows/ci.yml         # CI Pipeline
├── pyproject.toml                    # Python Projekt-Setup
├── requirements.txt                 # Dependencies
├── README.md                        # Projekt-Dokumentation
└── CONTRIBUTING.md                  # Beitragsrichtlinien
```

## Implementierungsplan — Status

### Sprint 1: Grundgerüst ✅ ABGESCHLOSSEN
- [x] **AppDaemon App Struktur** → `climatiq/appdaemon/climatiq_app.py`
  - Vollständige `ClimatIQ(hass.Hass)` Klasse mit `initialize()`, Listeners, Schedules
  - Lädt Config, initialisiert alle Komponenten, erstellt HA-Sensoren
- [x] **InfluxDB Anbindung** → `climatiq/data/influx_v1_client.py`
  - Zwei Clients: v1 (InfluxQL, wird verwendet) + v2 (Flux, vorhanden als Alternative)
  - Abfrage historischer Daten, Entities listen, Resampling
  - Credentials in `.env` konfiguriert (Host: 192.168.10.25)
- [x] **Basis-Observer (Takt-Erkennung)** → `climatiq/core/observer.py` + `climatiq/analysis/cycling_detector.py`
  - Observer trackt Power-History, Unit-Status, Cycling-Risk
  - CyclingDetector erkennt On/Off-Zyklen mit Hysterese
  - ⚠️ **PROBLEM**: Erkennt nur An/Aus-Zyklen, nicht Leistungsschwankungen (siehe Änderungsanforderung unten)
- [x] **Einfache regelbasierte Steuerung** → `climatiq/core/controller.py`
  - 3 Strategien: Load Balancing, Temperature Modulation, Fan Control
  - Safety Limits (max ±1.5°C Abweichung, min 5 Min Intervall)
  - Action-Callback für HA Service Calls

### Sprint 2: Regelbasierte Steuerung 🔶 TEILWEISE
- [x] **Lastverteilungs-Logik** → In `controller.py` implementiert
  - Aktiviert niedrig-priorisierte Geräte als Puffer
- [ ] **Nachtmodus** → Noch nicht implementiert
  - Config hat `night_temperature`/`night_start`/`night_end`, aber keine Logik
- [ ] **Dashboard in HA** → Nur Grundstruktur
  - `_create_sensors()` ist leer (pass), `_update_dashboard()` setzt States

### Sprint 3: Machine Learning ✅ ABGESCHLOSSEN
- [x] **Feature Engineering** → `predictor.py:prepare_features()`
  - 9 Features: power, power_trend, power_std, outdoor_temp, avg_room_temp, temp_diff, hour, active_units, compressor_runtime
- [x] **Modell-Training** → `predictor.py:train()`
  - RandomForestClassifier, Cross-Validation, Feature Importance
  - Automatisches Retraining (täglich um 03:00)
- [x] **Prediction Integration** → `predictor.py:predict()`
  - ML-Prediction mit Fallback auf Heuristik wenn ML nicht verfügbar

### Sprint 4: Reinforcement Learning ❌ NICHT BEGONNEN
- [ ] RL-Agent Setup
- [ ] Online-Lernen
- [ ] Feintuning

## Komponenten-Übersicht

| Komponente | Status | Dateien | Was fehlt? |
|-----------|--------|---------|------------|
| **Observer** | ✅ Implementiert | `core/observer.py`, `analysis/cycling_detector.py` | ⚠️ Takterkennung überarbeiten (siehe unten) |
| **Analyzer** | ✅ Implementiert | `core/analyzer.py` | ⚠️ Stabilitäts-Schwellwert falsch (zeigt immer 1800W) |
| **Predictor** | ✅ Implementiert | `core/predictor.py` | Funktional, aber Label-Erzeugung basiert auf altem Takt-Verständnis |
| **Controller** | ✅ Implementiert | `core/controller.py` | Nachtmodus fehlt, Strategien an neues Takt-Verständnis anpassen |
| **Learner (RL)** | ❌ Nicht vorhanden | — | Kompletter Sprint 4 |
| **AppDaemon** | ✅ Implementiert | `appdaemon/climatiq_app.py` | Dashboard-Sensoren nur Platzhalter |
| **InfluxDB** | ✅ Implementiert | `data/influx_v1_client.py`, `data/influx_client.py` | Beide Versionen vorhanden |
| **Config** | ✅ Implementiert | `config.py`, `config/*.yaml` | Funktional |

## ⚠️ KRITISCHE ÄNDERUNGSANFORDERUNG: Takterkennung v2

**Stand 2026-02-12 — Feedback von Sebastian:**

### Problem 1: Falsche Definition von "Takten"
Das aktuelle System erkennt Takten nur als **Kompressor An/Aus-Wechsel** (über/unter Schwellwert 200W/100W).

**Richtig ist:** Takten = **häufige Schwankungen der Energieaufnahme**, auch INNERHALB eines "eingeschalteten" Zustands. Z.B. Wechsel zwischen 600W und 1500W gilt als Takten.

### Problem 2: Stabilitätserkennung fehlerhaft
Der Analyzer zeigt im Live-Betrieb stets an, das System sei nur bei **1800W stabil**. Real ist das System auch bei **400-600W stabil** möglich.

### Neues Ziel
1. **Minimale Energieaufnahme** bei Komforterhaltung
2. **Große Energiesprünge vermeiden** (nicht nur An/Aus)
3. Stabile Betriebspunkte bei niedrigen Leistungen finden und halten

### Betroffene Dateien
- `analysis/cycling_detector.py` — Kernlogik muss komplett überarbeitet werden
- `core/observer.py` — Nutzt `CyclingDetector`, muss angepasst werden
- `core/analyzer.py` — Stabilitätserkennung liefert falsche Schwellwerte
- `core/predictor.py` — Labels basieren auf altem Takt-Verständnis
- `core/controller.py` — Steuerungsstrategien an neues Ziel anpassen

## Quick Reference für Wiederaufnahme

### Einstiegspunkte
1. **AppDaemon-Integration**: `climatiq/appdaemon/climatiq_app.py` — Hauptklasse `ClimatIQ`
2. **Takterkennung (Kernlogik)**: `climatiq/analysis/cycling_detector.py` — `CyclingDetector`
3. **Steuerung**: `climatiq/core/controller.py` — `Controller.decide_action()`
4. **Konfiguration**: `climatiq/config.py` + `config/config.example.yaml`

### Starten / Testen
```bash
cd climatiq
source venv/bin/activate

# Verbindungstest InfluxDB
python scripts/test_connection.py

# Unit Tests
pytest tests/

# Als AppDaemon: climatiq_app.py → AppDaemon apps-Ordner kopieren
```

### Konfiguration
- `.env` → InfluxDB Zugangsdaten (Host: 192.168.10.25, DB: homeassistant)
- `config/apps.yaml.example` → AppDaemon-Config kopieren + anpassen
- `config/config.example.yaml` → Allgemeine Config

### Nächste logische Schritte (Priorität)
1. 🔴 **Takterkennung v2**: `cycling_detector.py` überarbeiten — Schwankungserkennung statt An/Aus
2. 🔴 **Analyzer fixen**: Stabile Betriebsbereiche korrekt erkennen (Stabil wenn keine Energieschwankung)
3. 🟡 **Controller anpassen**: Ziel = minimale Energie + keine großen Sprünge
4. 🟡 **Predictor Labels anpassen**: Neue Takt-Definition für Training verwenden
5. 🟢 **Nachtmodus implementieren**
6. 🟢 **Dashboard-Sensoren fertigstellen**

## Abhängigkeiten

### Externe Services
- **InfluxDB 1.x** @ 192.168.10.25:8086 (DB: homeassistant)
- **Home Assistant** mit Climate-Entities
- **AppDaemon** für Live-Steuerung

### Python Packages (requirements.txt)
- `pandas`, `numpy` — Datenverarbeitung
- `scikit-learn`, `joblib` — ML (RandomForest)
- `influxdb-client` — InfluxDB 2.x (influx_client.py)
- `matplotlib`, `seaborn` — Visualisierung
- `python-dotenv`, `pyyaml` — Config
- `pydantic`, `pydantic-settings` — Validierung (in pyproject.toml)
- `pytest` — Testing
