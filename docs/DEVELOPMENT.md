# Development Guide

This guide is for developers who want to contribute to ClimatIQ or work on the code.

**If you just want to use ClimatIQ in Home Assistant, see [APPDAEMON_SETUP.md](APPDAEMON_SETUP.md) instead!**

---

## 🛠️ Development Setup

### Prerequisites
- Python 3.11+
- Git
- (Optional) Nix with Flakes enabled

### Clone Repository
```bash
git clone https://github.com/kreativmonkey/climatiq.git
cd climatiq
```

### Setup Environment

**Option A: Nix Flake (Recommended)**
```bash
# Enable Nix Flakes (if not already enabled)
echo "experimental-features = nix-command flakes" >> ~/.config/nix/nix.conf

# Use the development shell
echo "use flake" > .envrc
direnv allow

# Or manually:
nix develop
```

**Option B: Python venv**
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

pip install -r requirements.txt
```

---

## 📁 Project Structure

```
climatiq/
├── appdaemon/apps/          # AppDaemon integration (what users install)
│   ├── climatiq_controller.py
│   └── climatiq.yaml
│
├── climatiq/                # Python package (development & testing)
│   ├── __init__.py
│   ├── core/
│   │   ├── controller.py        # Core controller logic
│   │   ├── entities.py          # Data models
│   │   └── observer.py          # System observer
│   ├── data/
│   │   └── influx_v1_client.py  # InfluxDB V1 client
│   ├── models/                  # ML models (future)
│   └── analysis/                # Analysis tools (future)
│
├── tests/                   # Unit tests
│   └── unit/
│       ├── test_controller.py
│       ├── test_analyzer.py
│       ├── test_predictor.py
│       └── ...
│
├── scripts/                 # Analysis & utility scripts
│   ├── auto_stable_zones.py
│   ├── analyze_live_data.py
│   └── ...
│
├── docs/                    # Documentation
│   ├── APPDAEMON_SETUP.md       # User installation guide
│   ├── CONTROLLER.md            # Controller documentation
│   ├── MULTI_DEVICE.md          # Multi-device feature docs
│   └── DEVELOPMENT.md           # This file
│
├── data/                    # Research artifacts & analysis results
│   └── (gitignored)
│
├── models/                  # Trained ML models (future)
├── config/                  # Example configs
├── flake.nix               # Nix Flake definition
├── requirements.txt        # Python dependencies
├── pyproject.toml         # Project metadata & tool config
└── README.md              # Project overview
```

---

## 🧪 Testing

### Run All Tests
```bash
pytest tests/ -v
```

### Run Specific Test File
```bash
pytest tests/unit/test_controller.py -v
```

### Run with Coverage
```bash
pytest tests/ --cov=climatiq --cov-report=term
```

### Watch Mode (auto-run on changes)
```bash
pytest-watch tests/
```

---

## 🎨 Code Quality

### Formatting (Black)
```bash
# Check formatting
black --check .

# Auto-format
black .
```

### Linting (Ruff)
```bash
# Check linting
ruff check .

# Auto-fix
ruff check --fix .
```

### Type Checking (Mypy - optional)
```bash
mypy climatiq/
```

---

## 🔄 Git Workflow

### Branch Naming
- `feat/feature-name` - New features
- `fix/bug-description` - Bug fixes
- `docs/what-changed` - Documentation
- `test/what-tested` - Test improvements

### Commit Messages
Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add multi-device support
fix: correct emergency cooldown logic
docs: improve installation guide
test: add edge case tests for cooldown
```

### Pull Request Process
1. Create branch from `main`
2. Implement changes
3. Run tests + linting
4. Update documentation
5. Push branch
6. Create PR with description
7. Wait for review
8. Address feedback
9. Merge!

---

## 📊 Analysis Scripts

### Auto Stable Zones
```bash
python scripts/auto_stable_zones.py
```

Detects stable/unstable power zones from InfluxDB data using GMM clustering.

### Live Data Analysis
```bash
python scripts/analyze_live_data.py --days 7
```

Analyzes recent controller performance (cycling rate, power distribution, etc.).

---

## 🐛 Debugging

### AppDaemon Integration Testing

**Option 1: Mock AppDaemon (unit tests)**
```python
# See tests/unit/test_controller_v2.py for examples
```

**Option 2: Real Home Assistant**
1. Copy `appdaemon/apps/climatiq_controller.py` to `/config/appdaemon/apps/`
2. Add debug logging in code
3. Restart AppDaemon
4. Watch logs: `tail -f /config/appdaemon/appdaemon.log`

### Common Issues

**Import errors:**
- Check `sys.path` in tests
- Verify `__init__.py` files exist

**Test failures:**
- Check if using correct Python version (3.11+)
- Clear pytest cache: `rm -rf .pytest_cache`

**Black formatting:**
- Run `black .` before committing

---

## 📚 Documentation

### Update Documentation When:
- Adding new features
- Changing configuration options
- Fixing bugs that affect behavior
- Adding new analysis scripts

### Documentation Files:
- `README.md` - Project overview & quick start
- `docs/APPDAEMON_SETUP.md` - User installation guide (German)
- `docs/CONTROLLER.md` - Controller documentation (English)
- `docs/MULTI_DEVICE.md` - Multi-device feature docs (English)
- `docs/DEVELOPMENT.md` - This file (English)

---

## 🤝 Contributing

1. Fork the repository
2. Create feature branch
3. Make changes (follow code quality guidelines!)
4. Add tests
5. Update documentation
6. Create Pull Request

**Code Review Criteria:**
- ✅ All tests pass
- ✅ Black + Ruff compliant
- ✅ Documentation updated
- ✅ All code in English (comments, variables)
- ✅ PR description complete

---

## 📝 Release Process

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md`
3. Create git tag: `git tag v3.x.x`
4. Push tag: `git push origin v3.x.x`
5. GitHub Actions creates release automatically

---

**Questions?** Open an issue on GitHub!
