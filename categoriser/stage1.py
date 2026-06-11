"""
Stage 1 — Fast signal analysis (< 1 second, no external calls).

Answers three questions about the incoming Signal and returns a Stage1Result
that the router uses to decide whether to act immediately or escalate to Stage 2.
"""

import re
import time
from collections import defaultdict
from dataclasses import dataclass

from core.signal import Signal

# Pod/container states that indicate an infrastructure failure.
_INFRA_FAILURE_STATES = {
    "crashloopbackoff",
    "oomkilled",
    "error",
    "imagepullbackoff",
    "errimagepull",
    "createcontainerconfigerror",
    "containercreating",  # stuck
    "failed",
    "unknown",
}

# Filesystem path fragments that belong to the Python runtime / third-party libs,
# not to application code.
_STDLIB_PATH_FRAGMENTS = (
    "/usr/lib/python",
    "/usr/local/lib/python",
    "site-packages",
    "dist-packages",
    "<frozen ",
    "<string>",
)

# Sliding-window error occurrence tracker  {service:error_type -> [timestamp, ...]}
_occurrence_log: dict[str, list[float]] = defaultdict(list)
_TRANSIENT_WINDOW_SECONDS = 300   # 5-minute window
_TRANSIENT_THRESHOLD = 3          # fewer than 3 hits in window → transient


@dataclass
class Stage1Result:
    code_signal: bool
    infra_signal: bool
    transient_flag: bool


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _has_app_stack_trace(signal: Signal) -> bool:
    """Return True when the stack trace references application source files."""
    if not signal.stack_trace:
        return False

    trace = signal.stack_trace

    # Must look like a real Python/JVM/Node stack trace.
    has_trace_header = bool(
        re.search(r"(Traceback \(most recent call last\)|File \"|at .+\(.+:\d+\))", trace)
    )
    if not has_trace_header:
        # Bare error message with no trace — not enough evidence of app code.
        return False

    # At least one "File" line must reference a path outside stdlib/venv.
    for line in trace.splitlines():
        if 'File "' in line or "File '" in line:
            if not any(frag in line for frag in _STDLIB_PATH_FRAGMENTS):
                return True

    return False


def _is_pod_failed(signal: Signal) -> bool:
    """Return True when the signal carries evidence of a failed pod/container."""
    def _normalise(s: str) -> str:
        return s.lower().replace("-", "").replace("_", "")

    if signal.pod_status:
        return _normalise(signal.pod_status) in {
            _normalise(s) for s in _INFRA_FAILURE_STATES
        }

    # Kubernetes event signals encode the failure type in error_type.
    # Use exact match only — "error" must not match "TypeError".
    if signal.error_type:
        normalised = _normalise(signal.error_type)
        if normalised in {_normalise(s) for s in _INFRA_FAILURE_STATES}:
            return True

    return False


def _is_transient(signal: Signal) -> bool:
    """
    Return True when this error has occurred fewer than _TRANSIENT_THRESHOLD
    times in the last _TRANSIENT_WINDOW_SECONDS seconds.

    Side-effect: records the current occurrence in the sliding window.
    """
    now = time.time()
    key = f"{signal.service}:{signal.error_type}"

    # Evict expired entries.
    _occurrence_log[key] = [
        t for t in _occurrence_log[key] if now - t < _TRANSIENT_WINDOW_SECONDS
    ]

    # Record this occurrence.
    _occurrence_log[key].append(now)

    return len(_occurrence_log[key]) < _TRANSIENT_THRESHOLD


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def classify(signal: Signal) -> Stage1Result:
    """
    Classify a Signal in < 1 second with no external I/O.

    Returns a Stage1Result the router uses to determine the healing path.
    """
    return Stage1Result(
        code_signal=_has_app_stack_trace(signal),
        infra_signal=_is_pod_failed(signal),
        transient_flag=_is_transient(signal),
    )
