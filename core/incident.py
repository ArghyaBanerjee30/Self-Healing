from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from uuid import uuid4
import time

from core.signal import Signal


class IncidentPath(str, Enum):
    CODE = "code"
    INFRA = "infra"
    BOTH = "both"
    TRANSIENT = "transient"


class IncidentConfidence(str, Enum):
    HIGH = "high"
    LOW = "low"


@dataclass
class Incident:
    id: str = field(default_factory=lambda: str(uuid4()))
    signal: Optional[Signal] = None
    path: Optional[IncidentPath] = None
    confidence: Optional[IncidentConfidence] = None
    project_id: str = ""
    error_type: str = ""
    resolved: bool = False
    created_at: float = field(default_factory=time.time)
