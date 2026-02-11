"""Core entities and common types for HVAC Optimizer."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SystemMode(str, Enum):
    OBSERVATION = "observation"
    LEARNING = "learning"
    ACTIVE = "active"
    MANUAL = "manual"


class UnitStatus(BaseModel):
    name: str
    entity_id: str
    is_on: bool = False
    current_temp: float | None = None
    target_temp: float | None = None
    fan_mode: str | None = None
    hvac_mode: str | None = None


class OptimizerStatus(BaseModel):
    mode: SystemMode = SystemMode.OBSERVATION
    power_consumption: float = 0.0
    is_cycling: bool = False
    cycling_risk: float = 0.0  # 0.0 to 1.0
    base_load_detected: float | None = None
    units: dict[str, UnitStatus] = {}
    last_action: str | None = None
    last_update: datetime = Field(default_factory=datetime.utcnow)
    avoided_cycles_count: int = 0
