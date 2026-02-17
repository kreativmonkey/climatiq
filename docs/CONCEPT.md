# ClimatIQ - Konzept

> **Version 2.0** - Überarbeitet 2026-02-17  
> Branch: `feature/stability-optimizer-v2`

## Ziel
Ein selbstlernendes Home Assistant Tool, das Multi-Split Klimaanlagen so steuert, dass **Leistungsschwankungen (Takten) vermieden** werden, während die **Komforttemperatur** bei **minimaler stabiler Energieaufnahme** gehalten wird.

### Kernprinzipien (v2)
1. **Stabilität über alles**: Gleichmäßiger Betrieb schlägt kurzfristige "Effizienz"
2. **Minimale Energie bei Stabilität**: Niedrigste Leistungsaufnahme mit geringer Varianz
3. **Lernen aus Daten**: System-spezifische Schwellwerte, keine hardcoded Annahmen
4. **Proaktive Anpassung**: Probleme vermeiden, bevor sie auftreten

## Architektur

```
┌─────────────────────────────────────────────────────────┐
│                    Home Assistant                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │ climate.eg  │  │ climate.sz  │  │ climate.az  │ ... │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘     │
│         │                │                │             │
│         └────────────────┼────────────────┘             │
│                          │                              │
│              ┌───────────▼───────────┐                  │
│              │   ClimatIQ      │                  │
│              │   (AppDaemon App)     │                  │
│              └───────────┬───────────┘                  │
│                          │                              │
└──────────────────────────┼──────────────────────────────┘
                           │
              ┌────────────▼────────────┐
              │       InfluxDB          │
              │  (Historische Daten)    │
              └─────────────────────────┘
```

## Komponenten

### 1. Observer (Beobachter) - v2
- Überwacht Stromverbrauch in Echtzeit mit **Power Variance Tracking**:
  - **Power Mean**: Durchschnitt der letzten 5 Min
  - **Power Std Dev**: Standardabweichung (Maß für Stabilität)
  - **Power Gradient**: Trend (W/min) - steigend, fallend, stabil
  - **Power Spread**: Max - Min in Zeitfenster
  - **Cycling Risk**: 0-100% basierend auf Varianz-Metriken
- Erkennt **Takten als Leistungsschwankungen**, nicht nur An/Aus
- Sammelt Zustandsdaten:
  - Raumtemperaturen (Ist/Soll)
  - Außentemperatur
  - Lüfterstufen
  - Aktive Geräte
  - Kompressor-Laufzeit (aus Power-History abgeleitet)

### 2. Analyzer (Analyse) - v2 NEU
- **Auto-Discovery stabiler Betriebsbereiche**:
  - Clustering (DBSCAN / GMM) auf historischen Daten
  - Features: Power Mean, Power Std Dev, Outdoor Temp, Active Units
  - Ziel: Finde Zonen mit niedriger Varianz bei niedriger Leistung
- **Adaptive Schwellwerte**: Keine festen 400W/1800W, lernt system-spezifisch
- **Multi-dimensionale Stabilität**: (Power, Temp, Units, Fan) Kombinationen
- Output: Liste stabiler Betriebspunkte mit Parametern

### 3. Predictor (Vorhersage) - v2
- ML-Modell: RandomForest Classifier
- Input: Power-Statistiken (mean, std, gradient), Temperaturen, Tageszeit, aktive Geräte
- Output: Cycling Risk (0-100%), Wahrscheinlichkeit in nächsten 10 Min
- Trainiert auf historischen Daten mit **neuer Takt-Definition** (Varianz-basiert)
- Fallback: Heuristische Regeln wenn ML nicht verfügbar

### 4. Controller (Steuerung) - v2
- Entscheidet Aktionen basierend auf Vorhersage + Analyzer-Zonen
- Strategien (verfeinert):
  - **Load Balancing**: Aktiviere Geräte um in stabile Zone zu kommen
  - **Temperature Modulation**: Kleinere Schritte (±0.3°C), sanft
  - **Fan Control**: Graduell anpassen, keine Sprünge
  - **Preemptive Buffering**: Puffer-Räume vor Risiko-Peak aktivieren
  - **Night Mode**: 23:00-07:00 niedrigere Temps, mehrere Geräte
- **Safety**: Max ±1.5°C Abweichung, Min 5 Min zwischen Aktionen
- **Hysteresis**: Nicht sofort zurückändern, Stabilität abwarten

### 5. Learner (Lernender) - Future
- Bewertet Erfolg der Aktionen (Outcome-Tracking)
- Passt Strategie-Parameter an (Parameter-Tuning)
- **Future**: Reinforcement Learning Agent (PPO/SAC)
  - Reward: +1 pro Min stabil, -10 pro Takt-Event
  - Safe Exploration mit Constraints
  - Simulations-Training vor Live-Deployment

## Datenfluss

```
1. OBSERVE (v2)
   │
   ├── Power: Mean 480W, Std Dev 120W (Schwankungen!)
   ├── Gradient: +15 W/min (steigend)
   ├── Spread: Max 650W, Min 350W (Δ=300W, instabil)
   ├── Cycling Risk: 75% (hoch!)
   ├── Rooms: EG 21.8°C, SZ 22.1°C, AZ aus
   └── Outside: 4°C
   
2. ANALYZE
   │
   └── Stable Zone gefunden: 2 Geräte, 550-650W, Std Dev <30W
   
3. PREDICT
   │
   └── ML Model: "Takten in 8 min wahrscheinlich (82%)"
   
4. DECIDE
   │
   ├── Strategie: Load Balancing → aktiviere AZ als Puffer
   ├── Ziel: Power in stabile Zone 550-650W bringen
   └── Aktion: "Aktiviere AZ mit Soll 20°C, Fan LOW"
   
5. ACT
   │
   └── climate.set_temperature(az, 20)
       climate.set_fan_mode(az, "low")
   
6. OBSERVE (nach 10 min)
   │
   ├── Power: Mean 580W, Std Dev 25W (stabil! ✓)
   ├── Gradient: -2 W/min (ausgeglichen)
   ├── Cycling Risk: 15% (niedrig)
   └── Ergebnis: Aktion erfolgreich, kein Takten
   
7. LEARN
   │
   ├── Outcome: Positiv (+1 Punkt)
   └── Update: "Bei Power Std Dev >100W + 2 Geräte → +1 Gerät = gut"
```

## Lernansatz

### Phase 1: Regelbasiert (Sofort einsetzbar)
Einfache Regeln basierend auf Analyse:
- Wenn Power < 400W und nur 1-2 Geräte aktiv → aktiviere weiteres Gerät
- Wenn Takten erkannt → sofort Lastverteilung
- Nachts (23-06h) → präventiv mehr Geräte aktivieren

### Phase 2: Supervised Learning
- Trainiere Modell auf historischen Daten
- Features: Temperaturen, Power, Tageszeit, Geräte-Status
- Target: Takten ja/nein in nächsten 10 min

### Phase 3: Reinforcement Learning
- Agent lernt optimale Strategie durch Ausprobieren
- Reward: +1 für jede Minute ohne Takten, -10 für jeden Takt
- State: Alle Sensordaten
- Actions: Geräte ein/aus, Solltemp ±0.5°C, Lüfterstufe

## Home Assistant Integration

### Als AppDaemon App
```yaml
# apps.yaml
climatiq:
  module: climatiq
  class: HVACOptimizer
  
  # Geräte-Konfiguration
  indoor_units:
    - entity_id: climate.erdgeschoss
      temp_sensor: sensor.eg_temperatur
      priority: high
    - entity_id: climate.schlafzimmer
      temp_sensor: sensor.sz_temperatur
      priority: medium
    # ...
  
  # Sensoren
  power_sensor: sensor.ac_current_energy
  outdoor_temp: sensor.outdoor_temperature
  
  # InfluxDB
  influxdb:
    host: 192.168.10.25
    port: 8086
    database: homeassistant
  
  # Komfort-Einstellungen
  comfort:
    target_temp: 21.0
    tolerance: 0.5
    
  # Lern-Einstellungen
  learning:
    enabled: true
    model_path: /config/hvac_model.pkl
```

### Entities die erstellt werden
- `sensor.climatiq_status` - Aktueller Zustand
- `sensor.climatiq_cycling_risk` - Takt-Risiko (0-100%)
- `sensor.climatiq_efficiency_score` - Effizienz-Score
- `switch.climatiq_enabled` - An/Aus
- `number.climatiq_target_power` - Ziel-Mindestleistung

## Sicherheit

### Grenzen
- Maximale Abweichung von Nutzer-Solltemperatur: ±1.5°C
- Nutzer-Einstellungen haben immer Vorrang
- Notfall-Bypass wenn Temperatur kritisch

### Logging
- Alle Entscheidungen werden geloggt
- Erklärbar: "Habe AZ aktiviert weil Power nur 350W"

## Implementierungsplan

### Sprint 1: Grundgerüst (diese Woche)
- [ ] AppDaemon App Struktur
- [ ] InfluxDB Anbindung
- [ ] Basis-Observer (Takt-Erkennung)
- [ ] Einfache regelbasierte Steuerung

### Sprint 2: Regelbasierte Steuerung
- [ ] Lastverteilungs-Logik
- [ ] Nachtmodus
- [ ] Dashboard in HA

### Sprint 3: Machine Learning
- [ ] Feature Engineering
- [ ] Modell-Training
- [ ] Prediction Integration

### Sprint 4: Reinforcement Learning
- [ ] RL-Agent Setup
- [ ] Online-Lernen
- [ ] Feintuning

## Metriken für Erfolg (v2)

### Primäre Ziele (Must-Have)
1. **Takt-Reduktion**: <10 Takt-Events/Tag (Baseline: 50-100/Tag) = 90% Reduktion
2. **Stabilität**: >80% der Betriebszeit mit Power Std Dev <50W
3. **Komfort**: Temperatur-Abweichung <0.5°C RMS vom Sollwert
4. **Minimale Energie**: 50%+ der stabilen Zeit bei <600W Leistung

### Sekundäre Ziele (Nice-to-Have)
1. **Kompressor-Laufzeit**: Durchschnittliche Zyklus-Länge >30 Min (Baseline: ~3 Min)
2. **Interventionseffizienz**: <8 Steuerungsaktionen/Tag
3. **Vorhersagegenauigkeit**: Cycling Risk Prediction F1 >0.70
4. **Nutzerzufriedenheit**: <2 manuelle Overrides/Woche

### Datenerfassung
- **InfluxDB**: Alle 30s: Power, Temps, Actions, Outcomes
- **Memory**: Daily Summary in `memory/YYYY-MM-DD.md`
- **Models**: Training Metrics bei jedem Retrain
