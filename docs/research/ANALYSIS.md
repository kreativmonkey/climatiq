# Research & Analysis Documentation

This directory contains real-world analysis artifacts from the ClimatIQ development process, documenting the journey from initial problem identification to the final ML-based solution.

---

## Sprint 3.2: Machine Learning Analysis Evolution

### Context
The goal was to predict **instability** (compressor short-cycling) in a heat pump system using historical data from InfluxDB. Through three iterations, we refined our approach from symptom-based features to **causal features only**.

---

## V1: Initial ML Analysis (Symptom-based)

**File:** `sprint3_2_ml_analysis.png`

**Approach:** Random Forest classifier with features including:
- Power level
- Room temperature deltas (symptom!)
- Outdoor temperature
- Time of day

**Result:** 91.6% accuracy

**Problem:** High accuracy was misleading - we were using **symptoms as features** to predict **symptom-based labels**. This is circular reasoning!

**Key Insight:** _"High accuracy means nothing with circular reasoning - always distinguish CAUSE vs EFFECT."_

---

## V2: GMM Clustering (Zone Discovery)

**File:** `sprint3_2_v2_gmm.png`

**Approach:** Switched to **Gaussian Mixture Model (GMM)** clustering to automatically discover stable and unstable power zones from 30 days of historical data.

**Discovery:**
- **Stable Zones:**
  - ~519W (moderate outdoor temps)
  - ~1528W (cold outdoor temps)
- **Unstable Zone:** 1000-1500W (high cycling risk)

**Significance:** The system self-learns what "stable" means without manual thresholds. This forms the foundation for the rule-based controller.

**Script:** `scripts/auto_stable_zones.py`

---

## V3: Causal Feature Analysis

**File:** `sprint3_2_v3_causal.png`

**Approach:** Re-trained Random Forest using **causal features only**:
- Outdoor temperature
- Time of day
- Historical power trends
- **Excluded:** Room deltas (symptoms)

**Result:** 91.6% accuracy maintained, but now with **interpretable, actionable features**

**Feature Importance (Causal):**
| Feature            | Importance |
|--------------------|------------|
| power_level        | 19.7%      |
| delta_eg           | 9.5%       |
| delta_kz_abs       | 7.6%       |
| outdoor_temp       | 7.4%       |

**File:** `feature_importance_causal.csv`

---

## Stability Analysis

### Full Stability Analysis

**File:** `stability_analysis_complete.png`

Comprehensive view of system behavior over time:
- Power consumption patterns
- Stable vs unstable zone occupancy
- Correlation with outdoor temperature

### Transition Analysis

**Files:**
- `stability_transition_analysis.png`
- `transition_analysis_deep.png`

Deep dive into **zone transitions** - when and why the system moves between stable/unstable states.

**Key Findings:**
- Morning hours (8-18h) show higher instability
- Outdoor temp < -5°C triggers more cycling
- Total room deviation > 5K is a strong instability signal

---

## Cycling Detection

**Files:**
- `cycling_analysis.png`
- `cycling_analysis_24h.png`

Visual representation of compressor cycling patterns:
- Short-cycle detection (< 5 min on/off cycles)
- Frequency analysis over 24h windows
- Correlation with power zone and outdoor conditions

---

## Automatic Zone Detection

**File:** `auto_stable_zones.png`

Output from the GMM-based automatic zone detection algorithm. Shows:
- Histogram of power consumption distribution
- Identified clusters (stable/unstable zones)
- Cluster means and boundaries

**Config Output:** `stable_zones_config.json`

Example:
```json
{
  "stable_zones": [
    {"min": 400, "max": 650, "mean": 519},
    {"min": 1400, "max": 1700, "mean": 1528}
  ],
  "unstable_zones": [
    {"min": 1000, "max": 1500}
  ]
}
```

This configuration is automatically generated daily at 03:00 and used by the rule-based controller.

---

## Transition Correlation

**File:** `transition_correlation.png`

Correlation matrix showing relationships between:
- Power level
- Room temperature deltas
- Outdoor temperature
- Zone transitions

Helps identify which factors **cause** instability vs which are **effects**.

---

## Power Data Exports

Historical power consumption data used for training and validation:
- `power_30days.csv` - 30-day training dataset
- `power_last_5days.csv` - Recent validation data

**Note:** These CSV files are tracked here as research documentation but excluded from future commits via `.gitignore`.

---

## Key Learnings

1. **Causal Features Only**: Never use symptoms as features for symptom-based labels
2. **Self-Learning Systems**: GMM clustering enables automatic zone discovery without manual thresholds
3. **Stability > Efficiency**: Preventing cycling is more important than hitting exact target temperatures
4. **Multiple Stable Zones**: Systems can have multiple stable operating points depending on external conditions (outdoor temp)

---

## Future Work

- **Reinforcement Learning**: Use logged State-Action-Reward data (from `climatiq_rl.jsonl`) to train an RL agent
- **Adaptive Thresholds**: Dynamic zone boundaries based on seasonal patterns
- **Multi-Zone Optimization**: Coordinate multiple heat pumps in larger buildings

---

**Generated:** 2026-02-20  
**Project:** [ClimatIQ](https://github.com/kreativmonkey/climatiq)  
**Version:** v3.0.0
