"""
Supervisor Agent — the brain of the self-healing system.

Flow:
  CategoryResult → load skill → LLM creates dynamic TodoList → execute subagents
"""
import json
import re
import os
import logging
import httpx
from typing import Optional
from dotenv import load_dotenv

from core.signal import Signal
from core.incident import IncidentPath
from core.todo_list import TodoList
from categoriser.domain import CategoryResult
from agents.skills.loader import load_skill, skill_name
from agents.code import observer as _observer_agent
from agents.code import detective as _detective_agent
from agents.code import coder as _coder_agent

load_dotenv()
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM client (Ollama)
# ---------------------------------------------------------------------------

class _LLMClient:
    def __init__(self):
        self.model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
        self.base_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")

    def chat(self, system: str, user: str) -> str:
        response = httpx.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
            },
            timeout=180.0,
        )
        response.raise_for_status()
        return response.json()["message"]["content"]


# ---------------------------------------------------------------------------
# Incident description — built from Signal + CategoryResult for the LLM prompt
# ---------------------------------------------------------------------------

def _describe(result: CategoryResult) -> str:
    s = result.signal
    inc = result.incident
    lines = [
        f"incident_id: {inc.id}",
        f"path: {inc.path.value}",
        f"confidence: {inc.confidence.value}",
        f"service: {s.service}",
        f"error_type: {s.error_type}",
        f"raw_message: {s.raw_message}",
        f"project_id: {s.project_id}",
    ]
    if s.stack_trace:
        lines.append(f"stack_trace:\n{s.stack_trace}")
    if s.pod_name:
        lines.append(f"pod_name: {s.pod_name}")
    if s.pod_status:
        lines.append(f"pod_status: {s.pod_status}")
    if s.restart_count:
        lines.append(f"restart_count: {s.restart_count}")
    if result.stage2:
        lines.append(
            f"stage2_scores: code={result.stage2.code_suspicion_score:.2f} "
            f"infra={result.stage2.infra_suspicion_score:.2f}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM response parser — extracts (understanding, TodoList) from JSON output
# ---------------------------------------------------------------------------

def _parse_plan(raw: str, incident_id: str) -> tuple[str, TodoList]:
    todo_list = TodoList(incident_id=incident_id)

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return _fallback_plan(incident_id)

    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError:
        return _fallback_plan(incident_id)

    understanding = parsed.get("understanding", "No understanding provided")
    todos = parsed.get("todos", [])
    if not todos:
        return _fallback_plan(incident_id)

    for item in sorted(todos, key=lambda t: t.get("priority", 99)):
        desc = item.get("description", "").strip()
        agent = item.get("assigned_to", "supervisor").strip()
        if desc:
            todo_list.add(description=desc, assigned_to=agent)

    return understanding, todo_list


def _fallback_plan(incident_id: str) -> tuple[str, TodoList]:
    todo_list = TodoList(incident_id=incident_id)
    todo_list.add("Extract file path and line number from stack trace", "observer")
    todo_list.add("Read source code and query KG for callers, tests, past incidents", "detective")
    todo_list.add("Write minimal fix based on root cause", "coder")
    todo_list.add("Validate fix: static analysis, security scan, semantic review", "guardrail")
    todo_list.add("Run test suite, determine deployment decision", "tester")
    todo_list.add("Commit and deliver fix", "committer")
    todo_list.add("Write incident and fix outcome to knowledge graph", "learner")
    return "[fallback plan — LLM parse failed]", todo_list


# ---------------------------------------------------------------------------
# Subagent stubs — replaced by real implementations one by one
# ---------------------------------------------------------------------------

def _parse_observer_context(ctx: str, signal: Signal) -> "_observer_agent.ObserverResult":
    """Extract ObserverResult from a context string (looks for '| {...}' JSON trailer)."""
    try:
        idx = ctx.rfind("| {")
        if idx != -1:
            return _observer_agent.ObserverResult.from_json(ctx[idx + 2:])
    except Exception:
        pass
    # fallback: try to extract from stack trace directly
    return _observer_agent.run(signal)


def _parse_detective_context(ctx: str, signal: Signal) -> "Optional[_detective_agent.DetectiveResult]":
    """Extract DetectiveResult from a context string."""
    try:
        idx = ctx.rfind("| {")
        if idx != -1:
            return _detective_agent.DetectiveResult.from_json(ctx[idx + 2:])
    except Exception as e:
        log.warning("[Supervisor] could not parse Detective context: %s", e)
    return None


def _run_subagent(agent: str, todo: str, signal: Signal, context: str) -> str:
    stubs = {
        "observer":   _stub_observer,
        "detective":  _stub_detective,
        "operator":   _stub_operator,
        "coder":      _stub_coder,
        "guardrail":  _stub_guardrail,
        "tester":     _stub_tester,
        "executor":   _stub_executor,
        "verifier":   _stub_verifier,
        "committer":  _stub_committer,
        "learner":    _stub_learner,
        "supervisor": _stub_supervisor_step,
    }
    return stubs.get(agent, _stub_unknown)(todo, signal, context)


def _stub_observer(todo: str, s: Signal, ctx: str) -> str:
    result = _observer_agent.run(s)
    if result.found:
        return (
            f"[Observer] file={result.file_path}  "
            f"line={result.line}  function={result.function_name}  "
            f"| {result.to_json()}"
        )
    return f"[Observer] no app frame found in stack trace — {s.service}/{s.error_type}"


def _stub_detective(todo: str, s: Signal, ctx: str) -> str:
    # Parse Observer result from context
    obs = _parse_observer_context(ctx, s)
    if not obs.found:
        return f"[Detective] cannot proceed — Observer found no app file"

    result = _detective_agent.run(s, obs)
    blast = [c["name"] for c in result.blast_radius] or ["none via AST"]
    similar = [f"{f['name']} ({f['file']}, score={f['score']})" for f in result.similar_functions[:3]]
    summary = (
        f"[Detective] file={result.file_path}:{result.line}  "
        f"function={result.function_name}\n"
        f"  blast_radius: {blast}\n"
        f"  similar_functions: {similar or ['none found']}\n"
        f"  root_cause: {result.root_cause}\n"
        f"  pattern: {result.pattern}"
    )
    return summary + f"\n| {result.to_json()}"


def _stub_operator(todo: str, s: Signal, ctx: str) -> str:
    pod = s.pod_name or f"{s.service}-pod"
    return (
        f"[STUB] Operator: pod={pod} status={s.pod_status or 'CrashLoopBackOff'} "
        f"restart_count={s.restart_count} — playbook: rollback"
    )


def _stub_coder(todo: str, s: Signal, ctx: str) -> str:
    det = _parse_detective_context(ctx, s)
    if det is None:
        return "[Coder] cannot proceed — Detective result not found in context"

    result = _coder_agent.run(s, det)
    if not result.fix_written:
        return f"[Coder] fix NOT written: {result.fix_description}"

    diff_preview = "\n".join(result.diff.splitlines()[:20])
    return (
        f"[Coder] fix written to {result.file_path}\n"
        f"  {result.fix_description}\n"
        f"  diff preview:\n{diff_preview}"
        + (f"\n  ... ({len(result.diff.splitlines())} lines total)" if len(result.diff.splitlines()) > 20 else "")
        + f"\n| {result.to_json()}"
    )


def _stub_guardrail(todo: str, s: Signal, ctx: str) -> str:
    return (
        "[STUB] Guardrail: Layer1=PASS, Layer2=PASS, Layer3=PASS. VERDICT: PASS"
    )


def _stub_tester(todo: str, s: Signal, ctx: str) -> str:
    return (
        "[STUB] Tester: pytest passed. existing_tests_modified=False, "
        "new_tests_added=True. DECISION: direct_deploy"
    )


def _stub_executor(todo: str, s: Signal, ctx: str) -> str:
    return f"[STUB] Executor: kubectl rollout undo deployment/{s.service} — complete."


def _stub_verifier(todo: str, s: Signal, ctx: str) -> str:
    return "[STUB] Verifier: all pods Running+Ready. Service healthy."


def _stub_committer(todo: str, s: Signal, ctx: str) -> str:
    return "[STUB] Committer: fix committed. Merged to main (direct_deploy)."


def _stub_learner(todo: str, s: Signal, ctx: str) -> str:
    return f"[STUB] Learner: wrote incident and fix to KG for {s.project_id}."


def _stub_supervisor_step(todo: str, s: Signal, ctx: str) -> str:
    return f"[STUB] Supervisor step: {todo[:80]}"


def _stub_unknown(todo: str, s: Signal, ctx: str) -> str:
    return f"[STUB] Unknown agent — todo: {todo[:80]}"


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------

class Supervisor:
    def __init__(self, llm: Optional[_LLMClient] = None, verbose: bool = True):
        self.llm = llm or _LLMClient()
        self.verbose = verbose

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    def run(self, result: CategoryResult) -> TodoList:
        signal = result.signal
        incident = result.incident

        self._log(f"\n{'='*60}")
        self._log(f"SUPERVISOR [{incident.id}]")
        self._log(f"  Path  : {incident.path.value.upper()} ({incident.confidence.value} confidence)")
        self._log(f"  Error : {signal.error_type}: {signal.raw_message}")
        self._log(f"  Service: {signal.service}")
        self._log(f"{'='*60}")

        # 1. Load skill for this path (TRANSIENT has no skill — skip)
        if incident.path == IncidentPath.TRANSIENT:
            self._log("[SUPERVISOR] Transient incident — no action needed.")
            return TodoList(incident_id=incident.id)

        skill = load_skill(incident.path)
        self._log(f"\n[SKILL] Loaded: {skill_name(incident.path)}")

        # 2. Call LLM to create a dynamic, incident-specific TodoList
        self._log("\n[PLAN] Asking LLM to create TodoList...")
        prompt = (
            f"Here is the incident you must heal:\n\n"
            f"{_describe(result)}\n\n"
            f"Based on the skill above and this specific incident, "
            f"produce your understanding and a targeted TodoList. "
            f"Return valid JSON matching the output format in the skill."
        )

        try:
            raw_plan = self.llm.chat(system=skill, user=prompt)
            log.debug("[Supervisor] LLM raw plan: %s", raw_plan[:200])
        except Exception as e:
            self._log(f"[PLAN] LLM call failed: {e} — using fallback plan")
            raw_plan = ""

        understanding, todo_list = _parse_plan(raw_plan, incident.id)

        self._log(f"\n[UNDERSTANDING]\n  {understanding}")
        self._log(f"\n[TODOS] {len(todo_list.items)} items created:")
        self._log(todo_list.display())

        # 3. Execute each todo in sequence
        self._log("\n[EXECUTE] Running subagents...\n")
        context = ""
        failed = False

        for item in todo_list.items:
            self._log(f"  ○ [{item.assigned_to}] {item.description[:90]}")
            item.start()

            try:
                result_text = _run_subagent(
                    agent=item.assigned_to,
                    todo=item.description,
                    signal=signal,
                    context=context,
                )
                item.complete(result_text)
                context = result_text
                self._log(f"  ✓ [{item.assigned_to}] {result_text[:100]}")

                if item.assigned_to == "guardrail" and "HARD BLOCK" in result_text:
                    self._log("\n[ESCALATE] Security violation — stopping.")
                    failed = True
                    break

            except Exception as e:
                item.fail(str(e))
                self._log(f"  ✗ [{item.assigned_to}] FAILED: {e}")
                failed = True
                break

        # 4. Summary
        self._log(f"\n{'─'*60}")
        self._log(f"[RESULT] {todo_list.summary()}")
        status = "RESOLVED" if not failed else "FAILED"
        self._log(f"[STATUS] {status}")
        self._log(todo_list.display())

        return todo_list
