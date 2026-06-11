"""
Categoriser router — top-level entry point for the categoriser.

Public interface:
    route(signal, kg_client=None) -> CategoryResult

Decision logic (mirrors architecture spec):

  Stage 1 unambiguous:
    code=T, infra=F  →  CODE PATH   (high confidence)
    code=F, infra=T  →  INFRA PATH  (high confidence)

  Stage 1 ambiguous (both signals or neither):
    → Stage 2 parallel investigation
    infra_score > code_score + 0.2  →  INFRA PATH  (high confidence)
    code_score  > infra_score + 0.2  →  CODE PATH   (high confidence)
    both scores < 0.3               →  TRANSIENT   (low confidence)
    scores roughly equal            →  BOTH PATHS  (low confidence)

  Transient flag (< 3 occurrences in 5 min):
    → TransientWatcher holds for up to 5 min
    RESOLVED  →  CategoryResult with path=TRANSIENT, resolved=True
    ESCALATED →  re-run router without the transient gate
"""

import logging
from typing import Optional

from core.incident import Incident, IncidentConfidence, IncidentPath
from core.signal import Signal
from categoriser.domain import CategoryResult, Stage2Diagnostics
from categoriser.stage1 import classify as _stage1
from categoriser.stage2 import KGClient, investigate as _stage2
from categoriser import transient_watcher as _tw

log = logging.getLogger(__name__)

_DOMINANCE_THRESHOLD = 0.2   # score gap required to pick one path over the other
_LOW_SCORE_CEILING = 0.3     # both scores below this → treat as transient


async def route(
    signal: Signal,
    kg_client: Optional[KGClient] = None,
    *,
    _skip_transient_gate: bool = False,
) -> CategoryResult:
    """
    Run the full categoriser pipeline for *signal*.

    Returns a CategoryResult whose ``incident.path`` tells the Supervisor
    which healing path to dispatch.
    """
    stage1 = _stage1(signal)

    log.info(
        "[Categoriser/Stage1] service=%s error_type=%s "
        "code_signal=%s infra_signal=%s transient_flag=%s",
        signal.service, signal.error_type,
        stage1.code_signal, stage1.infra_signal, stage1.transient_flag,
    )

    # ------------------------------------------------------------------
    # Transient gate
    # ------------------------------------------------------------------
    if stage1.transient_flag and not _skip_transient_gate:
        # Feed stage1's occurrence log into the transient watcher counter
        # so the watcher sees occurrences recorded before it starts watching.
        _tw.record_occurrence(signal)

        def _get_count(s: Signal) -> int:
            from categoriser.stage1 import _occurrence_log
            key = f"{s.service}:{s.error_type}"
            return len(_occurrence_log.get(key, []))

        watch_result = await _tw.watch(
            signal,
            duration_seconds=60.0,
            poll_interval_seconds=5.0,
            escalation_threshold=3,
            get_recent_count=_get_count,
        )
        _tw.reset_counter(signal)

        if watch_result.outcome == _tw.WatchOutcome.RESOLVED:
            return CategoryResult(
                signal=signal,
                incident=_incident(signal, IncidentPath.TRANSIENT, IncidentConfidence.HIGH, resolved=True),
                stage1=stage1,
            )

        log.info("[Categoriser] transient escalated — re-categorising %s", signal.error_type)
        return await route(signal, kg_client, _skip_transient_gate=True)

    # ------------------------------------------------------------------
    # Stage 1 — unambiguous paths
    # ------------------------------------------------------------------
    if stage1.code_signal and not stage1.infra_signal:
        log.info("[Categoriser] → CODE PATH (Stage 1, high confidence)")
        return CategoryResult(
            signal=signal,
            incident=_incident(signal, IncidentPath.CODE, IncidentConfidence.HIGH),
            stage1=stage1,
        )

    if stage1.infra_signal and not stage1.code_signal:
        log.info("[Categoriser] → INFRA PATH (Stage 1, high confidence)")
        return CategoryResult(
            signal=signal,
            incident=_incident(signal, IncidentPath.INFRA, IncidentConfidence.HIGH),
            stage1=stage1,
        )

    # ------------------------------------------------------------------
    # Stage 2 — ambiguous (both signals present, or neither)
    # ------------------------------------------------------------------
    log.info("[Categoriser] ambiguous — running Stage 2 parallel investigation")
    stage2 = await _stage2(signal, kg_client)
    path, confidence = _resolve_ambiguity(stage2)

    log.info(
        "[Categoriser/Stage2] code=%.2f infra=%.2f → %s (%s)",
        stage2.code_suspicion_score, stage2.infra_suspicion_score,
        path.value, confidence.value,
    )

    return CategoryResult(
        signal=signal,
        incident=_incident(signal, path, confidence),
        stage1=stage1,
        stage2=stage2,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_ambiguity(
    stage2: Stage2Diagnostics,
) -> tuple[IncidentPath, IncidentConfidence]:
    code = stage2.code_suspicion_score
    infra = stage2.infra_suspicion_score

    if infra > code + _DOMINANCE_THRESHOLD:
        return IncidentPath.INFRA, IncidentConfidence.HIGH
    if code > infra + _DOMINANCE_THRESHOLD:
        return IncidentPath.CODE, IncidentConfidence.HIGH
    if code < _LOW_SCORE_CEILING and infra < _LOW_SCORE_CEILING:
        return IncidentPath.TRANSIENT, IncidentConfidence.LOW
    return IncidentPath.BOTH, IncidentConfidence.LOW


def _incident(
    signal: Signal,
    path: IncidentPath,
    confidence: IncidentConfidence,
    resolved: bool = False,
) -> Incident:
    return Incident(
        signal_id=signal.id,
        path=path,
        confidence=confidence,
        project_id=signal.project_id,
        error_type=signal.error_type,
        resolved=resolved,
    )
