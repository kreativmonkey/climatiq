"""Configuration management for HVAC Optimizer."""

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class IndoorUnitConfig(BaseModel):
    """Configuration for a single indoor unit."""

    name: str
    entity_id: str
    temp_sensor: str | None = None
    priority: str = "medium"  # low, medium, high


class InfluxDBConfig(BaseModel):
    """InfluxDB connection settings."""

    host: str = "localhost"
    port: int = 8086
    user: str = ""
    password: str = ""
    database: str = "homeassistant"


class ComfortConfig(BaseModel):
    """Comfort settings."""

    target_temp: float = 21.0
    min_temp: float = 19.0
    max_temp: float = 24.0
    tolerance: float = 0.5


class CyclingConfig(BaseModel):
    """Cycling detection settings."""

    power_on_threshold: float = 300.0
    power_off_threshold: float = 150.0
    min_cycle_minutes: int = 10


class LearningConfig(BaseModel):
    """Machine learning settings."""

    enabled: bool = True
    model_path: str = "models/cycling_predictor.joblib"
    min_observation_hours: int = 24
    retrain_interval_days: int = 7


class HVACOptimizerConfig(BaseSettings):
    """Main configuration for HVAC Optimizer."""

    # System type
    system_type: str = "multi_split"  # multi_split or single_split

    # Indoor units
    indoor_units: list[IndoorUnitConfig] = Field(default_factory=list)

    # Sensors
    power_sensor: str = ""
    outdoor_temp_sensor: str | None = None

    # Sub-configs
    influxdb: InfluxDBConfig = Field(default_factory=InfluxDBConfig)
    comfort: ComfortConfig = Field(default_factory=ComfortConfig)
    cycling: CyclingConfig = Field(default_factory=CyclingConfig)
    learning: LearningConfig = Field(default_factory=LearningConfig)

    # Unit priorities for load balancing (lower = used first as buffer)
    unit_priorities: dict[str, int] = Field(default_factory=dict)

    class Config:
        env_prefix = "HVAC_"
        env_nested_delimiter = "__"

    @classmethod
    def from_yaml(cls, path: Path) -> "HVACOptimizerConfig":
        """Load configuration from YAML file."""
        import yaml

        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for internal use."""
        return self.model_dump()
