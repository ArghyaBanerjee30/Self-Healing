"""
Stage 2 — Parallel ambiguous investigation (~10 seconds).

Runs a code-side KG check and an infra-side Kubernetes check concurrently,
then returns suspicion scores that the router uses to break the ambiguity.
"""

import asyncio
import logging
from typing import Optional, Protocol, runtime_checkable

from core.signal import Signal
from categoriser.domain import Stage2Diagnostics

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# KG client protocol — fulfilled by knowledge/kg_querier.py when wired up.
# ---------------------------------------------------------------------------

@runtime_checkable
class KGClient(Protocol):
    def get_incident_count(self, service: str, error_type: str, project_id: str) -> int:
        """Return number of past incidents for this service+error_type."""
        ...

    def get_fix_confidence(self, service: str, error_type: str, project_id: str) -> float:
        """Return average confidence of past successful fixes (0.0–1.0)."""
        ...


# ---------------------------------------------------------------------------
# Code-side check
# ---------------------------------------------------------------------------

async def _check_code_side(signal: Signal, kg_client: Optional[KGClient]) -> float:
    """
    Query the knowledge graph for past incidents and fix history.
    Returns a suspicion score in [0.0, 1.0].
    """
    # Base score: presence of a stack trace is mild evidence of a code bug.
    base = 0.3 if signal.stack_trace else 0.1

    if not kg_client:
        return base

    try:
        # Run blocking KG calls in a thread so we don't block the event loop.
        incident_count, fix_confidence = await asyncio.gather(
            asyncio.get_event_loop().run_in_executor(
                None,
                kg_client.get_incident_count,
                signal.service,
                signal.error_type,
                signal.project_id,
            ),
            asyncio.get_event_loop().run_in_executor(
                None,
                kg_client.get_fix_confidence,
                signal.service,
                signal.error_type,
                signal.project_id,
            ),
        )

        # More historical code incidents → higher suspicion this is code.
        incident_boost = min(0.4, incident_count * 0.1)
        # Past fixes that were highly confident → this is likely a code bug again.
        confidence_boost = fix_confidence * 0.3

        return min(1.0, base + incident_boost + confidence_boost)

    except Exception as exc:
        log.warning("KG code-side check failed: %s", exc)
        return base


# ---------------------------------------------------------------------------
# Infra-side check
# ---------------------------------------------------------------------------

async def _check_infra_side(signal: Signal) -> float:
    """
    Query Kubernetes for pod health metrics.
    Falls back to signal fields if the cluster is unreachable.
    Returns a suspicion score in [0.0, 1.0].
    """
    if not signal.pod_name:
        # No pod context at all — weak infra signal.
        return 0.1

    try:
        from kubernetes import client as k8s_client, config as k8s_config  # type: ignore

        try:
            k8s_config.load_incluster_config()
        except Exception:
            k8s_config.load_kube_config()

        v1 = k8s_client.CoreV1Api()

        pod_list = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: v1.list_pod_for_all_namespaces(
                field_selector=f"metadata.name={signal.pod_name}"
            ),
        )

        if not pod_list.items:
            return _score_from_signal_fields(signal)

        pod = pod_list.items[0]
        score = 0.0

        if pod.status and pod.status.container_statuses:
            for cs in pod.status.container_statuses:
                restarts = cs.restart_count or 0
                if restarts >= 5:
                    score += 0.5
                elif restarts >= 2:
                    score += 0.3
                elif restarts >= 1:
                    score += 0.1

                if cs.state and cs.state.waiting:
                    reason = (cs.state.waiting.reason or "").lower()
                    if "crashloop" in reason:
                        score += 0.4
                    elif "error" in reason or "backoff" in reason:
                        score += 0.2

        if pod.status:
            phase = (pod.status.phase or "").lower()
            if phase in ("failed", "unknown"):
                score += 0.3

        return min(1.0, score)

    except Exception as exc:
        log.warning("Kubernetes infra-side check failed: %s", exc)
        return _score_from_signal_fields(signal)


def _score_from_signal_fields(signal: Signal) -> float:
    """Derive an infra suspicion score purely from Signal fields (no I/O)."""
    if signal.restart_count >= 5:
        return 0.7
    if signal.restart_count >= 2:
        return 0.4
    if signal.restart_count >= 1:
        return 0.2
    if signal.pod_status:
        return 0.3
    return 0.1


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

async def investigate(
    signal: Signal,
    kg_client: Optional[KGClient] = None,
) -> Stage2Diagnostics:
    """
    Run the code-side and infra-side checks in parallel.
    Returns suspicion scores the router uses to resolve the ambiguity.
    """
    code_score, infra_score = await asyncio.gather(
        _check_code_side(signal, kg_client),
        _check_infra_side(signal),
    )

    return Stage2Diagnostics(
        code_suspicion_score=code_score,
        infra_suspicion_score=infra_score,
    )
