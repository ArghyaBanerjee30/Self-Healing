"""
Transient watcher — monitor a Signal for up to 5 minutes.

If the error recurs enough times during the window it is escalated back to
the router for full categorisation.  If it stops occurring it is silently
resolved (no healing action needed).
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from core.signal import Signal

log = logging.getLogger(__name__)


class WatchOutcome(str, Enum):
    ESCALATE = "escalate"   # error kept recurring → re-categorise
    RESOLVED = "resolved"   # error stopped → no action needed


@dataclass
class WatchResult:
    outcome: WatchOutcome
    signal: Signal
    occurrence_count: int
    watch_duration_seconds: float


async def watch(
    signal: Signal,
    duration_seconds: float = 300.0,
    poll_interval_seconds: float = 30.0,
    escalation_threshold: int = 3,
    get_recent_count: Optional[Callable[[Signal], int]] = None,
) -> WatchResult:
    """
    Watch *signal* for up to *duration_seconds*.

    Parameters
    ----------
    signal:
        The signal that triggered the transient flag.
    duration_seconds:
        How long to watch before declaring the error resolved (default: 5 min).
    poll_interval_seconds:
        How often to check the occurrence counter (default: 30 s).
    escalation_threshold:
        Total occurrences required to escalate (default: 3).
    get_recent_count:
        Optional callback that returns the current occurrence count for this
        signal.  When omitted the watcher relies on calls from the log watcher
        incrementing a shared counter (see ``record_occurrence``).
    """
    start = time.monotonic()
    occurrences = 1  # the signal that triggered the watch already counts

    log.info(
        "[TransientWatcher] watching %s/%s for %.0fs",
        signal.service,
        signal.error_type,
        duration_seconds,
    )

    while time.monotonic() - start < duration_seconds:
        await asyncio.sleep(poll_interval_seconds)

        if get_recent_count is not None:
            occurrences = get_recent_count(signal)
        else:
            # Fall back to the module-level shared counter.
            occurrences = _get_count(signal)

        log.debug(
            "[TransientWatcher] %s/%s occurrences=%d",
            signal.service,
            signal.error_type,
            occurrences,
        )

        if occurrences >= escalation_threshold:
            elapsed = time.monotonic() - start
            log.info(
                "[TransientWatcher] escalating %s/%s after %d occurrences in %.0fs",
                signal.service,
                signal.error_type,
                occurrences,
                elapsed,
            )
            return WatchResult(
                outcome=WatchOutcome.ESCALATE,
                signal=signal,
                occurrence_count=occurrences,
                watch_duration_seconds=elapsed,
            )

    elapsed = time.monotonic() - start
    log.info(
        "[TransientWatcher] resolved %s/%s — only %d occurrence(s) in %.0fs",
        signal.service,
        signal.error_type,
        occurrences,
        elapsed,
    )
    return WatchResult(
        outcome=WatchOutcome.RESOLVED,
        signal=signal,
        occurrence_count=occurrences,
        watch_duration_seconds=elapsed,
    )


# ---------------------------------------------------------------------------
# Shared occurrence counter (used when no get_recent_count callback is given)
# ---------------------------------------------------------------------------

_counters: dict[str, int] = {}


def _key(signal: Signal) -> str:
    return f"{signal.service}:{signal.error_type}"


def record_occurrence(signal: Signal) -> None:
    """Called by the log watcher each time this signal fires again."""
    k = _key(signal)
    _counters[k] = _counters.get(k, 0) + 1


def _get_count(signal: Signal) -> int:
    return _counters.get(_key(signal), 1)


def reset_counter(signal: Signal) -> None:
    """Reset after a watch cycle completes."""
    _counters.pop(_key(signal), None)
