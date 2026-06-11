from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time


class SignalSource(str, Enum):
    APPLICATION_LOG = "application_log"
    KUBERNETES_EVENT = "kubernetes_event"


@dataclass
class Signal:
    source: SignalSource
    service: str
    error_type: str
    raw_message: str = ""
    stack_trace: Optional[str] = None
    # Kubernetes / infra fields
    pod_name: Optional[str] = None
    pod_status: Optional[str] = None   # e.g. "CrashLoopBackOff", "OOMKilled"
    restart_count: int = 0
    # Context
    project_id: str = ""
    timestamp: float = field(default_factory=time.time)
