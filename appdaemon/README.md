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

# RL Training Log
tail -f /config/appdaemon/logs/climatiq_rl.jsonl
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
