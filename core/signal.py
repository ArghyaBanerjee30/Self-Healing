from __future__ import annotations

from enum import Enum
from typing import Optional
from uuid import uuid4
import time

from pydantic import BaseModel, Field


class SignalSource(str, Enum):
    APPLICATION_LOG = "application_log"
    KUBERNETES_EVENT = "kubernetes_event"


class Signal(BaseModel):
    """
    Structured event emitted by the log watcher or Kubernetes event stream.
    This is the sole input to the categoriser.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    source: SignalSource
    service: str
    error_type: str
    raw_message: str = ""

    # Application log fields
    stack_trace: Optional[str] = None

    # Kubernetes / infra fields
    pod_name: Optional[str] = None
    pod_status: Optional[str] = None  # e.g. "CrashLoopBackOff", "OOMKilled"
    restart_count: int = 0

    # Tenant context
    project_id: str = ""
    timestamp: float = Field(default_factory=time.time)

    model_config = {"frozen": True}
