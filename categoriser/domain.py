"""
Categoriser domain — the public contract between the categoriser and its callers.

Input:  core.signal.Signal          (defined in core — shared across the system)
Output: CategoryResult              (defined here — owned by the categoriser)

Internal pipeline types (Stage1Diagnostics, Stage2Diagnostics) are also
defined here so every layer of the categoriser shares one source of truth.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from core.incident import Incident
from core.signal import Signal


class Stage1Diagnostics(BaseModel):
    """
    Output of the fast, no-I/O Stage 1 classifier.
    Answers three boolean questions about the incoming Signal.
    """

    code_signal: bool    # stack trace references application source files
    infra_signal: bool   # pod / container is in a failed state
    transient_flag: bool  # error has occurred < 3 times in the last 5 minutes


class Stage2Diagnostics(BaseModel):
    """
    Output of the parallel Stage 2 investigation (ambiguous signals only).
    Suspicion scores drive the final path decision in the router.
    """

    code_suspicion_score: float = Field(ge=0.0, le=1.0)
    infra_suspicion_score: float = Field(ge=0.0, le=1.0)


class CategoryResult(BaseModel):
    """
    Final output of the categoriser.  Handed directly to the Supervisor.

    Carries both the lightweight Incident (path + confidence) and the
    original Signal so the Supervisor can pass full context to sub-agents
    without a separate lookup.

    Diagnostic fields (stage1, stage2) are available for observability,
    audit logging, and the Learner's KG write.
    """

    signal: Signal                           # original input (immutable)
    incident: Incident                       # routing decision + identity
    stage1: Stage1Diagnostics               # always present
    stage2: Optional[Stage2Diagnostics] = None  # present only for ambiguous signals
