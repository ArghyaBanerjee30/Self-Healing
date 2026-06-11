from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time


class SignalSource(Enum):
    LOG = "log"
    METRIC = "metric"
    ALERT = "alert"


@dataclass
class Signal:
    service: str
    error_type: str
    error_message: str
    source: SignalSource
    stack_trace: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
