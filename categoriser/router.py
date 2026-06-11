"""
Categoriser router — the top-level entry point for the categoriser.

Combines Stage 1 (fast, no I/O) and Stage 2 (parallel investigation) to
produce a RoutingResult that tells the Supervisor which healing path to take.

Decision logic mirrors the architecture spec exactly:

  Stage 1 unambiguous:
    code=T, infra=F  →  CODE PATH   (high confidence)
    code=F, infra=T  →  INFRA PATH  (high confidence)

  Stage 1 ambiguous (both or neither):
    → Stage 2 parallel investigation → compare suspicion scores
    infra_score > code_score + 0.2   →  INFRA PATH  (high confidence)
    code_score  > infra_score + 0.2  →  CODE PATH   (high confidence)
    both scores < 0.3                →  TRANSIENT   (low confidence)
    scores roughly equal             →  BOTH PATHS  (low confidence)

  Transient flag (< 3 occurrences in 5 min):
    → hand off to TransientWatcher
    → if RESOLVED: done (no healing)
    → if ESCALATED: re-run router without the transient gate
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from core.incident import Incident, IncidentConfidence, IncidentPath
from core.signal import Signal
from categoriser.stage1 import Stage1Result, classify as _stage1
from categoriser.stage2 import KGClient, Stage2Result, investigate as _stage2
from categoriser import transient_watcher as _tw

log = logging.getLogger(__name__)

# Minimum difference between infra and code scores to pick one path over the
# other rather than running both.
_DOMINANCE_THRESHOLD = 0.2

# Score below which both sides are considered too weak to act on.
_LOW_SCORE_CEILING = 0.3


@dataclass
class RoutingResult:
    """Everything the Supervisor needs to dispatch to the right healing path."""
    incident: Incident
    stage1: Stage1Result
    stage2: Optional[Stage2Result] = None


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

async def route(
    signal: Signal,
    kg_client: Optional[KGClient] = None,
    *,
    _skip_transient_gate: bool = False,
) -> RoutingResult:
    """
    Full categoriser pipeline.  Returns a RoutingResult whose
    ``incident.path`` tells the Supervisor which healing path to take.

    Parameters
    ----------
    signal:
        The structured signal emitted by the log watcher.
    kg_client:
        Optional knowledge-graph client for Stage 2 code-side scoring.
        When None, Stage 2 falls back to heuristics derived from signal fields.
    """
    stage1_result = _stage1(signal)

    log.info(
        "[Categoriser/Stage1] service=%s error_type=%s "
        "code_signal=%s infra_signal=%s transient_flag=%s",
        signal.service,
        signal.error_type,
        stage1_result.code_signal,
        stage1_result.infra_signal,
        stage1_result.transient_flag,
    )

    # ------------------------------------------------------------------
    # Transient gate — watch before acting
    # ------------------------------------------------------------------
    if stage1_result.transient_flag and not _skip_transient_gate:
        watch_result = await _tw.watch(signal)
        _tw.reset_counter(signal)

        if watch_result.outcome == _tw.WatchOutcome.RESOLVED:
            return RoutingResult(
                incident=_make_incident(signal, IncidentPath.TRANSIENT, IncidentConfidence.HIGH, resolved=True),
                stage1=stage1_result,
            )

        # Error persisted → re-run without the transient gate so we act.
        log.info("[Categoriser] transient escalated — re-categorising %s", signal.error_type)
        return await route(signal, kg_client, _skip_transient_gate=True)

    # ------------------------------------------------------------------
    # Stage 1 — unambiguous paths
    # ------------------------------------------------------------------
    if stage1_result.code_signal and not stage1_result.infra_signal:
        log.info("[Categoriser] → CODE PATH (high confidence, Stage 1)")
        return RoutingResult(
            incident=_make_incident(signal, IncidentPath.CODE, IncidentConfidence.HIGH),
            stage1=stage1_result,
        )

    if stage1_result.infra_signal and not stage1_result.code_signal:
        log.info("[Categoriser] → INFRA PATH (high confidence, Stage 1)")
        return RoutingResult(
            incident=_make_incident(signal, IncidentPath.INFRA, IncidentConfidence.HIGH),
            stage1=stage1_result,
        )

    # ------------------------------------------------------------------
    # Stage 2 — ambiguous (both signals, or neither)
    # ------------------------------------------------------------------
    log.info("[Categoriser] ambiguous — running Stage 2 parallel investigation")
    stage2_result = await _stage2(signal, kg_client)

    code_score = stage2_result.code_suspicion_score
    infra_score = stage2_result.infra_suspicion_score

    log.info(
        "[Categoriser/Stage2] code_score=%.2f infra_score=%.2f",
        code_score,
        infra_score,
    )

    if infra_score > code_score + _DOMINANCE_THRESHOLD:
        log.info("[Categoriser] → INFRA PATH (Stage 2, infra dominates)")
        path, confidence = IncidentPath.INFRA, IncidentConfidence.HIGH

    elif code_score > infra_score + _DOMINANCE_THRESHOLD:
        log.info("[Categoriser] → CODE PATH (Stage 2, code dominates)")
        path, confidence = IncidentPath.CODE, IncidentConfidence.HIGH

    elif code_score < _LOW_SCORE_CEILING and infra_score < _LOW_SCORE_CEILING:
        log.info("[Categoriser] → TRANSIENT (Stage 2, both scores too low)")
        path, confidence = IncidentPath.TRANSIENT, IncidentConfidence.LOW

    else:
        log.info("[Categoriser] → BOTH PATHS (Stage 2, scores roughly equal)")
        path, confidence = IncidentPath.BOTH, IncidentConfidence.LOW

    return RoutingResult(
        incident=_make_incident(signal, path, confidence),
        stage1=stage1_result,
        stage2=stage2_result,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_incident(
    signal: Signal,
    path: IncidentPath,
    confidence: IncidentConfidence,
    resolved: bool = False,
) -> Incident:
    return Incident(
        signal=signal,
        path=path,
        confidence=confidence,
        project_id=signal.project_id,
        error_type=signal.error_type,
        resolved=resolved,
    )
