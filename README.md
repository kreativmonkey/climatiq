# ClimatIQ

**Intelligent Climate Control for Home Assistant - Stability Optimizer**

ClimatIQ prevents power consumption cycling (Takten) in heat pump and air conditioning systems by learning optimal operating parameters and maintaining stable, efficient operation while preserving comfort temperature.

## The Problem

Modern multi-split heat pump and A/C systems often exhibit a problematic behavior pattern:

1. **Stable Phase**: The system runs with steady power consumption (e.g., 400-600W)
2. **Cycling Phase**: Power consumption starts to fluctuate rapidly (e.g., oscillating between 400W and 1500W)
3. **Unpredictable Triggers**: Minor environmental changes (temperature shifts, humidity, wind) can trigger cycling
4. **Manual Control Impossible**: The system dynamics are too complex for manual optimization

### What is "Takten" (Cycling)?

**Not just compressor on/off cycles!** Takten refers to **frequent power consumption fluctuations** even when the compressor remains "on". For example:
- Power oscillates between 600W and 1500W every few minutes
- System never settles into stable operation
- Efficiency drops, comfort suffers, component wear increases

### Real-World Impact

- **Energy waste**: Frequent power swings consume more energy than stable operation
- **Comfort degradation**: Temperature fluctuations and noise
- **Component wear**: Reduced system lifespan
- **Frustration**: Impossible to diagnose and fix manually

## The Solution

ClimatIQ learns from historical data and real-time observations to:

1. **Detect instability early**: Recognize patterns that lead to cycling before it starts
2. **Find stable operating points**: Identify combinations of settings (temperatures, fan speeds, active units) that produce stable power consumption at minimal levels
3. **Adapt proactively**: Adjust system parameters to maintain stability as environmental conditions change
4. **Minimize energy**: Target the lowest stable power consumption that maintains comfort

### Core Principles

- **Stability first**: Smooth, consistent operation beats brief periods of "efficiency"
- **Learn continuously**: System behavior changes with seasons, weather, usage patterns
- **Safety bounds**: Never sacrifice comfort (±1.5°C max deviation from user settings)
- **Explainability**: Every action is logged with reasoning

## Key Features

### Cycling Detection v2
- **Power variance analysis**: Detect fluctuations within "on" states
- **Gradient tracking**: Identify trends before cycling becomes severe
- **Windowed statistics**: Rolling mean, std dev, min/max spread
- **Adaptive thresholds**: No fixed 400W or 1800W limits - learns system-specific stable ranges

### Stability Analyzer
- **Automatic discovery**: Finds stable operating regions from historical data
- **Multi-dimensional clustering**: Considers power, temperatures, active units, fan speeds
- **Minimum energy targeting**: Identifies lowest-power stable states
- **Seasonal adaptation**: Recognizes that stable regions shift with outdoor temperature

### Predictive Controller
- **ML-based forecasting**: Predicts cycling risk before it happens (RandomForest model)
- **Heuristic fallback**: Rule-based decisions when ML unavailable
- **Action strategies**:
  - **Load balancing**: Distribute load across multiple indoor units
  - **Temperature modulation**: Gentle adjustments (±0.5°C) to shift operating point
  - **Fan control**: Reduce or increase fan speeds to stabilize power
  - **Preemptive buffering**: Activate low-priority zones as thermal buffer

### Continuous Learning
- **Feedback loop**: Evaluates action outcomes and adjusts strategies
- **Model retraining**: Daily updates (3:00 AM) with new data
- **Parameter tuning**: Learns optimal timing, magnitude of interventions
- **Future: RL agent**: Reinforcement learning for fully autonomous optimization

## Architecture

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
│              │   ClimatIQ App        │                  │
│              │   (AppDaemon)         │                  │
│              └───────────┬───────────┘                  │
│                          │                              │
└──────────────────────────┼──────────────────────────────┘
                           │
              ┌────────────▼────────────┐
              │    InfluxDB             │
              │  (Historical Data)      │
              │  - Power consumption    │
              │  - Temperatures         │
              │  - Unit states          │
              └─────────────────────────┘
```

### Components

1. **Observer** (`core/observer.py`)
   - Monitors power consumption in real-time
   - Tracks room temperatures, outdoor temperature, unit states
   - Detects cycling patterns (variance, gradients, spread)
   - Maintains sliding window of recent history

2. **Analyzer** (`core/analyzer.py`)
   - Analyzes historical data from InfluxDB
   - Identifies stable operating regions (clustering)
   - Discovers minimum-energy stable points
   - No hardcoded thresholds - learns from data

3. **Predictor** (`core/predictor.py`)
   - ML model (RandomForest) predicts cycling risk
   - Features: power stats, temperatures, time of day, active units, runtime
   - Heuristic fallback for robustness
   - Daily retraining with new data

4. **Controller** (`core/controller.py`)
   - Decides actions based on predictions and observations
   - Three strategy types: Load Balancing, Temperature Modulation, Fan Control
   - Safety limits: max ±1.5°C, min 5-minute action interval
   - Callbacks to Home Assistant service calls

5. **Learner** (future: `core/learner.py`)
   - Reinforcement Learning agent
   - Reward: +1 per minute of stable operation, -10 per cycling event
   - Learns optimal action policies through experience

## Installation

### Requirements

- Python 3.11+
- Home Assistant with climate entities (KNX, MQTT, or any integration)
- InfluxDB 1.x or 2.x (for historical data analysis)
- AppDaemon 4.x (for live control)

### Setup

```bash
# Clone repository
git clone <repo-url>
cd climatiq

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your InfluxDB credentials

# Copy AppDaemon configuration
cp config/apps.yaml.example /path/to/appdaemon/apps/apps.yaml
# Edit with your climate entities

# Copy AppDaemon app
cp climatiq/appdaemon/climatiq_app.py /path/to/appdaemon/apps/
```

### Configuration

Edit `config/apps.yaml` (or your AppDaemon `apps.yaml`):

```yaml
climatiq:
  module: climatiq_app
  class: ClimatIQ
  
  # Indoor units
  indoor_units:
    - entity_id: climate.erdgeschoss
      temp_sensor: sensor.eg_temperatur
      priority: high
    - entity_id: climate.schlafzimmer
      temp_sensor: sensor.sz_temperatur
      priority: medium
    - entity_id: climate.arbeitszimmer
      temp_sensor: sensor.az_temperatur
      priority: low
  
  # Power sensor (critical!)
  power_sensor: sensor.ac_current_energy
  
  # Outdoor temperature
  outdoor_temp: sensor.outdoor_temperature
  
  # InfluxDB connection
  influxdb:
    host: 192.168.10.25
    port: 8086
    database: homeassistant
    username: your_user
    password: your_password
  
  # Comfort settings
  comfort:
    target_temp: 21.0
    tolerance: 0.5
    max_deviation: 1.5
  
  # Learning settings
  learning:
    enabled: true
    model_path: /config/climatiq_model.pkl
    retrain_hour: 3  # Daily retraining at 3:00 AM
```

## Usage

### Initial Training

Before live operation, train the ML model with historical data:

```bash
# Analyze historical patterns (last 7 days recommended)
python -m climatiq.analyze --days 7

# Train prediction model
python -m climatiq.train --days 7 --output models/climatiq_model.pkl
```

### Live Operation

Once configured in AppDaemon, ClimatIQ runs automatically:

1. **Monitoring**: Every 30 seconds, checks power consumption and temperatures
2. **Risk assessment**: Calculates cycling risk using ML + heuristics
3. **Action decision**: If risk >70%, decides intervention strategy
4. **Execution**: Adjusts climate entities via Home Assistant
5. **Learning**: Evaluates outcome, updates model daily

### Home Assistant Entities

ClimatIQ creates the following sensors in Home Assistant:

- `sensor.climatiq_status` - Current state (idle, monitoring, acting, learning)
- `sensor.climatiq_cycling_risk` - Cycling risk percentage (0-100%)
- `sensor.climatiq_power_trend` - Power trend (stable, rising, falling, fluctuating)
- `sensor.climatiq_stability_score` - System stability score (0-100)
- `switch.climatiq_enabled` - Enable/disable automation
- `number.climatiq_min_stable_power` - Learned minimum stable power (W)

### Manual Override

User settings **always** take precedence:
- Manually changing any climate entity pauses ClimatIQ for 30 minutes
- ClimatIQ will never deviate more than ±1.5°C from user-set temperatures
- The `switch.climatiq_enabled` can disable automation entirely

## Success Metrics

### Primary Goals

1. **Cycling reduction**: <5 cycling events per day (vs. baseline 50-100)
2. **Stability improvement**: >80% of operation time in stable power range
3. **Energy minimization**: Lowest stable power consumption point maintained
4. **Comfort preservation**: Temperature deviation <0.5°C from target

### Secondary Goals

1. **Compressor runtime**: Longer, more stable run periods (>30 min avg)
2. **Power spread reduction**: Max-min power spread <300W during stable operation
3. **Intervention efficiency**: <10 control actions per day
4. **Prediction accuracy**: Cycling prediction precision >70%

## Development Roadmap

### ✅ Sprint 1: Foundation (Complete)
- [x] Project structure, dependencies, testing framework
- [x] InfluxDB integration (v1.x and v2.x)
- [x] AppDaemon app skeleton
- [x] Basic observer and controller

### 🔶 Sprint 2: Cycling Detection v2 (In Progress)
- [x] Power variance-based cycling detection
- [x] Adaptive thresholds (no hardcoded limits)
- [ ] Validate with last 5 days of data
- [ ] Unit tests for edge cases
- [ ] Integration test with live data

### 🔶 Sprint 3: Stability Analyzer (In Progress)
- [x] Clustering-based stable region discovery
- [ ] Fix false 1800W minimum (should find 400-600W stable zones)
- [ ] Multi-dimensional stability (power + temperatures + units)
- [ ] Seasonal adaptation logic

### 🟡 Sprint 4: Controller Refinement
- [ ] Action strategies optimized for new cycling definition
- [ ] Gradual intervention (avoid abrupt changes)
- [ ] Night mode (lower temperatures, preemptive buffering)
- [ ] Dashboard sensors (status, risk, stability score)

### 🟡 Sprint 5: ML Predictor
- [ ] Feature engineering for new cycling definition
- [ ] Retrain model with corrected labels
- [ ] Cross-validation, hyperparameter tuning
- [ ] Feature importance analysis

### 🟢 Sprint 6: Reinforcement Learning (Future)
- [ ] RL agent setup (PPO or SAC)
- [ ] Simulation environment
- [ ] Safe exploration (constraint-based)
- [ ] Transfer learning from rule-based to RL

## Project Status

**Current Phase**: Sprint 2 - Cycling Detection v2

**Branch**: `feature/stability-optimizer-v2`

**Recent Changes** (2026-02-17):
- Complete rework of cycling detection logic (variance-based)
- Observer extended with gradient tracking, power spread
- Analyzer refactored to discover minimum stable power points
- Controller adjusted for new stability targets
- Unit tests expanded

**Known Issues**:
- Analyzer still reports 1800W as minimum stable (should be ~400-600W)
- ML model labels need regeneration with new cycling definition
- Dashboard sensors not yet implemented
- Night mode logic missing

**Next Steps**:
1. Validate cycling detection v2 with last 5 days of data
2. Fix analyzer to correctly identify low-power stable zones
3. Retrain ML model with corrected labels
4. Implement dashboard sensors
5. Add night mode logic

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

## License

MIT License - see LICENSE file

## Support

For questions, issues, or feature requests, please open an issue on GitHub.

---

**Note**: This project is under active development. The cycling detection and stability analysis algorithms are being rewritten based on real-world observations. Expect frequent updates to core components.
