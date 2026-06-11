from __future__ import annotations

from enum import Enum
from uuid import uuid4
import time

from pydantic import BaseModel, Field


class IncidentPath(str, Enum):
    CODE = "code"
    INFRA = "infra"
    BOTH = "both"
    TRANSIENT = "transient"


class IncidentConfidence(str, Enum):
    HIGH = "high"
    LOW = "low"


class Incident(BaseModel):
    """
    Core domain object created by the categoriser and consumed by the Supervisor.

    References the originating Signal by ID rather than embedding it — the full
    Signal is carried in CategoryResult for callers that need it.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    signal_id: str                        # foreign key → Signal.id
    path: IncidentPath
    confidence: IncidentConfidence
    project_id: str
    error_type: str
    resolved: bool = False
    created_at: float = Field(default_factory=time.time)

    model_config = {"frozen": True}
