# ClimatIQ AppDaemon Installation

## Schnellstart

1. **Dateien kopieren:**
```bash
cp apps/climatiq_controller.py /config/appdaemon/apps/
cp apps/climatiq.yaml /config/appdaemon/apps/
```

2. **Config anpassen:** `/config/appdaemon/apps/climatiq.yaml`
   - Entity-IDs für deine Sensoren/Climate
   - InfluxDB Verbindung (falls vorhanden)

3. **AppDaemon neustarten**

## Automatische Zonen-Erkennung

Der Controller erkennt **automatisch** stabile/instabile Power-Zonen:
- Beim Start: Lädt 30 Tage Historie aus InfluxDB
- Täglich 03:00: Lernt Zonen neu
- Nutzt GMM Clustering (wie in der 90-Tage Analyse)

**Du musst keine Zonen manuell konfigurieren!**

## Logs

```bash
# AppDaemon Log
tail -f /config/appdaemon/logs/appdaemon.log | grep ClimatIQ

# RL Training Log (V3.2: now in appdaemon/logs/)
tail -f /config/appdaemon/logs/climatiq_rl.jsonl

# Zone Cache
cat /config/appdaemon/logs/climatiq_zones_cache.json
```

## Erkannte Zonen prüfen

Nach dem Start siehst du im Log:
```
✓ Zonen erkannt:
  Stabile Zonen: 2
    - 520W (±45W)
    - 1800W (±80W)
  Instabile Zonen: 1
    - 1000W - 1500W
```

## Stabilisierung

Wenn die Power oszilliert (in instabiler Zone), versucht der Controller:

1. **Target senken** bei warmen Räumen (die wärmsten zuerst)
2. **Target erhöhen** bei kalten Räumen (damit sie Idle erreichen)
3. **Abschalten** als letzten Ausweg (HVAC-Mode → off)
4. **Neutral-Room-Anpassung** wenn alle Räume komfortabel sind, aber Power dennoch oszilliert

Der Controller merkt sich den letzten angepassten Raum und wechselt beim nächsten Mal, um nicht immer denselben Raum zu adjustieren.

## Oszillations-Erkennung (V3.2)

Der Controller erkennt Oszillation auf zwei Arten:

1. **Zonen-basiert**: Power liegt in einer instabilen Zone (z.B. 1000-1500W)
2. **Zeitreihen-basiert**: Power variiert stark über Zeit (σ > 100W oder Spread > 200W)

Die Zeitreihen-Erkennung verhindert falsch-positive Meldungen bei konstantem Power-Level.

## Konfiguration (Optional)

In `climatiq.yaml` können zusätzliche Parameter gesetzt werden:

```yaml
rules:
  stability:
    oscillation_std_threshold: 100    # StdDev-Schwelle für Oszillation (W)
    oscillation_spread_threshold: 200  # Spread-Schwelle für Oszillation (W)
    auto_turn_off: true              # Raum abschalten als letzten Ausweg
    max_actions_per_cycle: 2         # Max. Aktionen pro Cycle
```
