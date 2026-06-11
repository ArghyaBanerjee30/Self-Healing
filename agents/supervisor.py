"""
Supervisor Agent — the brain of the self-healing system.

Flow:
  classified log → load skill → LLM creates dynamic TodoList → execute subagents
"""
import json
import re
import os
import httpx
from typing import Optional

from core.incident import Incident, IncidentCategory, IncidentStatus
from core.todo_list import TodoList, TodoStatus
from agents.skills.loader import load_skill, skill_name


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
# Incident description builder
# ---------------------------------------------------------------------------

def _describe_incident(incident: Incident) -> str:
    s = incident.signal
    lines = [
        f"incident_id: {incident.id}",
        f"category: {incident.category.value}",
        f"service: {s.service}",
        f"error_type: {s.error_type}",
        f"error_message: {s.error_message}",
        f"occurrence_count: {s.occurrence_count}",
    ]
    if s.stack_trace:
        lines.append(f"stack_trace:\n{s.stack_trace}")
    if s.pod_name:
        lines.append(f"pod_name: {s.pod_name}")
    if s.namespace:
        lines.append(f"namespace: {s.namespace}")
    lines.append(f"raw_log: {s.raw_text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# TodoList parser — extracts todos from LLM JSON response
# ---------------------------------------------------------------------------

def _parse_llm_plan(raw: str, incident_id: str) -> tuple[str, TodoList]:
    """
    Parses LLM output into (understanding_text, TodoList).
    Falls back to a safe default plan if the LLM response is malformed.
    """
    todo_list = TodoList(incident_id=incident_id)

    # Extract JSON block from response (LLMs sometimes wrap it in prose)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return _fallback_plan(raw, incident_id)

    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError:
        return _fallback_plan(raw, incident_id)

    understanding = parsed.get("understanding", "No understanding provided")

    todos = parsed.get("todos", [])
    if not todos:
        return _fallback_plan(raw, incident_id)

    # Sort by priority if present
    todos_sorted = sorted(todos, key=lambda t: t.get("priority", 99))

    for item in todos_sorted:
        description = item.get("description", "").strip()
        assigned_to = item.get("assigned_to", "supervisor").strip()
        if description:
            todo_list.add(description=description, assigned_to=assigned_to)

    return understanding, todo_list


def _fallback_plan(raw: str, incident_id: str) -> tuple[str, TodoList]:
    """Safe default plan when LLM output cannot be parsed."""
    todo_list = TodoList(incident_id=incident_id)
    todo_list.add("Extract file path and line number from stack trace", "observer")
    todo_list.add("Read source code and query KG for callers, tests, past incidents", "detective")
    todo_list.add("Write minimal fix based on root cause", "coder")
    todo_list.add("Validate fix: static analysis, security scan, semantic review", "guardrail")
    todo_list.add("Run test suite, determine deployment decision", "tester")
    todo_list.add("Commit and deliver fix", "committer")
    todo_list.add("Write incident and fix outcome to knowledge graph", "learner")
    return f"[fallback plan — LLM parse failed] raw: {raw[:200]}", todo_list


# ---------------------------------------------------------------------------
# Subagent stubs
# Placeholders — each will be replaced by the real subagent implementation.
# They receive the incident + their specific todo item + the previous result.
# ---------------------------------------------------------------------------

def _run_subagent(agent_name: str, todo_description: str, incident: Incident, context: str) -> str:
    """
    Stub dispatcher — routes to the right subagent by name.
    Replace each branch with the real subagent call.
    """
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
        "supervisor": _stub_supervisor,
    }
    fn = stubs.get(agent_name, _stub_unknown)
    return fn(todo_description, incident, context)


def _stub_observer(todo: str, incident: Incident, ctx: str) -> str:
    s = incident.signal
    if s.stack_trace:
        lines = s.stack_trace.splitlines()
        for line in lines:
            if 'File "' in line:
                return f"[STUB] Extracted: {line.strip()}"
    return f"[STUB] No stack trace — service={s.service}, error={s.error_type}"


def _stub_detective(todo: str, incident: Incident, ctx: str) -> str:
    return (
        f"[STUB] Detective: read source at location from Observer. "
        f"KG query: no past incidents found for {incident.signal.service}. "
        f"Root cause: missing null/guard check."
    )


def _stub_operator(todo: str, incident: Incident, ctx: str) -> str:
    s = incident.signal
    pod = s.pod_name or f"{s.service}-pod"
    return (
        f"[STUB] Operator: pod={pod} status=CrashLoopBackOff "
        f"restart_count={s.occurrence_count} — playbook: rollback"
    )


def _stub_coder(todo: str, incident: Incident, ctx: str) -> str:
    return (
        "[STUB] Coder: wrote null check for inventory return value. "
        "Added test_process_payment_unknown_order. Diff: 6 lines."
    )


def _stub_guardrail(todo: str, incident: Incident, ctx: str) -> str:
    return (
        "[STUB] Guardrail: Layer1=PASS (no syntax errors), "
        "Layer2=PASS (no security issues), Layer3=PASS (fix addresses root cause). "
        "VERDICT: PASS"
    )


def _stub_tester(todo: str, incident: Incident, ctx: str) -> str:
    return (
        "[STUB] Tester: ran pytest — 4 passed. "
        "existing_tests_modified=False, new_tests_added=True. "
        "DECISION: direct_deploy"
    )


def _stub_executor(todo: str, incident: Incident, ctx: str) -> str:
    s = incident.signal
    return (
        f"[STUB] Executor: kubectl rollout undo deployment/{s.service} -n "
        f"{s.namespace or 'default'} — rollout complete."
    )


def _stub_verifier(todo: str, incident: Incident, ctx: str) -> str:
    return (
        "[STUB] Verifier: polled 4 times over 60s. "
        "All pods Running+Ready. Service healthy."
    )


def _stub_committer(todo: str, incident: Incident, ctx: str) -> str:
    return (
        f"[STUB] Committer: created branch fix/{incident.id}. "
        "Committed fix. Opened PR #42. DECISION was direct_deploy → merged to main."
    )


def _stub_learner(todo: str, incident: Incident, ctx: str) -> str:
    return (
        f"[STUB] Learner: wrote Incident({incident.id}) and Fix node to KG. "
        "confidence=1.0 (direct_deploy)."
    )


def _stub_supervisor(todo: str, incident: Incident, ctx: str) -> str:
    return f"[STUB] Supervisor internal step: {todo}"


def _stub_unknown(todo: str, incident: Incident, ctx: str) -> str:
    return f"[STUB] Unknown agent — todo: {todo}"


# ---------------------------------------------------------------------------
# Supervisor main
# ---------------------------------------------------------------------------

class Supervisor:
    """
    Loads the skill for the incident's category, calls the LLM to build a
    dynamic TodoList, then drives each subagent in sequence.
    """

    def __init__(self, llm: Optional[_LLMClient] = None, verbose: bool = True):
        self.llm = llm or _LLMClient()
        self.verbose = verbose

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    def run(self, incident: Incident) -> TodoList:
        self._log(f"\n{'='*60}")
        self._log(f"SUPERVISOR [{incident.id}] — {incident.category.value.upper()} incident")
        self._log(f"Error: {incident.signal.error_type}: {incident.signal.error_message}")
        self._log(f"{'='*60}")

        # 1. Load the skill for this category
        skill = load_skill(incident.category)
        sname = skill_name(incident.category)
        self._log(f"\n[SKILL] Loaded: {sname}")

        # 2. Build the incident description for the LLM
        incident_desc = _describe_incident(incident)

        # 3. Call LLM to create a dynamic TodoList
        self._log("\n[PLAN] Calling LLM to create TodoList...")
        incident.status = IncidentStatus.PLANNING

        prompt = (
            f"Here is the incident you must heal:\n\n"
            f"{incident_desc}\n\n"
            f"Based on the skill above and this specific incident, "
            f"produce your understanding and a targeted TodoList. "
            f"Return valid JSON matching the output format in the skill."
        )

        try:
            raw_plan = self.llm.chat(system=skill, user=prompt)
        except Exception as e:
            self._log(f"[PLAN] LLM call failed: {e} — using fallback plan")
            raw_plan = ""

        understanding, todo_list = _parse_llm_plan(raw_plan, incident.id)
        incident.understanding = understanding
        incident.status = IncidentStatus.IN_PROGRESS

        self._log(f"\n[UNDERSTANDING] {understanding}")
        self._log(f"\n[TODOS] Created {len(todo_list.items)} items:")
        self._log(todo_list.display())

        # 4. Execute each todo in sequence
        self._log("\n[EXECUTE] Running subagents...\n")
        context = ""

        for item in todo_list.items:
            self._log(f"  ○ [{item.assigned_to}] {item.description}")
            item.start()

            try:
                result = _run_subagent(
                    agent_name=item.assigned_to,
                    todo_description=item.description,
                    incident=incident,
                    context=context,
                )
                item.complete(result)
                context = result  # pass output forward as context
                self._log(f"  ✓ [{item.assigned_to}] {result[:100]}")

                # Hard stop: Guardrail security violation
                if item.assigned_to == "guardrail" and "HARD BLOCK" in result:
                    self._log("\n[ESCALATE] Security violation — stopping.")
                    incident.status = IncidentStatus.ESCALATED
                    break

            except Exception as e:
                item.fail(str(e))
                self._log(f"  ✗ [{item.assigned_to}] FAILED: {e}")
                incident.status = IncidentStatus.FAILED
                break

        # 5. Final status
        self._log(f"\n[RESULT] {todo_list.summary()}")
        self._log(todo_list.display())

        if not todo_list.has_failures() and incident.status == IncidentStatus.IN_PROGRESS:
            incident.status = IncidentStatus.RESOLVED
            self._log(f"\n[RESOLVED] Incident {incident.id} resolved.")

        return todo_list
