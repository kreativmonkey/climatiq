# ClimatIQ - Konzept

## Ziel
Ein selbstlernendes Home Assistant Tool, das Multi-Split Klimaanlagen so steuert, dass **Kompressor-Takten vermieden** wird, während die **Komforttemperatur** gehalten wird.

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

### 1. Observer (Beobachter)
- Überwacht Stromverbrauch in Echtzeit
- Erkennt Takten (schnelle An/Aus-Wechsel)
- Sammelt Zustandsdaten:
  - Raumtemperaturen (Ist/Soll)
  - Außentemperatur
  - Lüfterstufen
  - Aktive Geräte
  - Kompressor-Status (aus Power abgeleitet)

### 2. Predictor (Vorhersage)
- ML-Modell: Vorhersage von Takten
- Input: Aktueller Zustand + Historie
- Output: "Takten wahrscheinlich in X Minuten"
- Trainiert auf historischen Daten aus InfluxDB

### 3. Controller (Steuerung)
- Entscheidet Aktionen basierend auf Vorhersage
- Strategien:
  - **Load Balancing**: Mehr Geräte aktivieren
  - **Temperature Shift**: Solltemperatur anpassen
  - **Fan Control**: Lüfterstufe reduzieren
  - **Preemptive Heating**: Puffer-Raum vorheizen

### 4. Learner (Lernender)
- Bewertet Erfolg der Aktionen
- Passt Strategie-Parameter an
- Reinforcement Learning Ansatz

## Datenfluss

```
1. OBSERVE
   │
   ├── Power: 380W (niedrig, Takt-Gefahr!)
   ├── Kompressor: AN seit 3 min
   ├── Rooms: EG 21.8°C, SZ 22.1°C, AZ aus
   └── Outside: 4°C
   
2. PREDICT
   │
   └── "Takten in 2-4 min wahrscheinlich (85%)"
   
3. DECIDE
   │
   └── Aktion: "Aktiviere AZ mit Soll 20°C, Fan LOW"
   
4. ACT
   │
   └── climate.set_temperature(az, 20)
       climate.set_fan_mode(az, "low")
   
5. LEARN
   │
   ├── Ergebnis nach 10 min: Kein Takten ✓
   └── Update: Diese Aktion bei ähnlichem Zustand = gut
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
- `sensor.hvac_cycling_risk` - Takt-Risiko (0-100%)
- `sensor.hvac_efficiency_score` - Effizienz-Score
- `switch.climatiq_enabled` - An/Aus
- `number.hvac_target_power` - Ziel-Mindestleistung

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

## Metriken für Erfolg

1. **Takt-Reduktion**: Zyklen/Tag sinken um >50%
2. **Komfort**: Temperatur-Abweichung <0.5°C
3. **Effizienz**: kWh/Grad-Tag verbessert sich
4. **Kompressor-Laufzeit**: Längere, stabilere Zyklen
