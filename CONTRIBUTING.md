# Contributing to ClimatIQ

Danke für dein Interesse an diesem Projekt! Hier findest du alle Infos, um mitzuentwickeln.

## Entwicklungsumgebung einrichten

### Voraussetzungen

- Python 3.11 oder höher
- Git
- InfluxDB (für Tests mit echten Daten, optional)
- Home Assistant mit AppDaemon (für Integration Tests, optional)

### Setup

```bash
# 1. Repository klonen
git clone https://github.com/YOUR_USERNAME/climatiq.git
cd climatiq

# 2. Virtual Environment erstellen
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# oder: venv\Scripts\activate  # Windows

# 3. Dependencies installieren (inkl. Dev-Dependencies)
pip install -e ".[dev]"

# 4. Pre-commit Hooks installieren (optional, empfohlen)
pre-commit install

# 5. Umgebungsvariablen konfigurieren
cp .env.example .env
# Dann .env mit deinen Werten anpassen
```

### Projektstruktur

```
climatiq/
├── climatiq/           # Hauptpaket
│   ├── core/                 # Kernlogik
│   │   ├── observer.py       # Datensammlung & Monitoring
│   │   ├── analyzer.py       # Muster-Erkennung
│   │   ├── predictor.py      # ML Vorhersage
│   │   ├── controller.py     # Steuerungslogik
│   │   └── learner.py        # Reinforcement Learning
│   ├── data/                 # Daten-Layer
│   │   ├── influx_client.py  # InfluxDB Anbindung
│   │   └── ha_client.py      # Home Assistant API
│   ├── models/               # ML Modelle
│   ├── analysis/             # Analyse-Tools
│   └── appdaemon/            # AppDaemon Integration
├── tests/                    # Test-Suite
│   ├── unit/                 # Unit Tests
│   ├── integration/          # Integration Tests
│   └── fixtures/             # Test-Daten
├── config/                   # Beispiel-Konfigurationen
├── docs/                     # Dokumentation
└── scripts/                  # Hilfs-Skripte
```

### Tests ausführen

```bash
# Alle Tests
pytest

# Mit Coverage
pytest --cov=climatiq --cov-report=html

# Nur Unit Tests (schnell, keine externe Abhängigkeiten)
pytest tests/unit/

# Nur Integration Tests (braucht InfluxDB)
pytest tests/integration/

# Einzelne Test-Datei
pytest tests/unit/test_observer.py -v
```

### Code-Style

Wir nutzen:
- **Black** für Formatierung
- **Ruff** für Linting
- **MyPy** für Type Checking

```bash
# Formatieren
black climatiq/ tests/

# Linting
ruff check climatiq/ tests/

# Type Checking
mypy climatiq/
```

### Pull Request Workflow

1. Fork das Repository
2. Erstelle einen Feature-Branch: `git checkout -b feature/mein-feature`
3. Schreibe Tests für deine Änderungen
4. Stelle sicher, dass alle Tests grün sind: `pytest`
5. Formatiere deinen Code: `black .`
6. Committe mit aussagekräftiger Message
7. Push und erstelle einen Pull Request

### Commit Messages

Wir folgen [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: Neue Funktionalität hinzugefügt
fix: Bug behoben
docs: Dokumentation aktualisiert
test: Tests hinzugefügt/geändert
refactor: Code-Refactoring ohne Funktionsänderung
```

## Architektur-Überblick

### Datenfluss

```
InfluxDB (Historie) ──┐
                      ├──► Observer ──► Analyzer ──► Predictor
Home Assistant (Live) ┘                                  │
                                                         ▼
                      ┌─────────────────────────── Controller
                      │                                  │
                      ▼                                  ▼
               Home Assistant                        Learner
              (Aktionen ausführen)              (Feedback verarbeiten)
```

### Betriebsmodi

1. **OBSERVATION** - Nur Daten sammeln, keine Aktionen (Default bei neuer Installation)
2. **LEARNING** - Modell trainieren auf gesammelten Daten
3. **ACTIVE** - Vorhersagen machen und Aktionen ausführen
4. **MANUAL** - Deaktiviert, Nutzer steuert manuell

## Hilfe & Fragen

- GitHub Issues für Bugs und Feature Requests
- Discussions für Fragen und Ideen
