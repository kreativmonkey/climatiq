# ClimatIQ - Development Plan

> Branch: `feature/stability-optimizer-v2`  
> Started: 2026-02-17  
> Status: Sprint 2 - Cycling Detection v2

## Project Vision

Build a self-learning system that prevents power consumption cycling in multi-split heat pump/AC systems by:
1. Detecting instability patterns early (power fluctuations, not just on/off)
2. Learning stable operating points at minimum energy consumption
3. Proactively adjusting system parameters to maintain stability
4. Adapting to environmental changes automatically

## Core Problem Statement (Revised 2026-02-17)

### Observed Behavior
1. **Stable phase**: System operates with consistent power consumption (e.g., 400-600W steady)
2. **Transition**: Minor environmental changes (temperature shift, humidity, wind) trigger instability
3. **Cycling phase**: Power consumption fluctuates rapidly (e.g., 400W ↔ 1500W, cycling every 2-5 minutes)
4. **Unpredictability**: No obvious pattern, manual intervention ineffective

### What We Got Wrong (v1)
- **Mistake**: Defined "Takten" as compressor on/off cycles (crossing 200W/100W thresholds)
- **Reality**: Takten = power fluctuations **within** the "on" state, not just binary on/off
- **Consequence**: Old detection missed 90% of actual cycling events
- **Analyzer flaw**: Always reported 1800W as minimum stable power (wrong!)

### New Understanding (v2)
- **Cycling definition**: Rapid power variance (std dev, gradient, spread) within operational state
- **Stability goal**: Find lowest power consumption with minimal variance, not lowest power period
- **Threshold**: Learn system-specific stable zones (likely 400-600W for this system), not hardcoded 200W or 1800W
- **Target**: Minimize energy **while maintaining stability**, not minimize energy at any cost

## Sprint Breakdown

### Sprint 1: Foundation ✅ COMPLETE (2026-02-11)

**Goal**: Establish project infrastructure, data access, basic architecture

**Deliverables**:
- [x] Project structure (`pyproject.toml`, `requirements.txt`, testing setup)
- [x] InfluxDB integration (v1.x InfluxQL + v2.x Flux)
- [x] AppDaemon app skeleton (`climatiq_app.py`)
- [x] Core components: Observer, Analyzer, Predictor, Controller (v1 logic)
- [x] Unit tests (37 tests, all passing)
- [x] CI pipeline (GitHub Actions)
- [x] Documentation (`README.md`, `CONCEPT.md`, `CONTRIBUTING.md`)

**Status**: ✅ Complete  
**Duration**: ~2 days  
**Commit**: `a9f7f06` (Feb 11, 2026)

---

### Sprint 2: Cycling Detection v2 🔶 IN PROGRESS (2026-02-17)

**Goal**: Replace on/off cycle detection with power variance-based cycling detection

#### Tasks

**2.1 Cycling Detection Algorithm** ✅ DONE
- [x] Implement power variance tracking (rolling std dev)
- [x] Add gradient analysis (power trend: rising, falling, stable)
- [x] Implement power spread metric (max - min in window)
- [x] Remove hardcoded thresholds (200W/100W)
- [x] Adaptive windowing (30s to 5min)

**2.2 Observer Enhancements** ✅ DONE
- [x] Extended `observe()` to track:
  - `power_mean`, `power_std`, `power_min`, `power_max`, `power_gradient`
  - `cycling_risk` (0-100 based on variance)
  - `power_spread` (max - min)
- [x] Sliding window history (configurable size)
- [x] Real-time cycling risk calculation

**2.3 Unit Tests** ✅ DONE
- [x] Test variance detection with synthetic data
- [x] Test gradient calculation accuracy
- [x] Test edge cases (empty data, single point, flat line)
- [x] Test adaptive thresholds

**2.4 Data Validation** ⏳ IN PROGRESS
- [ ] Pull last 5 days of data from InfluxDB
- [ ] Identify known stable periods (manual annotation)
- [ ] Identify known cycling periods
- [ ] Run new detector on historical data
- [ ] Validate: Does it correctly flag cycling episodes?
- [ ] Tune sensitivity parameters if needed

**Status**: 🔶 80% complete (algorithm done, validation pending)  
**ETA**: 2026-02-18 (1 day)

---

### Sprint 3: Stability Analyzer Fix 🟡 PLANNED

**Goal**: Correctly identify stable operating regions, especially at low power

#### Current Problem
- Analyzer uses clustering (DBSCAN) to find stable regions
- Currently reports **1800W** as minimum stable power
- Reality: System can be stable at **400-600W**
- Hypothesis: Algorithm weights "duration" too heavily, ignores variance

#### Tasks

**3.1 Debug Current Analyzer** 
- [ ] Log all clustering inputs (features, eps, min_samples)
- [ ] Visualize clusters (scatter plot: power vs. std dev, colored by cluster)
- [ ] Identify why low-power stable zones are ignored

**3.2 Revise Clustering Logic**
- [ ] Add `power_std` as primary feature (stability = low variance)
- [ ] Use `power_mean` as secondary feature (efficiency = low mean)
- [ ] Experiment with DBSCAN parameters (eps, min_samples)
- [ ] Consider alternative: Gaussian Mixture Models

**3.3 Multi-Dimensional Stability**
- [ ] Include temperature features (indoor/outdoor)
- [ ] Include active_units count
- [ ] Include fan_mode (if available)
- [ ] Result: Stability zones = (power, temp, units, fan) combinations

**3.4 Validation**
- [ ] Test with last 5 days of data
- [ ] Manually verify identified stable zones
- [ ] Confirm: Does analyzer now find 400-600W stable zones?

**3.5 Integration**
- [ ] Update Controller to use new stability zones
- [ ] Update Predictor features to include stability score

**Status**: 🟡 Not started  
**ETA**: 2026-02-19–20 (2 days)  
**Dependencies**: Sprint 2.4 (need validated historical data)

---

### Sprint 4: Controller Refinement 🟡 PLANNED

**Goal**: Optimize control strategies for new stability definition

#### Tasks

**4.1 Action Strategy Updates**
- [ ] **Load Balancing**: Bias toward configurations in known stable zones
- [ ] **Temperature Modulation**: Use smaller steps (±0.3°C instead of ±0.5°C)
- [ ] **Fan Control**: Avoid abrupt changes (gradual ramp)
- [ ] **Preemptive Buffering**: Activate buffer zones before cycling risk peaks

**4.2 Night Mode** ⭐ NEW
- [ ] Define night hours (23:00–07:00, configurable)
- [ ] Strategy: Preemptively activate buffer zones at lower temperatures
- [ ] Logic: Better to run 2+ units at 19°C than 1 unit cycling at 21°C
- [ ] Gradual transition (ramp down/up temperatures)

**4.3 Gradual Intervention**
- [ ] Implement multi-step actions (don't jump from 1 to 3 units)
- [ ] Wait-and-see: After action, observe 10min before next intervention
- [ ] Hysteresis: Don't reverse action unless significant change

**4.4 Safety Enhancements**
- [ ] Confirm: Never exceed ±1.5°C user deviation
- [ ] Add: Max actions per hour limit (e.g., 6)
- [ ] Add: "Panic mode" if cycling persists despite interventions (notify user)

**4.5 Dashboard Sensors** ⭐ NEW
- [ ] `sensor.climatiq_status` (idle, monitoring, acting, learning)
- [ ] `sensor.climatiq_cycling_risk` (0-100%)
- [ ] `sensor.climatiq_power_trend` (stable, rising, falling, fluctuating)
- [ ] `sensor.climatiq_stability_score` (0-100, based on variance)
- [ ] `sensor.climatiq_min_stable_power` (learned value, e.g., 450W)
- [ ] `sensor.climatiq_last_action` (description of last intervention)

**Status**: 🟡 Not started  
**ETA**: 2026-02-21–23 (3 days)  
**Dependencies**: Sprint 3 (need corrected stability zones)

---

### Sprint 5: ML Predictor Update 🟡 PLANNED

**Goal**: Retrain prediction model with corrected cycling labels

#### Current Problem
- Model trained with old cycling definition (on/off cycles)
- Labels are wrong: many real cycling events labeled as "stable"
- Features may be suboptimal (missing variance metrics)

#### Tasks

**5.1 Feature Engineering**
- [ ] Add new features:
  - `power_std` (last 5min, 10min, 30min)
  - `power_gradient` (W/min)
  - `power_spread` (max - min)
  - `cycling_episodes_last_hour` (historical)
- [ ] Review existing features (keep relevant, drop redundant)
- [ ] Feature importance analysis (RandomForest built-in)

**5.2 Label Regeneration**
- [ ] Pull 30 days of data (to have sufficient cycling examples)
- [ ] Apply new cycling detector (Sprint 2) to generate labels
- [ ] Manual spot-check: Verify labels are correct
- [ ] Balance dataset (downsample "stable" if too imbalanced)

**5.3 Model Training**
- [ ] Train RandomForest with new features + labels
- [ ] Cross-validation (5-fold)
- [ ] Hyperparameter tuning (GridSearchCV: n_estimators, max_depth, min_samples_split)
- [ ] Evaluate: Precision, recall, F1, confusion matrix

**5.4 Integration**
- [ ] Update `predictor.py:prepare_features()` with new feature set
- [ ] Update `predictor.py:train()` with new dataset
- [ ] Test: Does new model improve cycling prediction?

**5.5 Continuous Learning**
- [ ] Confirm daily retraining at 3:00 AM works
- [ ] Add: Rolling window training (last 30 days only, avoid concept drift)
- [ ] Add: Model versioning (save timestamp, metrics)

**Status**: 🟡 Not started  
**ETA**: 2026-02-24–26 (3 days)  
**Dependencies**: Sprint 2 (new cycling detector), Sprint 3 (stability zones)

---

### Sprint 6: Reinforcement Learning Agent 🟢 FUTURE

**Goal**: Autonomous optimization via RL (exploratory, low priority)

#### Rationale
- Current approach: Rule-based + supervised ML
- RL could learn optimal policies through trial-and-error
- Risk: Requires extensive simulation + safety constraints
- Benefit: Could discover non-obvious strategies

#### Tasks (Tentative)

**6.1 Simulation Environment**
- [ ] Create simplified system model (physics-based or data-driven)
- [ ] State space: power, temperatures, units, outdoor temp, time
- [ ] Action space: unit on/off, temperature ±0.5°C, fan low/med/high
- [ ] Reward: +1 per minute stable, -10 per cycling event, -0.1 per action

**6.2 RL Algorithm Selection**
- [ ] Research: PPO, SAC, DQN (compare pros/cons)
- [ ] Implement: Start with PPO (stable, well-documented)
- [ ] Library: Stable-Baselines3

**6.3 Safe Exploration**
- [ ] Constraint: Never exceed ±1.5°C user deviation
- [ ] Constraint: Max 6 actions per hour
- [ ] Approach: Constrained RL or reward shaping

**6.4 Training**
- [ ] Train in simulation (100k–1M steps)
- [ ] Evaluate: Compare to rule-based baseline
- [ ] Transfer: Gradual deployment in real system (with human oversight)

**6.5 Monitoring**
- [ ] Log all RL decisions + outcomes
- [ ] A/B test: RL vs. rule-based (weekly comparison)
- [ ] Rollback: Easy switch back to rules if RL underperforms

**Status**: 🟢 Future work (not prioritized)  
**ETA**: 2026-03+ (4+ weeks, if pursued)  
**Dependencies**: Sprints 2-5 complete, system stable, user buy-in

---

## Milestones

### Milestone 1: Cycling Detection Validated ⏳ (Sprint 2 complete)
- New detector correctly identifies cycling in historical data
- False positive rate <10%
- False negative rate <5%

### Milestone 2: Stable Zones Identified ⏳ (Sprint 3 complete)
- Analyzer finds low-power stable zones (e.g., 400-600W)
- Validation: Manual review confirms zones match operator observations
- Controller uses zones to guide actions

### Milestone 3: Live Deployment 🎯 (Sprint 4 complete)
- AppDaemon app running in production
- Dashboard sensors visible in Home Assistant
- Reduced cycling events (target: <10/day vs. baseline 50-100/day)

### Milestone 4: ML Model Deployed 🎯 (Sprint 5 complete)
- Predictor trained with correct labels, deployed
- Cycling prediction accuracy >70% precision
- Daily retraining functioning

### Milestone 5: RL Pilot 🚀 (Sprint 6 complete, optional)
- RL agent trained in simulation
- Pilot deployment with monitoring
- Decision: Continue RL or stick with rule-based

---

## Risk Management

### Technical Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Analyzer still can't find low-power stable zones | High | Manual clustering analysis, try GMM instead of DBSCAN |
| New cycling detector too sensitive (false positives) | Medium | Tune thresholds, add debouncing logic |
| ML model accuracy doesn't improve | Medium | Fallback to rule-based, accept reduced prediction |
| InfluxDB data incomplete/corrupted | High | Validate data quality first, handle gaps gracefully |
| System too complex for RL | Low | Stick with rule-based + supervised ML |

### Operational Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| User discomfort (temperature deviations) | High | Strict safety bounds (±1.5°C), easy override |
| System instability worsens | High | Kill switch (`switch.climatiq_enabled`), monitoring alerts |
| AppDaemon crashes/restarts | Medium | Stateless design, fast recovery |
| Power outage during critical action | Low | Home Assistant handles resume, ClimatIQ re-initializes |

---

## Success Metrics (Revisited)

### Primary Metrics (Must Achieve)

1. **Cycling Reduction**: <10 cycling events/day (baseline: 50-100/day) = 90% reduction
2. **Stability**: >80% of operation time with power std dev <50W
3. **Comfort**: Temperature deviation <0.5°C RMS from user target
4. **Minimum Energy**: 50%+ of stable time at <600W power consumption

### Secondary Metrics (Nice to Have)

1. **Compressor Runtime**: Average cycle length >30 minutes (baseline: ~3 min)
2. **Intervention Efficiency**: <8 control actions/day
3. **Prediction Accuracy**: Cycling risk prediction F1 score >0.70
4. **User Satisfaction**: Manual overrides <2/week (implicit feedback)

### Data Collection

- **InfluxDB**: Log all observations (power, temps, actions, outcomes) every 30s
- **Memory**: Store daily summary (cycling events, actions, metrics) in `memory/YYYY-MM-DD.md`
- **Model**: Save training metrics (accuracy, features, params) with each retrain

---

## Next Actions (Immediate)

1. **Today (2026-02-17)**:
   - [x] Create branch `feature/stability-optimizer-v2`
   - [x] Update README.md with new problem definition
   - [x] Create this PLAN.md
   - [ ] Pull last 5 days of data from InfluxDB
   - [ ] Manually identify 3-5 stable periods + 3-5 cycling periods
   - [ ] Run new cycling detector, validate accuracy

2. **Tomorrow (2026-02-18)**:
   - [ ] Fix any detector issues found in validation
   - [ ] Unit test edge cases
   - [ ] Start Sprint 3: Debug analyzer clustering
   - [ ] Create visualization script (power vs. std dev scatter plot)

3. **This Week (2026-02-19–23)**:
   - [ ] Complete Sprint 3 (analyzer fix)
   - [ ] Complete Sprint 4 (controller refinement)
   - [ ] Deploy to AppDaemon for live testing
   - [ ] Monitor first 48h of operation

---

## Open Questions

1. **Optimal window size for variance calculation?**  
   Current: 5 minutes. May need tuning based on system response time.

2. **How many stable zones exist?**  
   Hypothesis: 3-5 zones (e.g., 400-600W low, 800-1000W medium, 1200-1500W high).

3. **Can we predict cycling 10 minutes in advance?**  
   Goal of ML model. May need to accept shorter horizon (5 min?).

4. **Is RL worth the complexity?**  
   Decision deferred to Milestone 4. Evaluate if rule-based + ML is "good enough".

5. **Dynamic pricing integration?**  
   Future enhancement. Low priority until core stability achieved.

---

_Last updated: 2026-02-17 by Diyon_
