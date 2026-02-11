# HVAC Optimizer

Intelligent control system for heat pump / air conditioning units to minimize short-cycling (compressor on/off switching) while maintaining comfort temperature.

## Features

- **Anti-Cycling Logic**: Predicts and prevents compressor short-cycling
- **Multi-Split Support**: Handles systems with multiple indoor units
- **Single-Split Support**: Also works with simple single-unit systems
- **Energy Optimization**: Optional integration with dynamic electricity pricing
- **Home Assistant Integration**: Works via AppDaemon or custom component

## Problem Statement

Modern heat pumps and air conditioning systems in well-insulated buildings often face a mismatch: the system is sized for peak loads (extreme temperatures) but operates mostly at partial load. This leads to:

- **Short-cycling**: Compressor frequently turns on/off
- **Increased energy consumption**: Startup draws more power
- **Wear and tear**: Reduces system lifespan
- **Comfort issues**: Temperature fluctuations

This project uses machine learning to predict when cycling will occur and proactively adjusts system parameters to prevent it.

## Requirements

- Python 3.11+
- InfluxDB (for historical data)
- Home Assistant with climate entities
- AppDaemon (for live control)

## Installation

```bash
# Clone repository
git clone <repo-url>
cd hvac-optimizer

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your credentials
```

## Configuration

See `config/config.example.yaml` for configuration options.

## Usage

### Data Analysis
```bash
python -m hvac_optimizer.analyze
```

### Training
```bash
python -m hvac_optimizer.train
```

### Live Control (AppDaemon)
Copy `appdaemon/apps/hvac_optimizer.py` to your AppDaemon apps folder.

## Project Structure

```
hvac-optimizer/
├── hvac_optimizer/       # Main Python package
│   ├── __init__.py
│   ├── data/             # Data loading & preprocessing
│   ├── models/           # ML models
│   ├── control/          # Control logic
│   └── utils/            # Utilities
├── config/               # Configuration files
├── appdaemon/            # AppDaemon integration
├── tests/                # Unit tests
└── docs/                 # Documentation
```

## License

MIT License - see LICENSE file

## Contributing

Contributions welcome! Please read CONTRIBUTING.md first.
