"""Detect compressor cycling patterns from power data."""

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


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


class CyclingDetector:
    """Detect compressor cycling from power consumption data."""

    def __init__(
        self,
        power_on_threshold: float = 200,  # Watts - compressor is "on" above this
        power_off_threshold: float = 100,  # Watts - compressor is "off" below this
        min_state_duration: int = 30,  # Seconds - ignore transients shorter than this
    ):
        self.power_on_threshold = power_on_threshold
        self.power_off_threshold = power_off_threshold
        self.min_state_duration = min_state_duration

    def detect_cycles(self, power_series: pd.Series) -> list[CycleEvent]:
        """Detect on/off cycles from power consumption series.

        Args:
            power_series: Series with datetime index and power values in Watts

        Returns:
            List of CycleEvent objects
        """
        if power_series.empty:
            return []

        # Determine compressor state at each point
        # Use hysteresis: need to cross threshold to change state
        states = pd.Series(index=power_series.index, dtype=bool)
        current_state = power_series.iloc[0] > self.power_on_threshold

        for i, (time, power) in enumerate(power_series.items()):
            if current_state:  # Currently ON
                if power < self.power_off_threshold:
                    current_state = False
            else:  # Currently OFF
                if power > self.power_on_threshold:
                    current_state = True
            states.iloc[i] = current_state

        # Find state transitions
        state_changes = states.diff().fillna(False)
        on_times = state_changes[state_changes == True].index.tolist()
        off_times = state_changes[state_changes == False].index.tolist()

        # Match on/off pairs to form cycles
        cycles = []
        for on_time in on_times:
            # Find next off time after this on time
            next_offs = [t for t in off_times if t > on_time]
            if next_offs:
                off_time = next_offs[0]

                # Get power data during this cycle
                cycle_power = power_series[on_time:off_time]

                if len(cycle_power) > 0:
                    duration = (off_time - on_time).total_seconds() / 60

                    cycle = CycleEvent(
                        start_time=on_time,
                        end_time=off_time,
                        duration_minutes=duration,
                        peak_power=cycle_power.max(),
                        avg_power=cycle_power.mean(),
                    )
                    cycles.append(cycle)

        return cycles

    def analyze_cycling(self, power_series: pd.Series) -> dict[str, Any]:
        """Comprehensive cycling analysis.

        Returns dict with:
        - cycles: List of all detected cycles
        - short_cycles: Cycles under 10 min (problematic)
        - avg_cycle_duration: Average on-time
        - cycles_per_hour: Cycling frequency
        - short_cycle_ratio: Proportion of short cycles
        """
        cycles = self.detect_cycles(power_series)

        if not cycles:
            return {
                "cycles": [],
                "short_cycles": [],
                "total_cycles": 0,
                "short_cycle_count": 0,
                "avg_cycle_duration": None,
                "cycles_per_hour": 0,
                "short_cycle_ratio": 0,
            }

        short_cycles = [c for c in cycles if c.is_short_cycle]
        durations = [c.duration_minutes for c in cycles]

        # Calculate time span
        time_span_hours = (power_series.index[-1] - power_series.index[0]).total_seconds() / 3600

        return {
            "cycles": cycles,
            "short_cycles": short_cycles,
            "total_cycles": len(cycles),
            "short_cycle_count": len(short_cycles),
            "avg_cycle_duration": np.mean(durations),
            "min_cycle_duration": np.min(durations),
            "max_cycle_duration": np.max(durations),
            "cycles_per_hour": len(cycles) / time_span_hours if time_span_hours > 0 else 0,
            "short_cycle_ratio": len(short_cycles) / len(cycles) if cycles else 0,
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

        # Create a series of cycle starts
        cycle_times = pd.Series(1, index=[c.start_time for c in cycles])

        # Resample to regular intervals and count
        cycle_counts = cycle_times.resample(window).sum().fillna(0)

        # Convert to cycles per hour
        window_hours = pd.Timedelta(window).total_seconds() / 3600
        cycles_per_hour = cycle_counts / window_hours

        result = pd.DataFrame(
            {
                "cycles_per_hour": cycles_per_hour,
                "is_problematic": cycles_per_hour > threshold_cycles_per_hour,
            }
        )

        return result


if __name__ == "__main__":
    # Test with synthetic data
    import numpy as np

    # Generate fake cycling power data
    np.random.seed(42)
    times = pd.date_range("2024-01-01", periods=1440, freq="1min")  # 24 hours

    # Simulate cycling: alternating on/off every 5-15 minutes
    power = np.zeros(len(times))
    state = False
    i = 0
    while i < len(times):
        duration = np.random.randint(3, 20)  # 3-20 minute cycles
        state = not state
        power_level = np.random.uniform(800, 1200) if state else np.random.uniform(20, 80)
        power[i : i + duration] = power_level
        i += duration

    power_series = pd.Series(power, index=times)

    # Test detector
    detector = CyclingDetector()
    analysis = detector.analyze_cycling(power_series)

    print("=== Cycling Analysis ===")
    print(f"Total cycles: {analysis['total_cycles']}")
    print(f"Short cycles (<10min): {analysis['short_cycle_count']}")
    print(f"Avg cycle duration: {analysis['avg_cycle_duration']:.1f} min")
    print(f"Cycles per hour: {analysis['cycles_per_hour']:.1f}")
    print(f"Short cycle ratio: {analysis['short_cycle_ratio']:.1%}")
