"""Detect compressor cycling and fluctuation patterns from power data."""

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class CycleEvent:
    """A single compressor cycle (on -> off)."""

    start_time: pd.Timestamp
    end_time: pd.Timestamp
    duration_minutes: float
    peak_power: float
    avg_power: float

    @property
    def is_short_cycle(self) -> bool:
        """Cycles under 10 minutes are considered short/problematic."""
        return self.duration_minutes < 10


@dataclass
class FluctuationEvent:
    """A period of high power instability/fluctuation."""

    start_time: pd.Timestamp
    end_time: pd.Timestamp
    duration_minutes: float
    instability_score: float
    amplitude_watts: float
    frequency_hz: float  # Changes per minute
    avg_power: float


@dataclass
class PowerJump:
    """A significant jump in power consumption."""

    timestamp: pd.Timestamp
    power_before: float
    power_after: float
    delta_watts: float
    delta_pct: float


class CyclingDetector:
    """Detect compressor cycling and power fluctuations from consumption data.

    This detector identifies not just on/off cycles, but also 'micro-cycling' or
    fluctuations where the power remains above the 'on' threshold but varies
    significantly, indicating instability.
    """

    def __init__(
        self,
        power_on_threshold: float = 200.0,
        power_off_threshold: float = 100.0,
        fluctuation_threshold_watts: float = 300.0,
        fluctuation_threshold_pct: float = 40.0,
        window_minutes: int = 10,
        instability_threshold: float = 0.5,
    ):
        """Initialize the CyclingDetector.

        Args:
            power_on_threshold: Watts - compressor is "on" above this.
            power_off_threshold: Watts - compressor is "off" below this.
            fluctuation_threshold_watts: Absolute change to consider a fluctuation.
            fluctuation_threshold_pct: Relative change (%) to consider a fluctuation.
            window_minutes: Rolling window size for instability analysis.
            instability_threshold: Score above which a period is 'fluctuating'.
        """
        self.power_on_threshold = power_on_threshold
        self.power_off_threshold = power_off_threshold
        self.fluctuation_threshold_watts = fluctuation_threshold_watts
        self.fluctuation_threshold_pct = fluctuation_threshold_pct
        self.window_minutes = window_minutes
        self.instability_threshold = instability_threshold

    def detect_cycles(self, power_series: pd.Series) -> list[CycleEvent]:
        """Detect classic on/off cycles using hysteresis.

        Args:
            power_series: Series with datetime index and power values in Watts.

        Returns:
            List of CycleEvent objects.
        """
        if power_series.empty or len(power_series) < 2:
            return []

        # Determine compressor state using hysteresis
        states = []
        current_state = power_series.iloc[0] > self.power_on_threshold

        for power in power_series:
            if current_state:
                if power < self.power_off_threshold:
                    current_state = False
            else:
                if power > self.power_on_threshold:
                    current_state = True
            states.append(current_state)

        states_series = pd.Series(states, index=power_series.index)
        state_changes = states_series.astype(int).diff().fillna(0)

        on_times = state_changes[state_changes == 1].index
        off_times = state_changes[state_changes == -1].index

        cycles = []
        for on_time in on_times:
            # Find the first off_time after this on_time
            future_offs = off_times[off_times > on_time]
            if not future_offs.empty:
                off_time = future_offs[0]
                cycle_data = power_series[on_time:off_time]

                duration = (off_time - on_time).total_seconds() / 60.0
                cycles.append(
                    CycleEvent(
                        start_time=on_time,
                        end_time=off_time,
                        duration_minutes=duration,
                        peak_power=float(cycle_data.max()),
                        avg_power=float(cycle_data.mean()),
                    )
                )

        return cycles

    def calculate_instability_score(self, power_series: pd.Series) -> pd.Series:
        """Calculate a rolling instability score (0.0 to 1.0).

        The score is based on:
        1. Normalized Standard Deviation
        2. Relative Amplitude (max-min / mean)
        3. Direction Change Frequency

        Args:
            power_series: Power consumption data.

        Returns:
            Series of instability scores.
        """
        if power_series.empty:
            return pd.Series()

        window = f"{self.window_minutes}min"

        # 1. Rolling Standard Deviation (normalized by rolling mean)
        rolling_mean = power_series.rolling(window).mean()
        rolling_std = power_series.rolling(window).std()
        std_score = (rolling_std / rolling_mean).fillna(0)

        # 2. Rolling Amplitude (relative)
        rolling_min = power_series.rolling(window).min()
        rolling_max = power_series.rolling(window).max()
        amp_score = ((rolling_max - rolling_min) / rolling_mean).fillna(0)

        # 3. Frequency of direction changes
        diffs = power_series.diff().fillna(0)
        direction_changes = (np.sign(diffs).diff().fillna(0) != 0).astype(int)
        freq_score = direction_changes.rolling(window).mean().fillna(0)

        # Combine scores (weighted average, capped at 1.0)
        # Weights: 40% StdDev, 40% Amplitude, 20% Frequency
        combined = (std_score * 0.4) + (amp_score * 0.4) + (freq_score * 2.0)
        return combined.clip(0.0, 1.0)

    def detect_fluctuations(self, power_series: pd.Series) -> list[FluctuationEvent]:
        """Detect periods of significant power fluctuations.

        Args:
            power_series: Power consumption data.

        Returns:
            List of FluctuationEvent objects.
        """
        scores = self.calculate_instability_score(power_series)
        if scores.empty:
            return []

        is_unstable = scores > self.instability_threshold

        # Find contiguous periods of instability
        change = is_unstable.astype(int).diff().fillna(0)
        starts = change[change == 1].index
        ends = change[change == -1].index

        # Handle edge cases (starting unstable or ending unstable)
        if is_unstable.iloc[0]:
            starts = starts.insert(0, is_unstable.index[0])
        if is_unstable.iloc[-1]:
            ends = ends.append(pd.Index([is_unstable.index[-1]]))

        events = []
        for start, end in zip(starts, ends):
            period_data = power_series[start:end]
            period_scores = scores[start:end]

            if len(period_data) < 2:
                continue

            duration = (end - start).total_seconds() / 60.0
            diffs = period_data.diff().fillna(0)
            direction_changes = (np.sign(diffs).diff().fillna(0) != 0).astype(int).sum()

            events.append(
                FluctuationEvent(
                    start_time=start,
                    end_time=end,
                    duration_minutes=duration,
                    instability_score=float(period_scores.mean()),
                    amplitude_watts=float(period_data.max() - period_data.min()),
                    frequency_hz=direction_changes / (duration if duration > 0 else 1),
                    avg_power=float(period_data.mean()),
                )
            )

        return events

    def detect_power_jumps(
        self, power_series: pd.Series
    ) -> list[tuple[pd.Timestamp, float]]:
        """Detect rapid jumps in power consumption.

        Backward-compatible return type for unit tests: list of (timestamp, delta_watts).

        Args:
            power_series: Power consumption data.

        Returns:
            List of (timestamp, delta_watts) tuples.
        """
        if len(power_series) < 2:
            return []

        jumps: list[tuple[pd.Timestamp, float]] = []
        for i in range(1, len(power_series)):
            delta = float(power_series.iloc[i] - power_series.iloc[i - 1])
            prev_val = float(power_series.iloc[i - 1])

            abs_jump = abs(delta) >= self.fluctuation_threshold_watts
            rel_jump = False
            if prev_val > 0:
                rel_jump = (abs(delta) / prev_val) * 100 >= self.fluctuation_threshold_pct

            if abs_jump or rel_jump:
                jumps.append((power_series.index[i], delta))

        return jumps

    def analyze_cycling(self, power_series: pd.Series) -> dict[str, Any]:
        """Comprehensive analysis of cycling and fluctuations.

        Maintains backward compatibility by returning a dict.

        Returns:
            Dictionary containing cycles, fluctuations, jumps, and statistics.
        """
        cycles = self.detect_cycles(power_series)
        fluctuations = self.detect_fluctuations(power_series)
        jumps = self.detect_power_jumps(power_series)

        if power_series.empty:
            return {
                "cycles": [],
                "fluctuations": [],
                "jumps": [],
                "instability_score": 0.0,
                "total_cycles": 0,
                "short_cycle_count": 0,
            }

        short_cycles = [c for c in cycles if c.is_short_cycle]
        durations = [c.duration_minutes for c in cycles]
        instability_scores = self.calculate_instability_score(power_series)

        time_span_hours = (
            power_series.index[-1] - power_series.index[0]
        ).total_seconds() / 3600

        return {
            "cycles": cycles,
            "fluctuations": fluctuations,
            "jumps": jumps,
            "short_cycles": short_cycles,
            "total_cycles": len(cycles),
            "short_cycle_count": len(short_cycles),
            "avg_cycle_duration": np.mean(durations) if durations else None,
            "cycles_per_hour": len(cycles) / time_span_hours if time_span_hours > 0 else 0,
            "avg_instability": float(instability_scores.mean()),
            "max_instability": float(instability_scores.max()),
            "fluctuation_count": len(fluctuations),
            "jump_count": len(jumps),
            "time_span_hours": time_span_hours,
        }

    def find_cycling_periods(
        self,
        power_series: pd.Series,
        window: str = "1H",
        threshold_cycles_per_hour: float = 4,
    ) -> pd.DataFrame:
        """Find time periods with excessive cycling.

        Args:
            power_series: Power data
            window: Rolling window size
            threshold_cycles_per_hour: Cycles/hour above this = problematic

        Returns:
            DataFrame with cycling intensity over time
        """
        cycles = self.detect_cycles(power_series)

        if not cycles:
            return pd.DataFrame(columns=["cycles_per_hour", "is_problematic"])

        cycle_times = pd.Series(1, index=[c.start_time for c in cycles])
        cycle_counts = cycle_times.resample(window).sum().fillna(0)
        window_hours = pd.Timedelta(window).total_seconds() / 3600
        cycles_per_hour = cycle_counts / window_hours

        return pd.DataFrame(
            {
                "cycles_per_hour": cycles_per_hour,
                "is_problematic": cycles_per_hour > threshold_cycles_per_hour,
            }
        )
