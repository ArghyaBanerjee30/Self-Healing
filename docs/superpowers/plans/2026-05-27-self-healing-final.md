# Self-Healing System — Implementation Plan (Final)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production self-healing system that detects failures, categorises them (code vs infra vs ambiguous), queries a Neo4j knowledge graph for context, dispatches specialist subagents to fix the issue, gates deployment on confidence score, and feeds every outcome back into the knowledge graph — with zero human involvement for routine failures.

**Architecture:** A LogWatcher emits signals to a two-stage Categoriser. The Categoriser routes to a Supervisor Agent which uses a skill+rule approach: understand deeply first, create a TodoList, then dispatch subagents (Observer→Detective→Coder→**Guardrail**→Tester→Committer for code; Operator→Executor→Verifier for infra). The Guardrail validates every LLM-generated fix through static analysis, security scanning, and semantic review before tests run. The Tester makes the deployment decision deterministically from test change analysis — no LLM scoring. A Learner writes every outcome back to the per-tenant Neo4j knowledge graph. Tests fail → rollback immediately.

**Tech Stack:** Python 3.11+, Neo4j 5.x, sentence-transformers, Ollama llama3.1:8b, FastAPI (demo app), KIND (local K8s), PyGithub, Rich, PyYAML, pytest, SQLite (metadata), subprocess (language-agnostic test runner)

---

## Project File Structure

```
self-healing/
│
├── self-healing.yaml                    # tenant config for the demo project
├── main.py                              # entry point
├── requirements.txt
├── .env.example
│
├── config/
│   └── tenant_registry.py              # loads + validates self-healing.yaml
│
├── knowledge/
│   ├── neo4j_client.py                 # Neo4j connection + query wrapper
│   ├── graph_schema.py                 # node/relationship type constants
│   ├── kg_builder.py                   # builds KG from parsed codebase
│   └── kg_querier.py                   # all read queries (call graph, history, similar)
│
├── parser/
│   ├── code_parser.py                  # AST parser: files→functions→calls (language-agnostic)
│   ├── embedder.py                     # generates embeddings for function bodies
│   └── deployment_hook.py             # triggered on each new deployment
│
├── core/
│   ├── signal.py                       # Signal dataclass (raw error event)
│   ├── incident.py                     # Incident dataclass (enriched, with plan)
│   ├── todo_list.py                    # TodoList + TodoItem types
│   └── llm.py                          # Ollama client wrapper
│
├── categoriser/
│   ├── stage1.py                       # fast signal analysis → category
│   ├── stage2.py                       # parallel code+infra investigation (ambiguous)
│   ├── transient_watcher.py            # watch-and-wait for transient signals
│   └── router.py                       # combines stage1+2, emits routing decision
│
├── agents/
│   ├── supervisor.py                   # brain: understand→plan→dispatch→verify
│   │
│   ├── code/                           # code healing subagents
│   │   ├── observer.py                 # extracts file+line from stack trace
│   │   ├── detective.py                # queries KG, LLM root cause analysis
│   │   ├── coder.py                    # writes fix using LLM + KG context
│   │   ├── guardrail.py               # static analysis, security scan, LLM semantic review
│   │   ├── tester.py                   # runs tests, LLM revises on failure
│   │   └── committer.py               # git branch + commit + PR or direct push
│   │
│   ├── infra/                          # infra healing subagents
│   │   ├── operator.py                 # reads cluster state, identifies fix
│   │   ├── executor.py                 # applies kubectl/helm actions
│   │   └── verifier.py                # confirms service health post-fix
│   │
│   └── shared/
│       ├── learner.py                  # writes outcome to KG
│       ├── learner.py                  # writes outcome to KG
│       └── rollback.py                # git revert + redeploy on failure
│
├── watcher/
│   └── log_watcher.py                  # tails logs, emits signals to categoriser
│
├── ui/
│   └── terminal.py                     # Rich live agent stream display
│
├── demo_app/                           # fake production service with planted bugs
│   ├── app.py
│   ├── payments.py                     # Bug 1: missing null check
│   ├── inventory.py                    # Bug 2: divide by zero
│   ├── checkout.py                     # Bug 3: empty cart crash
│   └── tests/
│       ├── test_payments.py
│       ├── test_inventory.py
│       └── test_checkout.py
│
└── tests/                              # tests for the healing engine itself
    ├── test_signal.py
    ├── test_incident.py
    ├── test_todo_list.py
    ├── test_tenant_registry.py
    ├── test_categoriser_stage1.py
    ├── test_categoriser_stage2.py
    ├── test_kg_builder.py
    ├── test_kg_querier.py
    ├── test_observer.py
    ├── test_detective.py
    ├── test_coder.py
    ├── test_tester.py
    ├── test_committer.py
    ├── test_tester.py
    ├── test_operator.py
    ├── test_executor.py
    ├── test_infra_verifier.py
    ├── test_supervisor.py
    ├── test_learner.py
    └── test_rollback.py
```


---

## Phase 0: Environment Bootstrap

### Task 0.1: Install prerequisites

**Files:** None (system setup)

- [ ] **Step 1: Install system tools**

```bash
brew install python@3.11 git ollama
brew install --cask docker
# Start Docker Desktop, then:
brew install kind kubectl
ollama pull llama3.1:8b
ollama serve &
```

Expected: ollama running at http://localhost:11434

- [ ] **Step 2: Start Neo4j locally via Docker**

```bash
docker run -d \
  --name neo4j-self-healing \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password123 \
  -e NEO4J_PLUGINS='["apoc","graph-data-science"]' \
  neo4j:5.15.0
```

Expected: Neo4j browser at http://localhost:7474 (login: neo4j/password123)

- [ ] **Step 3: Create Python environment**

```bash
cd "/Users/arghyabanerjee/Desktop/Self Healing"
python3.11 -m venv .venv
source .venv/bin/activate
```

- [ ] **Step 4: Create requirements.txt**

```
# LLM
langchain-ollama==0.2.0
langchain-community==0.3.1
httpx==0.27.2

# Knowledge Graph
neo4j==5.15.0
sentence-transformers==3.2.1

# Kubernetes
kubernetes==30.1.0

# GitHub
PyGithub==2.4.0
gitpython==3.1.43

# Config + utilities
pyyaml==6.0.2
python-dotenv==1.0.1
schedule==1.2.2
rich==13.7.1

# Demo app
fastapi==0.115.0
uvicorn==0.30.6

# Testing
pytest==8.3.3
pytest-asyncio==0.24.0
pytest-mock==3.14.0
```

- [ ] **Step 5: Install dependencies**

```bash
pip install -r requirements.txt
```

Expected: all packages install without error

- [ ] **Step 6: Create .env.example**

```bash
# .env.example
GITHUB_TOKEN=ghp_your_token_here
GITHUB_REPO=your-username/self-healing-demo
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password123
```

- [ ] **Step 7: Initialise git and commit**

```bash
git init
git add requirements.txt .env.example
git commit -m "chore: bootstrap self-healing system project"
```

---

## Phase 1: Configuration + Tenant Registry

### Task 1.1: self-healing.yaml for demo project

**Files:**
- Create: `self-healing.yaml`
- Create: `config/tenant_registry.py`
- Create: `tests/test_tenant_registry.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_tenant_registry.py
import pytest
import os
import tempfile
import yaml
from config.tenant_registry import TenantConfig, load_tenant_config

def test_load_valid_config():
    config_data = {
        "project": {
            "id": "project-x",
            "name": "Ecommerce Platform",
            "repo": "github.com/org/project-x"
        },
        "stack": {
            "test_command": "pytest tests/ -v",
            "entry_points": [
                {"service": "payments", "log_pattern": "demo_app/payments.py"}
            ]
        },
        "confidence": {
            "auto_deploy_threshold": 0.85,
            "pr_threshold": 0.60
        },
        "healing": {
            "max_fix_attempts": 3,
            "rollback_on_test_failure": True
        }
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config_data, f)
        tmp_path = f.name
    try:
        config = load_tenant_config(tmp_path)
        assert config.project_id == "project-x"
        assert config.test_command == "pytest tests/ -v"
        assert config.auto_deploy_threshold == 0.85
        assert config.pr_threshold == 0.60
        assert config.max_fix_attempts == 3
        assert config.rollback_on_test_failure is True
        assert len(config.entry_points) == 1
        assert config.entry_points[0]["service"] == "payments"
    finally:
        os.unlink(tmp_path)

def test_load_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_tenant_config("/nonexistent/self-healing.yaml")
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_tenant_registry.py -v
```

Expected: FAIL — module not found

- [ ] **Step 3: Implement TenantConfig and loader**

```python
# config/tenant_registry.py
import os
import yaml
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TenantConfig:
    project_id: str
    project_name: str
    repo: str
    test_command: str
    entry_points: list[dict]
    auto_deploy_threshold: float
    pr_threshold: float
    max_fix_attempts: int
    rollback_on_test_failure: bool
    notify_slack_channel: Optional[str] = None


def load_tenant_config(path: str = "self-healing.yaml") -> TenantConfig:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config not found: {path}")
    with open(path) as f:
        raw = yaml.safe_load(f)
    project = raw["project"]
    stack = raw["stack"]
    confidence = raw["confidence"]
    healing = raw["healing"]
    return TenantConfig(
        project_id=project["id"],
        project_name=project["name"],
        repo=project["repo"],
        test_command=stack["test_command"],
        entry_points=stack.get("entry_points", []),
        auto_deploy_threshold=float(confidence["auto_deploy_threshold"]),
        pr_threshold=float(confidence["pr_threshold"]),
        max_fix_attempts=int(healing["max_fix_attempts"]),
        rollback_on_test_failure=bool(healing.get("rollback_on_test_failure", True)),
        notify_slack_channel=healing.get("notify_slack_channel"),
    )
```

- [ ] **Step 4: Create self-healing.yaml for the demo**

```yaml
# self-healing.yaml
project:
  id: "project-x"
  name: "Ecommerce Demo Platform"
  repo: "your-username/self-healing-demo"

stack:
  test_command: "pytest demo_app/tests/ -v"
  entry_points:
    - service: "payments"
      log_pattern: "demo_app/payments.py"
    - service: "inventory"
      log_pattern: "demo_app/inventory.py"
    - service: "checkout"
      log_pattern: "demo_app/checkout.py"

confidence:
  auto_deploy_threshold: 0.85
  pr_threshold: 0.60

healing:
  max_fix_attempts: 3
  rollback_on_test_failure: true
  notify_slack_channel: "#alerts"
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_tenant_registry.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add config/ self-healing.yaml tests/test_tenant_registry.py
git commit -m "feat: add tenant config loader and self-healing.yaml"
```

---

## Phase 2: Core Types

### Task 2.1: Signal, Incident, TodoList

**Files:**
- Create: `core/signal.py`
- Create: `core/incident.py`
- Create: `core/todo_list.py`
- Create: `tests/test_signal.py`
- Create: `tests/test_incident.py`
- Create: `tests/test_todo_list.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_signal.py
from core.signal import Signal, SignalSource

def test_signal_creation():
    s = Signal(
        source=SignalSource.LOG,
        service="payments",
        error_type="TypeError",
        error_message="'NoneType' object is not subscriptable",
        stack_trace='File "demo_app/payments.py", line 18',
        raw_text="ERROR payments - TypeError ...",
        occurrence_count=1,
    )
    assert s.service == "payments"
    assert s.error_type == "TypeError"
    assert s.occurrence_count == 1
    assert s.is_infra_signal is False
    assert s.is_code_signal is True

def test_signal_infra_detection():
    s = Signal(
        source=SignalSource.KUBERNETES,
        service="payments",
        error_type="CrashLoopBackOff",
        error_message="Back-off restarting failed container",
        stack_trace="",
        raw_text="pod payments-xyz CrashLoopBackOff",
        occurrence_count=5,
    )
    assert s.is_infra_signal is True
    assert s.is_code_signal is False
```

```python
# tests/test_incident.py
from core.incident import Incident, IncidentStatus, IncidentCategory
from core.signal import Signal, SignalSource

def test_incident_from_signal():
    signal = Signal(
        source=SignalSource.LOG,
        service="payments",
        error_type="TypeError",
        error_message="NoneType error",
        stack_trace='File "demo_app/payments.py", line 18',
        raw_text="ERROR...",
        occurrence_count=4,
    )
    inc = Incident.from_signal("inc-001", signal, IncidentCategory.CODE)
    assert inc.id == "inc-001"
    assert inc.category == IncidentCategory.CODE
    assert inc.status == IncidentStatus.DETECTED
    assert inc.pr_url is None
    assert inc.fix_patch is None

def test_incident_status_progression():
    signal = Signal(
        source=SignalSource.LOG,
        service="payments",
        error_type="TypeError",
        error_message="err",
        stack_trace="",
        raw_text="",
        occurrence_count=1,
    )
    inc = Incident.from_signal("inc-002", signal, IncidentCategory.CODE)
    inc.status = IncidentStatus.CODING
    assert inc.status == IncidentStatus.CODING
```

```python
# tests/test_todo_list.py
from core.todo_list import TodoList, TodoStatus

def test_full_lifecycle():
    tl = TodoList(incident_id="inc-001")
    tl.add("Query knowledge graph for context", assigned_to="detective")
    tl.add("Write code fix", assigned_to="coder")
    tl.add("Run test suite", assigned_to="tester")
    assert len(tl.items) == 3
    tl.start(0)
    assert tl.items[0].status == TodoStatus.IN_PROGRESS
    tl.complete(0, result="KG returned 3 similar past fixes")
    assert tl.items[0].status == TodoStatus.DONE
    assert tl.all_done() is False
    tl.complete(1, result="fix written: 4 lines changed")
    tl.complete(2, result="3 tests passed")
    assert tl.all_done() is True

def test_todo_list_fail_item():
    tl = TodoList(incident_id="inc-002")
    tl.add("Write fix", assigned_to="coder")
    tl.fail(0, reason="LLM returned empty response after 3 retries")
    assert tl.items[0].status == TodoStatus.FAILED
    assert tl.all_done() is True
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_signal.py tests/test_incident.py tests/test_todo_list.py -v
```

Expected: FAIL — modules not found

- [ ] **Step 3: Implement Signal**

```python
# core/signal.py
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import Optional

INFRA_ERROR_TYPES = {
    "CrashLoopBackOff", "OOMKilled", "Evicted",
    "FailedScheduling", "Unhealthy", "NodeNotReady",
    "ServiceUnavailable", "ConnectionRefused",
}

CODE_ERROR_TYPES = {
    "TypeError", "ValueError", "KeyError", "AttributeError",
    "IndexError", "ZeroDivisionError", "RuntimeError",
    "AssertionError", "NameError", "ImportError",
}


class SignalSource(Enum):
    LOG = "log"
    KUBERNETES = "kubernetes"
    WEBHOOK = "webhook"


@dataclass
class Signal:
    source: SignalSource
    service: str
    error_type: str
    error_message: str
    stack_trace: str
    raw_text: str
    occurrence_count: int
    timestamp: datetime = field(default_factory=datetime.utcnow)
    pod_name: Optional[str] = None
    namespace: Optional[str] = None

    @property
    def is_code_signal(self) -> bool:
        return (
            self.error_type in CODE_ERROR_TYPES
            or bool(self.stack_trace.strip())
        )

    @property
    def is_infra_signal(self) -> bool:
        return (
            self.error_type in INFRA_ERROR_TYPES
            or self.source == SignalSource.KUBERNETES
        )
```

- [ ] **Step 4: Implement Incident**

```python
# core/incident.py
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime
from core.signal import Signal


class IncidentCategory(Enum):
    CODE = "code"
    INFRA = "infra"
    BOTH = "both"
    TRANSIENT = "transient"


class IncidentStatus(Enum):
    DETECTED = "detected"
    CATEGORISED = "categorised"
    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    CODING = "coding"
    TESTING = "testing"
    SCORING = "scoring"
    COMMITTING = "committing"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    ESCALATED = "escalated"


@dataclass
class Incident:
    id: str
    signal: Signal
    category: IncidentCategory
    status: IncidentStatus = IncidentStatus.DETECTED
    kg_context: dict = field(default_factory=dict)
    root_cause_analysis: Optional[str] = None
    buggy_code: Optional[str] = None
    fixed_code: Optional[str] = None
    fix_patch: Optional[str] = None
    test_output: Optional[str] = None
    # Deployment decision — set by TesterAgent, read by Supervisor
    deploy_decision: Optional[str] = None          # "direct_deploy" | "open_pr" | "rollback"
    existing_tests_modified: Optional[bool] = None # True = existing test file was touched
    new_tests_added: Optional[bool] = None         # True = new test added alongside fix
    pr_url: Optional[str] = None
    pr_branch: Optional[str] = None
    infra_action_taken: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None

    @classmethod
    def from_signal(
        cls,
        incident_id: str,
        signal: Signal,
        category: IncidentCategory,
    ) -> "Incident":
        return cls(id=incident_id, signal=signal, category=category)
```

- [ ] **Step 5: Implement TodoList**

```python
# core/todo_list.py
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TodoStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


@dataclass
class TodoItem:
    description: str
    assigned_to: Optional[str] = None
    status: TodoStatus = TodoStatus.PENDING
    result: Optional[str] = None


@dataclass
class TodoList:
    incident_id: str
    items: list[TodoItem] = field(default_factory=list)

    def add(self, description: str, assigned_to: Optional[str] = None) -> int:
        self.items.append(TodoItem(description=description, assigned_to=assigned_to))
        return len(self.items) - 1

    def start(self, index: int) -> None:
        self.items[index].status = TodoStatus.IN_PROGRESS

    def complete(self, index: int, result: str) -> None:
        self.items[index].status = TodoStatus.DONE
        self.items[index].result = result

    def fail(self, index: int, reason: str) -> None:
        self.items[index].status = TodoStatus.FAILED
        self.items[index].result = reason

    def all_done(self) -> bool:
        return all(
            i.status in (TodoStatus.DONE, TodoStatus.FAILED)
            for i in self.items
        )

    def summary(self) -> str:
        done = sum(1 for i in self.items if i.status == TodoStatus.DONE)
        failed = sum(1 for i in self.items if i.status == TodoStatus.FAILED)
        total = len(self.items)
        return f"{done}/{total} done, {failed} failed"

    def render(self) -> list[dict]:
        return [
            {
                "index": i,
                "description": item.description,
                "assigned_to": item.assigned_to,
                "status": item.status.value,
                "result": item.result,
            }
            for i, item in enumerate(self.items)
        ]
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_signal.py tests/test_incident.py tests/test_todo_list.py -v
```

Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add core/ tests/test_signal.py tests/test_incident.py tests/test_todo_list.py
git commit -m "feat: add Signal, Incident, TodoList core types"
```


### Task 2.2: LLM Client

**Files:**
- Create: `core/llm.py`
- Create: `tests/test_llm.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_llm.py
from unittest.mock import patch, MagicMock
from core.llm import OllamaClient

def test_chat_returns_string():
    client = OllamaClient()
    with patch("httpx.post") as mock:
        mock.return_value = MagicMock(
            status_code=200,
            json=lambda: {"message": {"content": "root cause: null check missing"}}
        )
        result = client.chat("Analyse this error")
        assert isinstance(result, str)
        assert len(result) > 0

def test_create_todos_returns_list():
    client = OllamaClient()
    with patch("httpx.post") as mock:
        mock.return_value = MagicMock(
            status_code=200,
            json=lambda: {"message": {"content": "1. Read logs\n2. Find bug\n3. Write fix\n4. Test\n5. Commit"}}
        )
        todos = client.create_todos("TypeError in payments service")
        assert isinstance(todos, list)
        assert len(todos) >= 3

def test_write_code_fix_strips_fences():
    client = OllamaClient()
    with patch("httpx.post") as mock:
        mock.return_value = MagicMock(
            status_code=200,
            json=lambda: {"message": {"content": "```python\nif x is None:\n    raise ValueError('null')\n```"}}
        )
        fix = client.write_code_fix(
            buggy_code="total = x['price']",
            root_cause="x can be None",
            error="TypeError",
            file_path="payments.py",
        )
        assert "```" not in fix
        assert "if x is None" in fix
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_llm.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement OllamaClient**

```python
# core/llm.py
import re
import os
import httpx
from typing import Optional


class OllamaClient:
    def __init__(
        self,
        model: str = None,
        base_url: str = None,
    ):
        self.model = model or os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
        self.base_url = base_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")

    def chat(self, prompt: str, system: Optional[str] = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = httpx.post(
            f"{self.base_url}/api/chat",
            json={"model": self.model, "messages": messages, "stream": False},
            timeout=180.0,
        )
        response.raise_for_status()
        return response.json()["message"]["content"]

    def create_todos(self, incident_summary: str) -> list[str]:
        system = (
            "You are a senior SRE creating a repair plan. "
            "Output a numbered list of 5 concrete steps to diagnose and fix this incident. "
            "Steps must cover: understand, investigate, fix, test, deliver. "
            "Output ONLY the numbered list, nothing else."
        )
        raw = self.chat(incident_summary, system=system)
        todos = []
        for line in raw.strip().split("\n"):
            line = line.strip()
            if line and line[0].isdigit():
                cleaned = re.sub(r"^\d+[\.\)]\s*", "", line).strip()
                if cleaned:
                    todos.append(cleaned)
        return todos if todos else [
            "Read signal and extract file and line from stack trace",
            "Query knowledge graph for context and similar past incidents",
            "Write minimal code fix based on root cause analysis",
            "Run test suite to validate fix correctness",
            "Commit fix and deliver via PR or direct deploy",
        ]

    def analyse_stack_trace(
        self, stack_trace: str, error_message: str, source_code: str = ""
    ) -> dict:
        system = (
            "You are a senior engineer performing root cause analysis. "
            "Given an error message, stack trace, and optionally the source code, "
            "identify the root cause. Respond in EXACTLY this format:\n"
            "FILE: <filepath>\n"
            "LINE: <number>\n"
            "ROOT_CAUSE: <one sentence>\n"
            "PATTERN: <e.g. missing null check, divide by zero, missing guard clause>\n"
            "CERTAINTY: <high|medium|low>"
        )
        prompt = (
            f"Error: {error_message}\n\n"
            f"Stack trace:\n{stack_trace}\n\n"
            f"Source code:\n{source_code[:2000] if source_code else 'not provided'}"
        )
        raw = self.chat(prompt, system=system)
        result = {
            "file": None, "line": None, "root_cause": None,
            "pattern": None, "certainty": "low", "raw": raw
        }
        for line in raw.split("\n"):
            if line.startswith("FILE:"):
                result["file"] = line.split(":", 1)[1].strip()
            elif line.startswith("LINE:"):
                val = line.split(":", 1)[1].strip()
                result["line"] = int(val) if val.isdigit() else None
            elif line.startswith("ROOT_CAUSE:"):
                result["root_cause"] = line.split(":", 1)[1].strip()
            elif line.startswith("PATTERN:"):
                result["pattern"] = line.split(":", 1)[1].strip()
            elif line.startswith("CERTAINTY:"):
                result["certainty"] = line.split(":", 1)[1].strip().lower()
        return result

    def write_code_fix(
        self,
        buggy_code: str,
        root_cause: str,
        error: str,
        file_path: str = "",
        kg_context: str = "",
    ) -> str:
        system = (
            "You are an expert software engineer. "
            "Write ONLY the corrected Python code. "
            "Rules: minimal change, preserve all function signatures, "
            "add proper error handling matching the project's patterns, "
            "no explanations, no markdown fences, raw code only."
        )
        prompt = (
            f"File: {file_path}\n"
            f"Error: {error}\n"
            f"Root cause: {root_cause}\n"
            f"Project context from knowledge graph:\n{kg_context}\n\n"
            f"Buggy code:\n{buggy_code}\n\n"
            "Write the fixed version:"
        )
        raw = self.chat(prompt, system=system)
        raw = re.sub(r"^```\w*\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw.strip())
        return raw.strip()

    def generate_pr_description(
        self, incident_id: str, root_cause: str,
        fix_summary: str, test_output: str
    ) -> str:
        system = (
            "Write a concise, professional GitHub PR description for "
            "an autonomous self-healing fix. Cover: what broke, why, what changed."
        )
        prompt = (
            f"Incident: {incident_id}\n"
            f"Root cause: {root_cause}\n"
            f"Fix: {fix_summary}\n"
            f"Tests: {test_output[:300]}"
        )
        return self.chat(prompt, system=system)

    def score_fix_certainty(self, root_cause: str, fix_code: str) -> float:
        system = (
            "Rate your confidence in this code fix on a scale 0.0 to 1.0. "
            "Output ONLY a decimal number between 0.0 and 1.0, nothing else."
        )
        prompt = f"Root cause: {root_cause}\n\nFix applied:\n{fix_code}"
        raw = self.chat(prompt, system=system).strip()
        try:
            score = float(re.search(r"0?\.\d+|[01]\.0*", raw).group())
            return max(0.0, min(1.0, score))
        except Exception:
            return 0.5
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_llm.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/llm.py tests/test_llm.py
git commit -m "feat: add Ollama LLM client with RCA, fix generation, and PR description"
```

---

## Phase 2b: GitHub Tools

### Task 2b.1: GitHubTools wrapper

**Files:**
- Create: `core/github_tools.py`
- Create: `tests/test_github_tools.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_github_tools.py
from unittest.mock import MagicMock, patch
from core.github_tools import GitHubTools

def test_create_branch_calls_github_api():
    mock_repo = MagicMock()
    mock_repo.get_branch.return_value = MagicMock(commit=MagicMock(sha="abc123"))
    mock_repo.create_git_ref = MagicMock()

    tools = GitHubTools.__new__(GitHubTools)
    tools.repo = mock_repo

    sha = tools.create_branch("fix/inc-001-type-error")
    mock_repo.create_git_ref.assert_called_once()
    assert sha == "abc123"

def test_commit_fix_calls_update_file():
    mock_repo = MagicMock()
    mock_file = MagicMock()
    mock_file.sha = "file-sha-123"
    mock_repo.get_contents.return_value = mock_file
    mock_repo.update_file = MagicMock()

    tools = GitHubTools.__new__(GitHubTools)
    tools.repo = mock_repo

    tools.commit_fix(
        branch="fix/inc-001",
        file_path="demo_app/payments.py",
        new_content="def process_payment(): pass",
        commit_message="fix: handle None inventory",
    )
    mock_repo.update_file.assert_called_once()

def test_open_pr_returns_url():
    mock_repo = MagicMock()
    mock_pr = MagicMock()
    mock_pr.html_url = "https://github.com/org/repo/pull/42"
    mock_repo.create_pull.return_value = mock_pr

    tools = GitHubTools.__new__(GitHubTools)
    tools.repo = mock_repo

    url = tools.open_pr(
        branch="fix/inc-001",
        title="fix(payments): null check",
        body="## Fix\nAdded null guard.",
    )
    assert url == "https://github.com/org/repo/pull/42"
    mock_repo.create_pull.assert_called_once()
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_github_tools.py -v
```

Expected: FAIL — module not found

- [ ] **Step 3: Implement GitHubTools**

```python
# core/github_tools.py
import os
from github import Github, GithubException


class GitHubTools:
    def __init__(self, token: str = None, repo_name: str = None):
        token = token or os.environ.get("GITHUB_TOKEN", "")
        repo_name = repo_name or os.environ.get("GITHUB_REPO", "")
        self.gh = Github(token)
        self.repo = self.gh.get_repo(repo_name)

    def create_branch(self, branch_name: str, base_branch: str = "main") -> str:
        """Creates a fix branch from main. Returns base commit SHA."""
        base = self.repo.get_branch(base_branch)
        sha = base.commit.sha
        try:
            self.repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=sha)
        except GithubException as e:
            if e.status != 422:   # 422 = branch already exists, safe to ignore
                raise
        return sha

    def get_file_content(self, file_path: str, branch: str = "main") -> str:
        """Returns current file content from the given branch."""
        contents = self.repo.get_contents(file_path, ref=branch)
        return contents.decoded_content.decode("utf-8")

    def commit_fix(
        self,
        branch: str,
        file_path: str,
        new_content: str,
        commit_message: str,
    ) -> None:
        """Commits the fixed file content to the fix branch."""
        file = self.repo.get_contents(file_path, ref=branch)
        self.repo.update_file(
            path=file_path,
            message=commit_message,
            content=new_content,
            sha=file.sha,
            branch=branch,
        )

    def open_pr(
        self,
        branch: str,
        title: str,
        body: str,
        base_branch: str = "main",
    ) -> str:
        """Opens a GitHub PR and returns the PR URL."""
        pr = self.repo.create_pull(
            title=title,
            body=body,
            head=branch,
            base=base_branch,
        )
        return pr.html_url
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_github_tools.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/github_tools.py tests/test_github_tools.py
git commit -m "feat: add GitHub tools — branch, commit, and PR creation"
```

---

## Phase 3: Neo4j Knowledge Graph

### Task 3.1: Neo4j client and graph schema

**Files:**
- Create: `knowledge/graph_schema.py`
- Create: `knowledge/neo4j_client.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_neo4j_client.py
from unittest.mock import MagicMock, patch
from knowledge.neo4j_client import Neo4jClient

def test_client_connects_and_runs_query():
    with patch("neo4j.GraphDatabase.driver") as mock_driver:
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.return_value = [{"n": "test"}]
        mock_driver.return_value.session.return_value = mock_session

        client = Neo4jClient(uri="bolt://localhost:7687", user="neo4j", password="pw")
        results = client.query("MATCH (n) RETURN n LIMIT 1")
        assert isinstance(results, list)
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_neo4j_client.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement graph schema constants**

```python
# knowledge/graph_schema.py

# Node labels
FILE = "File"
FUNCTION = "Function"
CLASS = "Class"
MODULE = "Module"
TEST = "Test"
INCIDENT = "Incident"
FIX = "Fix"

# Relationship types
CONTAINS = "CONTAINS"
CALLS = "CALLS"
IMPORTS = "IMPORTS"
INHERITS = "INHERITS"
TESTS = "TESTS"
OCCURRED_IN = "OCCURRED_IN"
FIXED_BY = "FIXED_BY"
APPLIED_TO = "APPLIED_TO"
SIMILAR_TO = "SIMILAR_TO"
```

- [ ] **Step 4: Implement Neo4jClient**

```python
# knowledge/neo4j_client.py
import os
from typing import Any
from neo4j import GraphDatabase


class Neo4jClient:
    def __init__(
        self,
        uri: str = None,
        user: str = None,
        password: str = None,
    ):
        self.uri = uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.environ.get("NEO4J_USER", "neo4j")
        self.password = password or os.environ.get("NEO4J_PASSWORD", "password123")
        self.driver = GraphDatabase.driver(
            self.uri, auth=(self.user, self.password)
        )

    def query(self, cypher: str, params: dict = None) -> list[dict]:
        with self.driver.session() as session:
            result = session.run(cypher, params or {})
            return [dict(record) for record in result]

    def write(self, cypher: str, params: dict = None) -> None:
        with self.driver.session() as session:
            session.run(cypher, params or {})

    def close(self) -> None:
        self.driver.close()

    def create_vector_index(self, project_id: str) -> None:
        self.write(f"""
            CREATE VECTOR INDEX function_embeddings_{project_id.replace('-','_')}
            IF NOT EXISTS
            FOR (f:Function)
            ON f.embedding
            OPTIONS {{indexConfig: {{
                `vector.dimensions`: 384,
                `vector.similarity_function`: 'cosine'
            }}}}
        """)

    def vector_search(
        self,
        project_id: str,
        embedding: list[float],
        top_k: int = 5,
    ) -> list[dict]:
        return self.query("""
            CALL db.index.vector.queryNodes(
                $index_name, $top_k, $embedding
            ) YIELD node, score
            WHERE node.project_id = $project_id
            RETURN node.name AS name,
                   node.file AS file,
                   node.body AS body,
                   score
            ORDER BY score DESC
        """, {
            "index_name": f"function_embeddings_{project_id.replace('-','_')}",
            "top_k": top_k,
            "embedding": embedding,
            "project_id": project_id,
        })
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_neo4j_client.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add knowledge/graph_schema.py knowledge/neo4j_client.py tests/test_neo4j_client.py
git commit -m "feat: add Neo4j client and graph schema constants"
```

---

### Task 3.2: Deployment parser — builds KG from codebase

**Files:**
- Create: `parser/code_parser.py`
- Create: `parser/embedder.py`
- Create: `knowledge/kg_builder.py`
- Create: `parser/deployment_hook.py`
- Create: `tests/test_kg_builder.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_kg_builder.py
import os
import tempfile
from unittest.mock import MagicMock
from knowledge.kg_builder import KGBuilder

def test_kg_builder_indexes_python_file():
    python_code = '''
def process_payment(order_id: str) -> dict:
    inventory = get_inventory(order_id)
    total = inventory["price"] * inventory["quantity"]
    return {"status": "ok", "total": total}

def get_inventory(order_id: str):
    return {"price": 10.0, "quantity": 2}
'''
    with tempfile.TemporaryDirectory() as tmpdir:
        fpath = os.path.join(tmpdir, "payments.py")
        with open(fpath, "w") as f:
            f.write(python_code)

        mock_neo4j = MagicMock()
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [0.1] * 384

        builder = KGBuilder(
            neo4j_client=mock_neo4j,
            embedder=mock_embedder,
            project_id="project-x",
        )
        result = builder.index_file(fpath)

        assert result["functions_found"] == 2
        assert result["file_path"] == fpath
        assert mock_neo4j.write.call_count >= 2
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_kg_builder.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement code parser**

```python
# parser/code_parser.py
import ast
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParsedFunction:
    name: str
    file_path: str
    line_start: int
    line_end: int
    body: str
    calls: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)


@dataclass
class ParsedFile:
    path: str
    language: str
    functions: list[ParsedFunction] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)


class CodeParser:
    def parse_file(self, file_path: str) -> Optional[ParsedFile]:
        ext = os.path.splitext(file_path)[1]
        if ext == ".py":
            return self._parse_python(file_path)
        return None

    def _parse_python(self, file_path: str) -> ParsedFile:
        with open(file_path) as f:
            source = f.read()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return ParsedFile(path=file_path, language="python")

        lines = source.split("\n")
        parsed = ParsedFile(path=file_path, language="python")

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    parsed.imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    parsed.imports.append(node.module)
            elif isinstance(node, ast.ClassDef):
                parsed.classes.append(node.name)
            elif isinstance(node, ast.FunctionDef):
                line_start = node.lineno
                line_end = node.end_lineno or node.lineno
                body = "\n".join(lines[line_start - 1:line_end])
                calls = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name):
                            calls.append(child.func.id)
                        elif isinstance(child.func, ast.Attribute):
                            calls.append(child.func.attr)
                decorators = [
                    d.id if isinstance(d, ast.Name) else
                    d.attr if isinstance(d, ast.Attribute) else str(d)
                    for d in node.decorator_list
                ]
                parsed.functions.append(ParsedFunction(
                    name=node.name,
                    file_path=file_path,
                    line_start=line_start,
                    line_end=line_end,
                    body=body,
                    calls=calls,
                    decorators=decorators,
                ))
        return parsed
```

- [ ] **Step 4: Implement embedder**

```python
# parser/embedder.py
from sentence_transformers import SentenceTransformer


class CodeEmbedder:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        # all-MiniLM-L6-v2: 384 dimensions, fast, runs locally
        self.model = SentenceTransformer(model_name)

    def embed(self, text: str) -> list[float]:
        return self.model.encode(text, normalize_embeddings=True).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(
            texts, normalize_embeddings=True, batch_size=32
        ).tolist()
```

- [ ] **Step 5: Implement KGBuilder**

```python
# knowledge/kg_builder.py
import os
from parser.code_parser import CodeParser
from parser.embedder import CodeEmbedder
from knowledge.neo4j_client import Neo4jClient
from knowledge import graph_schema as gs


class KGBuilder:
    def __init__(
        self,
        neo4j_client: Neo4jClient = None,
        embedder: CodeEmbedder = None,
        project_id: str = "default",
    ):
        self.neo4j = neo4j_client or Neo4jClient()
        self.embedder = embedder or CodeEmbedder()
        self.project_id = project_id
        self.parser = CodeParser()

    def index_file(self, file_path: str) -> dict:
        parsed = self.parser.parse_file(file_path)
        if not parsed or not parsed.functions:
            return {"file_path": file_path, "functions_found": 0}

        # Upsert File node
        self.neo4j.write(f"""
            MERGE (f:{gs.FILE} {{path: $path, project_id: $pid}})
            SET f.language = $lang
        """, {"path": file_path, "pid": self.project_id, "lang": parsed.language})

        # Upsert each Function node with embedding
        for func in parsed.functions:
            embedding = self.embedder.embed(func.body)
            self.neo4j.write(f"""
                MERGE (fn:{gs.FUNCTION} {{
                    name: $name,
                    file: $file,
                    project_id: $pid
                }})
                SET fn.line_start = $ls,
                    fn.line_end = $le,
                    fn.body = $body,
                    fn.embedding = $emb
            """, {
                "name": func.name,
                "file": file_path,
                "pid": self.project_id,
                "ls": func.line_start,
                "le": func.line_end,
                "body": func.body,
                "emb": embedding,
            })

            # File CONTAINS Function
            self.neo4j.write(f"""
                MATCH (f:{gs.FILE} {{path: $file, project_id: $pid}})
                MATCH (fn:{gs.FUNCTION} {{name: $name, file: $file, project_id: $pid}})
                MERGE (f)-[:{gs.CONTAINS}]->(fn)
            """, {"file": file_path, "pid": self.project_id, "name": func.name})

            # Function CALLS relationships
            for callee in func.calls:
                self.neo4j.write(f"""
                    MATCH (caller:{gs.FUNCTION} {{
                        name: $caller_name, file: $file, project_id: $pid
                    }})
                    MERGE (callee:{gs.FUNCTION} {{
                        name: $callee_name, project_id: $pid
                    }})
                    MERGE (caller)-[:{gs.CALLS}]->(callee)
                """, {
                    "caller_name": func.name,
                    "callee_name": callee,
                    "file": file_path,
                    "pid": self.project_id,
                })

        return {"file_path": file_path, "functions_found": len(parsed.functions)}

    def index_directory(self, dir_path: str) -> dict:
        total_files = 0
        total_functions = 0
        for root, _, files in os.walk(dir_path):
            for fname in files:
                if fname.endswith((".py", ".js", ".ts", ".java")):
                    fpath = os.path.join(root, fname)
                    result = self.index_file(fpath)
                    total_files += 1
                    total_functions += result.get("functions_found", 0)
        return {"files_indexed": total_files, "functions_indexed": total_functions}
```

- [ ] **Step 6: Implement deployment hook**

```python
# parser/deployment_hook.py
"""
Called after every new deployment.
Re-indexes the codebase into Neo4j so the KG is always current.

Usage:
  python parser/deployment_hook.py --project-dir ./demo_app --config self-healing.yaml
"""
import argparse
import time
from config.tenant_registry import load_tenant_config
from knowledge.neo4j_client import Neo4jClient
from knowledge.kg_builder import KGBuilder
from parser.embedder import CodeEmbedder
from rich.console import Console

console = Console()


def run_deployment_parse(project_dir: str, config_path: str = "self-healing.yaml") -> dict:
    config = load_tenant_config(config_path)
    console.print(
        f"\n[bold yellow]DEPLOYMENT PARSER[/] "
        f"Indexing {project_dir} for project [{config.project_id}]..."
    )
    start = time.time()
    neo4j = Neo4jClient()
    embedder = CodeEmbedder()
    builder = KGBuilder(
        neo4j_client=neo4j,
        embedder=embedder,
        project_id=config.project_id,
    )
    neo4j.create_vector_index(config.project_id)
    result = builder.index_directory(project_dir)
    elapsed = time.time() - start
    console.print(
        f"[bold green]KG updated:[/] "
        f"{result['files_indexed']} files, "
        f"{result['functions_indexed']} functions indexed in {elapsed:.1f}s"
    )
    neo4j.close()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--config", default="self-healing.yaml")
    args = parser.parse_args()
    run_deployment_parse(args.project_dir, args.config)
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
pytest tests/test_kg_builder.py -v
```

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add parser/ knowledge/kg_builder.py knowledge/neo4j_client.py \
        knowledge/graph_schema.py tests/test_kg_builder.py
git commit -m "feat: add deployment parser, KG builder, and code embedder"
```


### Task 3.3: KG Querier — reads context for the Detective

**Files:**
- Create: `knowledge/kg_querier.py`
- Create: `tests/test_kg_querier.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_kg_querier.py
from unittest.mock import MagicMock
from knowledge.kg_querier import KGQuerier

def test_querier_gets_function_context():
    mock_neo4j = MagicMock()
    mock_neo4j.query.return_value = [
        {
            "callers": ["checkout_handler"],
            "callees": ["get_inventory"],
            "tests": ["test_process_payment"],
            "past_incidents": [],
            "past_fixes": [],
        }
    ]
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [0.1] * 384

    querier = KGQuerier(
        neo4j_client=mock_neo4j,
        embedder=mock_embedder,
        project_id="project-x",
    )
    context = querier.get_function_context("process_payment", "demo_app/payments.py")
    assert "callers" in context
    assert "callees" in context

def test_querier_finds_similar_incidents():
    mock_neo4j = MagicMock()
    mock_neo4j.vector_search.return_value = [
        {"name": "process_payment", "file": "payments.py", "body": "def process_payment...", "score": 0.95}
    ]
    mock_neo4j.query.return_value = []
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [0.1] * 384

    querier = KGQuerier(
        neo4j_client=mock_neo4j,
        embedder=mock_embedder,
        project_id="project-x",
    )
    similar = querier.find_similar_incidents("TypeError NoneType stack trace text")
    assert isinstance(similar, list)
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_kg_querier.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement KGQuerier**

```python
# knowledge/kg_querier.py
from knowledge.neo4j_client import Neo4jClient
from parser.embedder import CodeEmbedder
from knowledge import graph_schema as gs


class KGQuerier:
    def __init__(
        self,
        neo4j_client: Neo4jClient = None,
        embedder: CodeEmbedder = None,
        project_id: str = "default",
    ):
        self.neo4j = neo4j_client or Neo4jClient()
        self.embedder = embedder or CodeEmbedder()
        self.project_id = project_id

    def get_function_context(self, function_name: str, file_path: str) -> dict:
        """
        Returns the full neighbourhood of a function:
        callers, callees, tests covering it, past incidents, past fixes.
        This is the core query the Detective uses.
        """
        results = self.neo4j.query("""
            MATCH (fn:Function {name: $name, file: $file, project_id: $pid})
            OPTIONAL MATCH (caller:Function)-[:CALLS]->(fn)
            OPTIONAL MATCH (fn)-[:CALLS]->(callee:Function)
            OPTIONAL MATCH (t:Test)-[:TESTS]->(fn)
            OPTIONAL MATCH (i:Incident)-[:OCCURRED_IN]->(fn)
            OPTIONAL MATCH (i)-[:FIXED_BY]->(fix:Fix)
            RETURN
                collect(DISTINCT caller.name) AS callers,
                collect(DISTINCT callee.name) AS callees,
                collect(DISTINCT t.name) AS tests,
                collect(DISTINCT {
                    id: i.id,
                    type: i.error_type,
                    resolved: i.resolved
                }) AS past_incidents,
                collect(DISTINCT {
                    patch: fix.patch,
                    confidence: fix.confidence
                }) AS past_fixes
        """, {
            "name": function_name,
            "file": file_path,
            "pid": self.project_id,
        })
        if results:
            return results[0]
        return {
            "callers": [], "callees": [], "tests": [],
            "past_incidents": [], "past_fixes": [],
        }

    def find_similar_incidents(self, query_text: str, top_k: int = 3) -> list[dict]:
        """
        Finds past incidents with similar stack traces using vector similarity.
        Returns the top-k most similar past incidents with their fixes.
        """
        embedding = self.embedder.embed(query_text)
        similar_functions = self.neo4j.vector_search(
            self.project_id, embedding, top_k=top_k
        )
        if not similar_functions:
            return []
        results = []
        for fn in similar_functions:
            incidents = self.neo4j.query("""
                MATCH (fn:Function {name: $name, project_id: $pid})
                MATCH (i:Incident)-[:OCCURRED_IN]->(fn)
                MATCH (i)-[:FIXED_BY]->(fix:Fix)
                RETURN i.id AS incident_id,
                       i.error_type AS error_type,
                       fix.patch AS fix_patch,
                       fix.confidence AS confidence
                ORDER BY fix.confidence DESC
                LIMIT 3
            """, {"name": fn["name"], "pid": self.project_id})
            results.extend(incidents)
        return results

    def get_call_chain(self, function_name: str, max_depth: int = 4) -> list[dict]:
        """
        Returns the full call chain up to max_depth hops from the function.
        Used to understand blast radius of a bug.
        """
        return self.neo4j.query("""
            MATCH path = (fn:Function {name: $name, project_id: $pid})
                         -[:CALLS*1..$depth]->(dep:Function)
            RETURN [n IN nodes(path) | n.name] AS chain,
                   length(path) AS depth
            ORDER BY depth ASC
            LIMIT 20
        """, {
            "name": function_name,
            "pid": self.project_id,
            "depth": max_depth,
        })

    def get_tests_for_function(self, function_name: str) -> list[str]:
        """Returns test function names that cover this function."""
        results = self.neo4j.query("""
            MATCH (t:Test)-[:TESTS]->(fn:Function {name: $name, project_id: $pid})
            RETURN t.name AS test_name, t.file AS test_file
        """, {"name": function_name, "pid": self.project_id})
        return [r["test_name"] for r in results]

    def save_incident(self, incident_id: str, function_name: str,
                       file_path: str, error_type: str) -> None:
        self.neo4j.write("""
            MERGE (i:Incident {id: $id, project_id: $pid})
            SET i.error_type = $error_type, i.resolved = false
            WITH i
            MATCH (fn:Function {name: $name, file: $file, project_id: $pid})
            MERGE (i)-[:OCCURRED_IN]->(fn)
        """, {
            "id": incident_id,
            "pid": self.project_id,
            "error_type": error_type,
            "name": function_name,
            "file": file_path,
        })

    def save_fix(self, incident_id: str, function_name: str, file_path: str,
                  patch: str, confidence: float) -> None:
        self.neo4j.write("""
            MATCH (i:Incident {id: $id, project_id: $pid})
            MERGE (fix:Fix {incident_id: $id, project_id: $pid})
            SET fix.patch = $patch, fix.confidence = $confidence
            MERGE (i)-[:FIXED_BY]->(fix)
            WITH fix
            MATCH (fn:Function {name: $name, file: $file, project_id: $pid})
            MERGE (fix)-[:APPLIED_TO]->(fn)
            WITH i
            MATCH (i)
            SET i.resolved = true
        """, {
            "id": incident_id,
            "pid": self.project_id,
            "patch": patch,
            "confidence": confidence,
            "name": function_name,
            "file": file_path,
        })
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_kg_querier.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add knowledge/kg_querier.py tests/test_kg_querier.py
git commit -m "feat: add KG querier with call graph, similar incident, and fix history queries"
```

---

## Phase 4: Categoriser

### Task 4.1: Stage 1 — fast signal classifier

**Files:**
- Create: `categoriser/stage1.py`
- Create: `tests/test_categoriser_stage1.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_categoriser_stage1.py
from core.signal import Signal, SignalSource
from core.incident import IncidentCategory
from categoriser.stage1 import Stage1Categoriser

def test_classifies_code_error():
    signal = Signal(
        source=SignalSource.LOG,
        service="payments",
        error_type="TypeError",
        error_message="NoneType not subscriptable",
        stack_trace='File "demo_app/payments.py", line 18',
        raw_text="ERROR ...",
        occurrence_count=4,
    )
    cat = Stage1Categoriser()
    result = cat.classify(signal)
    assert result.category == IncidentCategory.CODE
    assert result.confidence >= 0.8

def test_classifies_infra_error():
    signal = Signal(
        source=SignalSource.KUBERNETES,
        service="payments",
        error_type="CrashLoopBackOff",
        error_message="Back-off restarting failed container",
        stack_trace="",
        raw_text="pod payments-xyz CrashLoopBackOff",
        occurrence_count=8,
    )
    cat = Stage1Categoriser()
    result = cat.classify(signal)
    assert result.category == IncidentCategory.INFRA
    assert result.confidence >= 0.8

def test_classifies_ambiguous():
    signal = Signal(
        source=SignalSource.LOG,
        service="payments",
        error_type="ConnectionError",
        error_message="database unreachable",
        stack_trace='File "demo_app/payments.py", line 45',
        raw_text="ERROR ConnectionError ...",
        occurrence_count=6,
    )
    cat = Stage1Categoriser()
    result = cat.classify(signal)
    assert result.category == IncidentCategory.BOTH

def test_classifies_transient():
    signal = Signal(
        source=SignalSource.LOG,
        service="payments",
        error_type="ConnectionError",
        error_message="timeout",
        stack_trace="",
        raw_text="WARN timeout",
        occurrence_count=1,
    )
    cat = Stage1Categoriser()
    result = cat.classify(signal)
    assert result.category == IncidentCategory.TRANSIENT
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_categoriser_stage1.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement Stage1Categoriser**

```python
# categoriser/stage1.py
from dataclasses import dataclass
from core.signal import Signal, INFRA_ERROR_TYPES, CODE_ERROR_TYPES
from core.incident import IncidentCategory

AMBIGUOUS_ERROR_TYPES = {
    "ConnectionError", "TimeoutError", "ConnectionRefusedError",
    "OSError", "IOError", "SocketError",
}

TRANSIENT_THRESHOLD = 3  # fewer than this = possible transient


@dataclass
class ClassificationResult:
    category: IncidentCategory
    confidence: float
    reason: str


class Stage1Categoriser:
    """
    Fast first-pass classifier. Runs in < 1 second.
    No LLM, no external calls — pure signal analysis.
    """

    def classify(self, signal: Signal) -> ClassificationResult:
        # Transient check first
        if signal.occurrence_count < TRANSIENT_THRESHOLD and not signal.stack_trace:
            return ClassificationResult(
                category=IncidentCategory.TRANSIENT,
                confidence=0.7,
                reason=f"Only {signal.occurrence_count} occurrences, no stack trace",
            )

        has_code = signal.is_code_signal
        has_infra = signal.is_infra_signal
        is_ambiguous_type = signal.error_type in AMBIGUOUS_ERROR_TYPES

        if has_code and not has_infra and not is_ambiguous_type:
            return ClassificationResult(
                category=IncidentCategory.CODE,
                confidence=0.90,
                reason="Stack trace present, no infra failure signals",
            )

        if has_infra and not has_code:
            return ClassificationResult(
                category=IncidentCategory.INFRA,
                confidence=0.90,
                reason="Infra error type, no application stack trace",
            )

        if has_code and has_infra:
            return ClassificationResult(
                category=IncidentCategory.BOTH,
                confidence=0.50,
                reason="Both code stack trace and infra signals present — needs Stage 2",
            )

        if is_ambiguous_type:
            return ClassificationResult(
                category=IncidentCategory.BOTH,
                confidence=0.40,
                reason=f"Ambiguous error type {signal.error_type} — needs Stage 2",
            )

        return ClassificationResult(
            category=IncidentCategory.TRANSIENT,
            confidence=0.50,
            reason="Could not determine category — treating as transient",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_categoriser_stage1.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add categoriser/stage1.py tests/test_categoriser_stage1.py
git commit -m "feat: add Stage 1 fast signal categoriser"
```

---

### Task 4.2: Stage 2 — parallel investigation for ambiguous signals

**Files:**
- Create: `categoriser/stage2.py`
- Create: `categoriser/transient_watcher.py`
- Create: `categoriser/router.py`
- Create: `tests/test_categoriser_stage2.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_categoriser_stage2.py
from unittest.mock import MagicMock
from core.signal import Signal, SignalSource
from core.incident import IncidentCategory
from categoriser.stage2 import Stage2Investigator

def test_stage2_routes_to_infra_when_pod_down():
    signal = Signal(
        source=SignalSource.LOG,
        service="payments",
        error_type="ConnectionError",
        error_message="database unreachable",
        stack_trace='File "demo_app/payments.py", line 45',
        raw_text="ERROR ...",
        occurrence_count=6,
    )
    mock_kg = MagicMock()
    # KG says: no recent commit touching this file
    mock_kg.get_function_context.return_value = {
        "callers": [], "callees": [], "tests": [],
        "past_incidents": [], "past_fixes": [],
    }
    mock_kubectl = MagicMock()
    # kubectl says: db pod is crashing
    mock_kubectl.get_pod_status.return_value = [
        {"name": "db-pod-xyz", "phase": "CrashLoopBackOff",
         "restart_count": 12, "waiting_reason": "CrashLoopBackOff"}
    ]

    investigator = Stage2Investigator(kg_querier=mock_kg, kubectl=mock_kubectl)
    result = investigator.investigate(signal)

    assert result.category == IncidentCategory.INFRA
    assert result.infra_suspicion_score > result.code_suspicion_score

def test_stage2_routes_to_code_when_no_infra_issue():
    signal = Signal(
        source=SignalSource.LOG,
        service="payments",
        error_type="ConnectionError",
        error_message="wrong connection string",
        stack_trace='File "demo_app/payments.py", line 45',
        raw_text="ERROR ...",
        occurrence_count=6,
    )
    mock_kg = MagicMock()
    mock_kg.get_function_context.return_value = {
        "callers": ["checkout"], "callees": ["db_connect"],
        "tests": ["test_payments"], "past_incidents": [{"type": "ConnectionError"}],
        "past_fixes": [{"patch": "fix connection string", "confidence": 0.9}],
    }
    mock_kubectl = MagicMock()
    mock_kubectl.get_pod_status.return_value = []  # no pod issues

    investigator = Stage2Investigator(kg_querier=mock_kg, kubectl=mock_kubectl)
    result = investigator.investigate(signal)

    assert result.category == IncidentCategory.CODE
    assert result.code_suspicion_score > result.infra_suspicion_score
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_categoriser_stage2.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement Stage2Investigator**

```python
# categoriser/stage2.py
from dataclasses import dataclass
from core.signal import Signal
from core.incident import IncidentCategory
from knowledge.kg_querier import KGQuerier


INFRA_WAITING_REASONS = {
    "CrashLoopBackOff", "OOMKilled", "Error",
    "ImagePullBackOff", "ErrImagePull",
}


@dataclass
class Stage2Result:
    category: IncidentCategory
    code_suspicion_score: float
    infra_suspicion_score: float
    reason: str


class Stage2Investigator:
    """
    Parallel lightweight investigation for ambiguous signals.
    Queries KG (code side) and kubectl (infra side) simultaneously.
    Compares suspicion scores to route to the right healing path.
    """

    def __init__(self, kg_querier: KGQuerier = None, kubectl=None):
        self.kg = kg_querier
        self.kubectl = kubectl

    def investigate(self, signal: Signal) -> Stage2Result:
        code_score = self._check_code_side(signal)
        infra_score = self._check_infra_side(signal)

        if infra_score > code_score + 0.2:
            category = IncidentCategory.INFRA
            reason = f"Infra score {infra_score:.2f} > code score {code_score:.2f}"
        elif code_score > infra_score + 0.2:
            category = IncidentCategory.CODE
            reason = f"Code score {code_score:.2f} > infra score {infra_score:.2f}"
        else:
            category = IncidentCategory.BOTH
            reason = f"Scores too close: code={code_score:.2f}, infra={infra_score:.2f}"

        return Stage2Result(
            category=category,
            code_suspicion_score=code_score,
            infra_suspicion_score=infra_score,
            reason=reason,
        )

    def _check_code_side(self, signal: Signal) -> float:
        if not self.kg:
            return 0.3
        score = 0.0
        # Stack trace present: +0.3
        if signal.stack_trace:
            score += 0.3
        # Past incidents for this function in KG: +0.4
        try:
            context = self.kg.get_function_context(
                signal.service, f"demo_app/{signal.service}.py"
            )
            if context.get("past_incidents"):
                score += 0.4
            if context.get("past_fixes"):
                score += 0.2
        except Exception:
            pass
        return min(1.0, score)

    def _check_infra_side(self, signal: Signal) -> float:
        if not self.kubectl:
            return 0.3
        score = 0.0
        try:
            pods = self.kubectl.get_pod_status(signal.service)
            for pod in pods:
                if pod.get("waiting_reason") in INFRA_WAITING_REASONS:
                    score += 0.6
                    break
                if pod.get("restart_count", 0) > 5:
                    score += 0.3
        except Exception:
            pass
        return min(1.0, score)
```

- [ ] **Step 4: Implement TransientWatcher**

```python
# categoriser/transient_watcher.py
import time
import threading
from collections import defaultdict
from core.signal import Signal


class TransientWatcher:
    """
    Watches a signal for 5 minutes.
    If it repeats >= 3 times, promotes it to a real incident.
    If it does not repeat, discards it as transient noise.
    """

    def __init__(self, watch_seconds: int = 300, repeat_threshold: int = 3):
        self.watch_seconds = watch_seconds
        self.repeat_threshold = repeat_threshold
        self._counts: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def observe(self, signal: Signal, on_confirmed) -> None:
        key = f"{signal.service}:{signal.error_type}:{signal.error_message[:50]}"
        with self._lock:
            self._counts[key] += 1
            count = self._counts[key]

        if count >= self.repeat_threshold:
            with self._lock:
                self._counts[key] = 0
            on_confirmed(signal)
        else:
            threading.Timer(
                self.watch_seconds,
                self._expire,
                args=[key]
            ).start()

    def _expire(self, key: str) -> None:
        with self._lock:
            self._counts.pop(key, None)
```

- [ ] **Step 5: Implement Router**

```python
# categoriser/router.py
import uuid
from core.signal import Signal
from core.incident import Incident, IncidentCategory
from categoriser.stage1 import Stage1Categoriser
from categoriser.stage2 import Stage2Investigator
from categoriser.transient_watcher import TransientWatcher
from rich.console import Console

console = Console()


class Categoriser:
    """
    Two-stage categoriser + transient watcher.
    Emits a fully categorised Incident to the Supervisor.
    """

    def __init__(
        self,
        kg_querier=None,
        kubectl=None,
        transient_watcher: TransientWatcher = None,
    ):
        self.stage1 = Stage1Categoriser()
        self.stage2 = Stage2Investigator(kg_querier=kg_querier, kubectl=kubectl)
        self.watcher = transient_watcher or TransientWatcher()

    def process(self, signal: Signal) -> Incident | None:
        """
        Returns an Incident if the signal is actionable.
        Returns None if transient (being watched).
        """
        result = self.stage1.classify(signal)
        console.print(
            f"[dim]CATEGORISER Stage1:[/] "
            f"{result.category.value} (confidence={result.confidence:.2f}) "
            f"— {result.reason}"
        )

        if result.category == IncidentCategory.TRANSIENT:
            console.print("[dim]Sending to TransientWatcher — monitoring...[/]")
            return None

        final_category = result.category

        if result.category == IncidentCategory.BOTH:
            console.print("[dim]CATEGORISER Stage2: ambiguous — investigating both sides...[/]")
            stage2_result = self.stage2.investigate(signal)
            final_category = stage2_result.category
            console.print(
                f"[dim]CATEGORISER Stage2:[/] "
                f"resolved to {final_category.value} — {stage2_result.reason}"
            )

        incident_id = f"inc-{uuid.uuid4().hex[:8]}"
        incident = Incident.from_signal(incident_id, signal, final_category)
        incident.status = incident.status.__class__.CATEGORISED
        return incident
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_categoriser_stage2.py -v
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add categoriser/ tests/test_categoriser_stage2.py
git commit -m "feat: add Stage 2 investigator, TransientWatcher, and Categoriser router"
```


---

## Phase 5: Code Healing Subagents

### Task 5.1: Observer — extracts file+line from stack trace

```python
# agents/code/observer.py
import re
import os
from core.incident import Incident

SKIP_PREFIXES = (
    "fastapi", "uvicorn", "starlette", "anyio",
    "asyncio", "site-packages", "<frozen", "/usr/lib",
)


class ObserverAgent:
    """Parses the stack trace and attaches the source file path to the incident."""

    def run(self, incident: Incident) -> dict:
        signal = incident.signal
        file_path = self._extract_file(signal.stack_trace, signal.service)
        incident.signal = signal
        return {"file_path": file_path, "service": signal.service}

    def _extract_file(self, stack_trace: str, service: str) -> str:
        lines = stack_trace.split("\n")
        last_app_file = ""
        for line in lines:
            match = re.search(r'File "([^"]+)", line (\d+)', line)
            if match:
                path = match.group(1)
                if not any(skip in path for skip in SKIP_PREFIXES):
                    last_app_file = path
        return last_app_file or f"demo_app/{service}.py"
```

### Task 5.2: Detective — queries KG + LLM root cause

```python
# agents/code/detective.py
import os
from core.incident import Incident
from core.llm import OllamaClient
from knowledge.kg_querier import KGQuerier


class DetectiveAgent:
    """
    Queries the knowledge graph for full context around the failing function,
    then uses the LLM to perform root cause analysis with that rich context.
    """

    def __init__(self, llm: OllamaClient = None, kg: KGQuerier = None):
        self.llm = llm or OllamaClient()
        self.kg = kg

    def run(self, incident: Incident) -> dict:
        signal = incident.signal
        file_path = self._find_file(signal)

        # Read source code
        source_code = ""
        if os.path.exists(file_path):
            with open(file_path) as f:
                source_code = f.read()
        incident.buggy_code = source_code

        # Query KG for context
        kg_context = {}
        kg_context_str = "No knowledge graph context available."
        if self.kg:
            func_name = self._extract_function_name(signal.stack_trace)
            kg_context = self.kg.get_function_context(func_name, file_path)
            similar = self.kg.find_similar_incidents(
                signal.stack_trace + signal.error_message
            )
            kg_context["similar_past_incidents"] = similar
            kg_context_str = self._format_kg_context(kg_context)
            incident.kg_context = kg_context

        # LLM root cause analysis with full context
        analysis = self.llm.analyse_stack_trace(
            stack_trace=signal.stack_trace,
            error_message=signal.error_message,
            source_code=source_code,
        )

        rca = (
            f"File: {analysis.get('file', file_path)}\n"
            f"Line: {analysis.get('line', 'unknown')}\n"
            f"Root Cause: {analysis.get('root_cause', 'unknown')}\n"
            f"Pattern: {analysis.get('pattern', 'unknown')}\n"
            f"Certainty: {analysis.get('certainty', 'low')}\n"
            f"KG Context: {kg_context_str}"
        )
        incident.root_cause_analysis = rca
        return {"root_cause_analysis": rca, "file_path": file_path, "kg_context": kg_context}

    def _find_file(self, signal) -> str:
        import re
        for line in signal.stack_trace.split("\n"):
            match = re.search(r'File "([^"]+)", line', line)
            if match:
                path = match.group(1)
                if os.path.exists(path):
                    return path
        candidate = f"demo_app/{signal.service}.py"
        return candidate if os.path.exists(candidate) else signal.service + ".py"

    def _extract_function_name(self, stack_trace: str) -> str:
        import re
        matches = re.findall(r"in (\w+)\s*$", stack_trace, re.MULTILINE)
        return matches[-1] if matches else "unknown"

    def _format_kg_context(self, ctx: dict) -> str:
        parts = []
        if ctx.get("callers"):
            parts.append(f"Called by: {', '.join(ctx['callers'])}")
        if ctx.get("callees"):
            parts.append(f"Calls: {', '.join(ctx['callees'])}")
        if ctx.get("past_fixes"):
            parts.append(f"Past fixes: {len(ctx['past_fixes'])} recorded")
        if ctx.get("similar_past_incidents"):
            parts.append(f"Similar incidents: {len(ctx['similar_past_incidents'])} found")
        return " | ".join(parts) if parts else "No prior context"
```

### Task 5.3: Coder — writes fix using LLM + KG context

```python
# agents/code/coder.py
import difflib
from core.incident import Incident
from core.llm import OllamaClient


class CoderAgent:
    """Writes the code fix using LLM, informed by KG context."""

    def __init__(self, llm: OllamaClient = None):
        self.llm = llm or OllamaClient()

    def run(self, incident: Incident) -> dict:
        if not incident.buggy_code:
            return {"fix_written": False, "reason": "No source code available"}

        kg_context_str = self._format_kg_for_prompt(incident.kg_context)

        fixed_code = self.llm.write_code_fix(
            buggy_code=incident.buggy_code,
            root_cause=incident.root_cause_analysis or incident.signal.error_message,
            error=incident.signal.error_message,
            file_path=self._find_file(incident.signal),
            kg_context=kg_context_str,
        )

        if not fixed_code or fixed_code.strip() == incident.buggy_code.strip():
            return {"fix_written": False, "reason": "LLM returned unchanged code"}

        incident.fixed_code = fixed_code
        incident.fix_patch = self._generate_diff(
            incident.buggy_code, fixed_code,
            self._find_file(incident.signal)
        )
        return {
            "fix_written": True,
            "patch_lines": len(incident.fix_patch.split("\n")),
        }

    def _find_file(self, signal) -> str:
        import re, os
        for line in signal.stack_trace.split("\n"):
            match = re.search(r'File "([^"]+)", line', line)
            if match and os.path.exists(match.group(1)):
                return match.group(1)
        return f"demo_app/{signal.service}.py"

    def _format_kg_for_prompt(self, kg_context: dict) -> str:
        if not kg_context:
            return "No knowledge graph context."
        parts = []
        if kg_context.get("past_fixes"):
            fixes = kg_context["past_fixes"][:2]
            parts.append(f"Past successful fixes for similar issues:\n" +
                         "\n".join(f"  - {f.get('patch','')[:100]}" for f in fixes))
        if kg_context.get("callers"):
            parts.append(f"This function is called by: {', '.join(kg_context['callers'])}")
        return "\n".join(parts) if parts else "No prior context."

    def _generate_diff(self, original: str, fixed: str, file_path: str) -> str:
        diff = difflib.unified_diff(
            original.splitlines(keepends=True),
            fixed.splitlines(keepends=True),
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm="",
        )
        return "\n".join(diff)

    def run_revision(
        self,
        incident: Incident,
        feedback: str,
        specific_issue: str = None,
    ) -> dict:
        """
        Called by Supervisor when Guardrail rejects the fix.
        Sends the specific guardrail failure reason back to the LLM
        so it can write a targeted revision.
        """
        if not incident.buggy_code:
            return {"fix_written": False, "reason": "No original code to revise from"}

        file_path = self._find_file(incident.signal)
        revision_context = (
            f"Your previous fix was rejected by the code review guardrail.\n"
            f"Rejection reason: {feedback}\n"
            f"Specific issue: {specific_issue or 'see reason above'}\n\n"
            f"Rewrite the fix addressing this specific problem."
        )
        revised_code = self.llm.write_code_fix(
            buggy_code=incident.buggy_code,
            root_cause=revision_context,
            error=incident.signal.error_message,
            file_path=file_path,
        )
        if not revised_code or revised_code.strip() == incident.fixed_code.strip():
            return {"fix_written": False, "reason": "LLM returned unchanged code on revision"}

        previous_code = incident.fixed_code
        incident.fixed_code = revised_code
        incident.fix_patch = self._generate_diff(
            previous_code, revised_code, file_path
        )
        return {
            "fix_written": True,
            "patch_lines": len(incident.fix_patch.split("\n")),
            "revision": True,
        }
```

### Task 5.5: Guardrail Agent — three-layer code validation

**Sits between Coder and Tester. Validates the fix before any test is run.**

**Files:**
- Create: `agents/code/guardrail.py`
- Create: `tests/test_guardrail.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_guardrail.py
from unittest.mock import MagicMock, patch
from core.signal import Signal, SignalSource
from core.incident import Incident, IncidentCategory
from agents.code.guardrail import GuardrailAgent, GuardrailResult


def _make_incident(fixed_code: str) -> Incident:
    signal = Signal(
        source=SignalSource.LOG, service="payments",
        error_type="TypeError",
        error_message="'NoneType' object is not subscriptable",
        stack_trace='File "demo_app/payments.py", line 18, in process_payment',
        raw_text="ERROR", occurrence_count=4,
    )
    inc = Incident.from_signal("inc-001", signal, IncidentCategory.CODE)
    inc.fixed_code = fixed_code
    inc.root_cause_analysis = "ROOT_CAUSE: inventory can be None\nPATTERN: missing null check"
    return inc


def test_layer1_fails_on_syntax_error():
    """Static analysis catches syntax error before LLM is even called."""
    incident = _make_incident("def process_payment(order_id\n    pass")
    agent = GuardrailAgent(llm=MagicMock())
    result = agent.run(incident)
    assert result.passed is False
    assert result.layer == "static"
    assert "syntax" in result.reason.lower()


def test_layer2_hard_blocks_on_security_violation():
    """Security scan catches shell=True — hard block, no retry."""
    incident = _make_incident(
        "import subprocess\n"
        "def process_payment(order_id):\n"
        "    subprocess.run(order_id, shell=True)\n"
    )
    agent = GuardrailAgent(llm=MagicMock())
    result = agent.run(incident)
    assert result.passed is False
    assert result.layer == "security"
    assert result.hard_block is True


def test_layer2_hard_blocks_on_eval():
    """Security scan catches eval() — hard block."""
    incident = _make_incident(
        "def process_payment(order_id):\n"
        "    return eval(order_id)\n"
    )
    agent = GuardrailAgent(llm=MagicMock())
    result = agent.run(incident)
    assert result.passed is False
    assert result.layer == "security"
    assert result.hard_block is True


def test_layer3_fails_on_bare_except_pass():
    """Semantic review catches bare except: pass via LLM judge."""
    bad_fix = (
        "def process_payment(order_id):\n"
        "    try:\n"
        "        inventory = get_inventory(order_id)\n"
        "        total = inventory['price'] * inventory['quantity']\n"
        "        return {'status': 'ok', 'total': total}\n"
        "    except:\n"
        "        pass\n"
    )
    incident = _make_incident(bad_fix)
    mock_llm = MagicMock()
    mock_llm.chat.return_value = (
        "VERDICT: FAIL\n"
        "REASON: Fix uses bare except: pass which silently swallows all exceptions\n"
        "SPECIFIC_ISSUE: bare except: pass on line 6"
    )
    agent = GuardrailAgent(llm=mock_llm)
    result = agent.run(incident)
    assert result.passed is False
    assert result.layer == "semantic"
    assert result.hard_block is False
    assert "bare except" in result.reason.lower()


def test_all_layers_pass_on_clean_fix():
    """Good fix passes all three layers."""
    good_fix = (
        "def process_payment(order_id: str) -> dict:\n"
        "    inventory = get_inventory(order_id)\n"
        "    if inventory is None:\n"
        "        raise ValueError(f'Inventory not found for order {order_id}')\n"
        "    total = inventory['price'] * inventory['quantity']\n"
        "    return {'status': 'ok', 'order_id': order_id, 'total': total}\n"
    )
    incident = _make_incident(good_fix)
    mock_llm = MagicMock()
    mock_llm.chat.return_value = (
        "VERDICT: PASS\n"
        "REASON: Fix correctly adds null guard and raises a descriptive ValueError\n"
        "SPECIFIC_ISSUE: none"
    )
    agent = GuardrailAgent(llm=mock_llm)
    result = agent.run(incident)
    assert result.passed is True
    assert result.layer == "all"
    assert result.hard_block is False
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_guardrail.py -v
```

Expected: FAIL — module not found

- [ ] **Step 3: Implement GuardrailAgent**

```python
# agents/code/guardrail.py
import ast
import re
import subprocess
from dataclasses import dataclass
from typing import Optional
from core.incident import Incident
from core.llm import OllamaClient


# Layer 2: patterns that constitute a hard security block
SECURITY_PATTERNS = [
    (r"\beval\s*\(", "eval() detected — arbitrary code execution risk"),
    (r"\bexec\s*\(", "exec() detected — arbitrary code execution risk"),
    (r"shell\s*=\s*True", "shell=True in subprocess — command injection risk"),
    (r"pickle\.loads?\s*\(", "pickle.loads() — unsafe deserialization risk"),
    (r"__import__\s*\(", "__import__() — dynamic import risk"),
    (r"os\.system\s*\(", "os.system() — command injection risk"),
    (r"(?:password|secret|api_key|token)\s*=\s*['\"][^'\"]{8,}['\"]",
     "Hardcoded credential detected"),
]

# Layer 3: LLM judge system prompt
SEMANTIC_JUDGE_SYSTEM = """You are a senior code reviewer performing a safety review.
You did NOT write this fix. Your job is to find problems with it.

REJECT the fix if ANY of the following are true:
- Uses bare except: pass or except: continue (silently swallows errors)
- Returns a fake or default value instead of raising a proper exception
- Does not address the stated root cause
- Changes the function signature or return type
- Introduces a new external library dependency
- Is disproportionately large for a simple guard clause (30+ lines)
- Contradicts standard error handling patterns

Respond in EXACTLY this format (no other text):
VERDICT: PASS or FAIL
REASON: one sentence explaining your decision
SPECIFIC_ISSUE: the exact problem if FAIL, or "none" if PASS"""


@dataclass
class GuardrailResult:
    passed: bool
    layer: str           # "static" | "security" | "semantic" | "all"
    reason: str
    specific_issue: Optional[str] = None
    hard_block: bool = False


class GuardrailAgent:
    """
    Three-layer code validation between Coder and Tester.

    Layer 1 — Static Analysis:  syntax, imports, undefined vars (no LLM)
    Layer 2 — Security Scan:    dangerous patterns (no LLM, hard block)
    Layer 3 — Semantic Review:  LLM-as-judge (independent critic call)

    Returns GuardrailResult. Supervisor sends failures back to Coder
    except security violations which are always hard-blocked.
    """

    def __init__(self, llm: OllamaClient = None):
        self.llm = llm or OllamaClient()

    def run(self, incident: Incident) -> GuardrailResult:
        code = incident.fixed_code or ""

        # Layer 1: Static analysis
        static_result = self._static_analysis(code)
        if not static_result.passed:
            return static_result

        # Layer 2: Security scan
        security_result = self._security_scan(code)
        if not security_result.passed:
            return security_result

        # Layer 3: Semantic review
        semantic_result = self._semantic_review(code, incident)
        if not semantic_result.passed:
            return semantic_result

        return GuardrailResult(
            passed=True,
            layer="all",
            reason="All three guardrail layers passed",
            hard_block=False,
        )

    def _static_analysis(self, code: str) -> GuardrailResult:
        """Layer 1: AST parse + basic lint check."""
        # AST parse — catches syntax errors
        try:
            ast.parse(code)
        except SyntaxError as e:
            return GuardrailResult(
                passed=False,
                layer="static",
                reason=f"Syntax error in generated fix: {e.msg} at line {e.lineno}",
                specific_issue=str(e),
                hard_block=False,
            )

        # ruff check if available — catches undefined names, imports
        try:
            result = subprocess.run(
                ["ruff", "check", "--select=F", "-"],
                input=code,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0 and result.stdout.strip():
                first_issue = result.stdout.strip().split("\n")[0]
                return GuardrailResult(
                    passed=False,
                    layer="static",
                    reason=f"Static analysis issue: {first_issue}",
                    specific_issue=result.stdout.strip(),
                    hard_block=False,
                )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass  # ruff not installed — skip, AST parse was sufficient

        return GuardrailResult(
            passed=True, layer="static",
            reason="Static analysis passed", hard_block=False,
        )

    def _security_scan(self, code: str) -> GuardrailResult:
        """
        Layer 2: Pattern-based security scan.
        Any match = HARD BLOCK. No retry. No exceptions.
        """
        for pattern, description in SECURITY_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                return GuardrailResult(
                    passed=False,
                    layer="security",
                    reason=f"Security violation — hard block: {description}",
                    specific_issue=description,
                    hard_block=True,
                )
        return GuardrailResult(
            passed=True, layer="security",
            reason="Security scan passed", hard_block=False,
        )

    def _semantic_review(self, code: str, incident: Incident) -> GuardrailResult:
        """
        Layer 3: LLM-as-judge.
        A separate, independent LLM call acting as critic.
        """
        prompt = (
            f"Root cause of the bug:\n{incident.root_cause_analysis}\n\n"
            f"Error that occurred:\n{incident.signal.error_message}\n\n"
            f"Fix written by the coding agent:\n{code}\n\n"
            "Review this fix."
        )
        raw = self.llm.chat(prompt, system=SEMANTIC_JUDGE_SYSTEM)

        verdict = "PASS"
        reason = "Semantic review passed"
        specific_issue = None

        for line in raw.strip().split("\n"):
            line = line.strip()
            if line.startswith("VERDICT:"):
                verdict = line.split(":", 1)[1].strip().upper()
            elif line.startswith("REASON:"):
                reason = line.split(":", 1)[1].strip()
            elif line.startswith("SPECIFIC_ISSUE:"):
                specific_issue = line.split(":", 1)[1].strip()
                if specific_issue.lower() == "none":
                    specific_issue = None

        if verdict == "FAIL":
            return GuardrailResult(
                passed=False,
                layer="semantic",
                reason=reason,
                specific_issue=specific_issue,
                hard_block=False,
            )

        return GuardrailResult(
            passed=True, layer="semantic",
            reason=reason, hard_block=False,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_guardrail.py -v
```

Expected:
```
PASSED tests/test_guardrail.py::test_layer1_fails_on_syntax_error
PASSED tests/test_guardrail.py::test_layer2_hard_blocks_on_security_violation
PASSED tests/test_guardrail.py::test_layer2_hard_blocks_on_eval
PASSED tests/test_guardrail.py::test_layer3_fails_on_bare_except_pass
PASSED tests/test_guardrail.py::test_all_layers_pass_on_clean_fix
5 passed
```

- [ ] **Step 5: Commit**

```bash
git add agents/code/guardrail.py tests/test_guardrail.py
git commit -m "feat: add Guardrail agent — static analysis, security scan, LLM semantic review"
```

---

### Task 5.5: Tester — runs tests + makes deployment decision

**The Tester owns the deployment decision. No LLM scoring. Pure deterministic rule.**

```
DECISION RULE:
  Any existing test file modified?           → open_pr
    (functionality may have changed —
     human must verify what changed)

  No existing tests modified
  + new test added for the fix
  + all tests passing                        → direct_deploy
    (fix is additive, tested, provably
     non-breaking — safe to ship)

  No existing tests modified
  + no new test added
  + all tests passing                        → open_pr
    (fix is untested — scope is unclear,
     human review required)

  Any test failing (after all retries)       → rollback
    (never leave production in a broken
     state — revert immediately)
```

**Files:**
- Create: `agents/code/tester.py`
- Create: `tests/test_tester.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_tester.py
import pytest
from unittest.mock import MagicMock, patch
from core.signal import Signal, SignalSource
from core.incident import Incident, IncidentCategory
from agents.code.tester import TesterAgent


def _make_incident() -> Incident:
    signal = Signal(
        source=SignalSource.LOG,
        service="payments",
        error_type="TypeError",
        error_message="NoneType not subscriptable",
        stack_trace='File "demo_app/payments.py", line 18, in process_payment',
        raw_text="ERROR",
        occurrence_count=4,
    )
    inc = Incident.from_signal("inc-001", signal, IncidentCategory.CODE)
    inc.buggy_code = 'def process_payment(order_id):\n    total = inventory["price"]\n'
    inc.fixed_code = (
        'def process_payment(order_id):\n'
        '    if inventory is None:\n'
        '        raise ValueError("not found")\n'
        '    total = inventory["price"]\n'
    )
    inc.fix_patch = (
        "--- a/demo_app/payments.py\n"
        "+++ b/demo_app/payments.py\n"
        "+    if inventory is None:\n"
        "+        raise ValueError('not found')\n"
    )
    return inc


def test_decision_direct_deploy_when_new_test_added_no_existing_modified():
    """
    Fix adds a new test, does not modify any existing test.
    All tests pass.
    Expected: direct_deploy.
    """
    incident = _make_incident()
    tester = TesterAgent.__new__(TesterAgent)
    tester.llm = MagicMock()
    tester.config = MagicMock()
    tester.config.test_command = "pytest demo_app/tests/ -v"
    tester.config.max_fix_attempts = 1

    with patch.object(tester, "_run_tests", return_value=(True, "3 passed")), \
         patch.object(tester, "_apply_fix_to_disk"), \
         patch.object(tester, "_restore_file"), \
         patch.object(tester, "_analyse_test_changes", return_value={
             "existing_tests_modified": False,
             "new_tests_added": True,
             "new_test_names": ["test_unknown_order_raises_value_error"],
         }):
        result = tester.run(incident)

    assert result["passed"] is True
    assert result["decision"] == "direct_deploy"
    assert incident.deploy_decision == "direct_deploy"
    assert incident.new_tests_added is True
    assert incident.existing_tests_modified is False


def test_decision_open_pr_when_existing_test_modified():
    """
    Fix modifies an existing test file — functionality may have changed.
    Expected: open_pr regardless of whether tests pass.
    """
    incident = _make_incident()
    tester = TesterAgent.__new__(TesterAgent)
    tester.llm = MagicMock()
    tester.config = MagicMock()
    tester.config.test_command = "pytest demo_app/tests/ -v"
    tester.config.max_fix_attempts = 1

    with patch.object(tester, "_run_tests", return_value=(True, "3 passed")), \
         patch.object(tester, "_apply_fix_to_disk"), \
         patch.object(tester, "_restore_file"), \
         patch.object(tester, "_analyse_test_changes", return_value={
             "existing_tests_modified": True,
             "new_tests_added": False,
             "new_test_names": [],
         }):
        result = tester.run(incident)

    assert result["passed"] is True
    assert result["decision"] == "open_pr"
    assert incident.deploy_decision == "open_pr"
    assert incident.existing_tests_modified is True


def test_decision_open_pr_when_no_tests_added_or_modified():
    """
    Fix changes source code only, no test changes whatsoever.
    Passing tests but no coverage evidence — scope unclear.
    Expected: open_pr.
    """
    incident = _make_incident()
    tester = TesterAgent.__new__(TesterAgent)
    tester.llm = MagicMock()
    tester.config = MagicMock()
    tester.config.test_command = "pytest demo_app/tests/ -v"
    tester.config.max_fix_attempts = 1

    with patch.object(tester, "_run_tests", return_value=(True, "2 passed")), \
         patch.object(tester, "_apply_fix_to_disk"), \
         patch.object(tester, "_restore_file"), \
         patch.object(tester, "_analyse_test_changes", return_value={
             "existing_tests_modified": False,
             "new_tests_added": False,
             "new_test_names": [],
         }):
        result = tester.run(incident)

    assert result["passed"] is True
    assert result["decision"] == "open_pr"
    assert incident.deploy_decision == "open_pr"


def test_decision_rollback_when_tests_fail():
    """
    Tests fail after all retries — rollback immediately.
    """
    incident = _make_incident()
    tester = TesterAgent.__new__(TesterAgent)
    tester.llm = MagicMock()
    tester.llm.write_code_fix.return_value = incident.fixed_code
    tester.config = MagicMock()
    tester.config.test_command = "pytest demo_app/tests/ -v"
    tester.config.max_fix_attempts = 2

    with patch.object(tester, "_run_tests", return_value=(False, "FAILED test_payments")), \
         patch.object(tester, "_apply_fix_to_disk"), \
         patch.object(tester, "_restore_file"), \
         patch.object(tester, "_analyse_test_changes", return_value={
             "existing_tests_modified": False,
             "new_tests_added": False,
             "new_test_names": [],
         }):
        result = tester.run(incident)

    assert result["passed"] is False
    assert result["decision"] == "rollback"
    assert incident.deploy_decision == "rollback"
```

- [ ] **Step 2: Run to verify tests fail**

```bash
pytest tests/test_tester.py -v
```

Expected: FAIL — module not found

- [ ] **Step 3: Implement TesterAgent with deployment decision**

```python
# agents/code/tester.py
import os
import re
import subprocess
from core.incident import Incident
from core.llm import OllamaClient
from config.tenant_registry import TenantConfig


TEST_FILE_PATTERNS = ("test_", "_test.py", "/tests/", "\\tests\\", "spec_", "_spec.py")


class TesterAgent:
    """
    Writes the fix to disk, runs the full test suite, then makes a
    deterministic deployment decision based on test file change analysis.

    DECISION RULES (no LLM involved):
      existing_tests_modified = True              → open_pr
      existing_tests_modified = False
        + new_tests_added = True
        + all tests pass                          → direct_deploy
      existing_tests_modified = False
        + new_tests_added = False
        + all tests pass                          → open_pr
      any test failing (after all retries)        → rollback
    """

    def __init__(self, config: TenantConfig = None, llm: OllamaClient = None):
        self.config = config
        self.llm = llm or OllamaClient()

    def run(self, incident: Incident) -> dict:
        if not incident.fixed_code:
            incident.deploy_decision = "rollback"
            return {"passed": False, "decision": "rollback", "reason": "No fix available"}

        file_path = self._find_file(incident.signal)
        max_attempts = self.config.max_fix_attempts if self.config else 3
        test_command = self.config.test_command if self.config else "pytest tests/ -v"

        # Analyse what the fix changes BEFORE touching disk
        test_analysis = self._analyse_test_changes(incident.fix_patch or "")
        incident.existing_tests_modified = test_analysis["existing_tests_modified"]
        incident.new_tests_added = test_analysis["new_tests_added"]

        original_content = self._read_original(file_path)

        try:
            for attempt in range(max_attempts):
                self._apply_fix_to_disk(file_path, incident.fixed_code)
                passed, output = self._run_tests(test_command)
                incident.test_output = output

                if passed:
                    decision = self._make_decision(test_analysis)
                    incident.deploy_decision = decision
                    return {
                        "passed": True,
                        "output": output,
                        "attempts": attempt + 1,
                        "decision": decision,
                        "existing_tests_modified": test_analysis["existing_tests_modified"],
                        "new_tests_added": test_analysis["new_tests_added"],
                        "new_test_names": test_analysis["new_test_names"],
                    }

                # Tests failed — ask LLM to revise if retries remain
                if attempt < max_attempts - 1:
                    revised = self.llm.write_code_fix(
                        buggy_code=incident.buggy_code or "",
                        root_cause=(
                            f"{incident.root_cause_analysis}\n"
                            f"Previous fix failed tests:\n{output[-500:]}"
                        ),
                        error=incident.signal.error_message,
                        file_path=file_path,
                    )
                    if revised and revised.strip() != incident.fixed_code.strip():
                        incident.fixed_code = revised
                        # Re-analyse test changes for revised fix
                        test_analysis = self._analyse_test_changes(
                            incident.fix_patch or ""
                        )

            # All retries exhausted — rollback
            incident.deploy_decision = "rollback"
            return {
                "passed": False,
                "output": incident.test_output,
                "attempts": max_attempts,
                "decision": "rollback",
            }
        finally:
            self._restore_file(file_path, original_content)

    def _analyse_test_changes(self, patch: str) -> dict:
        """
        Reads the unified diff and determines:
        - Did any existing test file get modified?
        - Were any new test functions added?

        An 'existing test modified' means a line was changed in a file
        that already contained tests (i.e., a test file that existed before).

        A 'new test added' means a new function starting with 'test_'
        appears in the +lines of the diff.
        """
        existing_tests_modified = False
        new_tests_added = False
        new_test_names = []

        current_file = ""
        is_new_file = False

        for line in patch.split("\n"):
            # Track which file we're in
            if line.startswith("--- a/"):
                current_file = line[6:].strip()
                is_new_file = False
            elif line.startswith("+++ b/"):
                new_path = line[6:].strip()
                # If old path was /dev/null this is a brand new file
                is_new_file = current_file == "/dev/null"
                current_file = new_path

            # Check if current file is a test file
            is_test_file = any(p in current_file for p in TEST_FILE_PATTERNS)

            if is_test_file:
                if line.startswith("+") and not line.startswith("+++"):
                    # A line was added to a test file
                    added_line = line[1:].strip()
                    if added_line.startswith("def test_"):
                        # New test function added
                        match = re.match(r"def (test_\w+)", added_line)
                        if match:
                            new_test_names.append(match.group(1))
                        new_tests_added = True
                    if not is_new_file:
                        # An existing test file was modified
                        existing_tests_modified = True

        return {
            "existing_tests_modified": existing_tests_modified,
            "new_tests_added": new_tests_added,
            "new_test_names": new_test_names,
        }

    def _make_decision(self, test_analysis: dict) -> str:
        """
        Pure deterministic rule. No LLM. No scoring.
        """
        if test_analysis["existing_tests_modified"]:
            return "open_pr"
        if test_analysis["new_tests_added"]:
            return "direct_deploy"
        return "open_pr"

    def _apply_fix_to_disk(self, file_path: str, content: str) -> None:
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        with open(file_path, "w") as f:
            f.write(content)

    def _restore_file(self, file_path: str, original_content: str | None) -> None:
        if original_content is not None:
            with open(file_path, "w") as f:
                f.write(original_content)

    def _read_original(self, file_path: str) -> str | None:
        if os.path.exists(file_path):
            with open(file_path) as f:
                return f.read()
        return None

    def _run_tests(self, test_command: str) -> tuple[bool, str]:
        result = subprocess.run(
            test_command.split(),
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode == 0, result.stdout + result.stderr

    def _find_file(self, signal) -> str:
        for line in signal.stack_trace.split("\n"):
            match = re.search(r'File "([^"]+)", line', line)
            if match and os.path.exists(match.group(1)):
                return match.group(1)
        return f"demo_app/{signal.service}.py"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_tester.py -v
```

Expected:
```
PASSED tests/test_tester.py::test_decision_direct_deploy_when_new_test_added_no_existing_modified
PASSED tests/test_tester.py::test_decision_open_pr_when_existing_test_modified
PASSED tests/test_tester.py::test_decision_open_pr_when_no_tests_added_or_modified
PASSED tests/test_tester.py::test_decision_rollback_when_tests_fail
4 passed
```

- [ ] **Step 5: Commit**

```bash
git add agents/code/tester.py tests/test_tester.py
git commit -m "feat: add Tester agent with deterministic deploy decision from test change analysis"
```

### Task 5.6: Committer — branch + commit + PR or direct push

```python
# agents/code/committer.py
import os
import re
from datetime import datetime
from core.incident import Incident, IncidentStatus
from core.llm import OllamaClient
from core.github_tools import GitHubTools


class CommitterAgent:
    """
    Delivers the fix to GitHub.
    High confidence + low risk → direct push to main + CI/CD.
    Otherwise → open PR for human review.
    """

    def __init__(self, github: GitHubTools = None, llm: OllamaClient = None):
        self.github = github or GitHubTools()
        self.llm = llm or OllamaClient()

    def run(self, incident: Incident, decision: str) -> dict:
        if not incident.fixed_code:
            return {"committed": False, "reason": "No fix available"}

        file_path = self._find_file(incident.signal)
        error_slug = re.sub(r"[^a-z0-9]", "-", incident.signal.error_type.lower())
        branch = f"fix/{incident.id}-{error_slug}"
        incident.pr_branch = branch

        self.github.create_branch(branch)
        commit_msg = (
            f"fix({incident.signal.service}): "
            f"resolve {incident.signal.error_type} "
            f"[{incident.id}] [self-healed]"
        )
        self.github.commit_fix(
            branch=branch,
            file_path=file_path,
            new_content=incident.fixed_code,
            commit_message=commit_msg,
        )

        if decision == "auto_deploy":
            # Merge to main directly
            pr_url = self.github.open_pr(
                branch=branch,
                title=f"fix({incident.signal.service}): {incident.signal.error_type} [{incident.id}]",
                body=self._build_pr_body(incident, auto_deploy=True),
            )
            incident.pr_url = pr_url
            incident.status = IncidentStatus.COMMITTING
            return {"committed": True, "pr_url": pr_url, "mode": "auto_deploy"}
        else:
            pr_description = self.llm.generate_pr_description(
                incident_id=incident.id,
                root_cause=incident.root_cause_analysis or "",
                fix_summary=f"Modified {file_path}",
                test_output=incident.test_output or "",
            )
            pr_url = self.github.open_pr(
                branch=branch,
                title=f"fix({incident.signal.service}): {incident.signal.error_type} [{incident.id}]",
                body=self._build_pr_body(incident, llm_description=pr_description),
            )
            incident.pr_url = pr_url
            incident.status = IncidentStatus.COMMITTING
            return {"committed": True, "pr_url": pr_url, "mode": "open_pr"}

    def _find_file(self, signal) -> str:
        import re as re_mod, os as os_mod
        for line in signal.stack_trace.split("\n"):
            match = re_mod.search(r'File "([^"]+)", line', line)
            if match and os_mod.path.exists(match.group(1)):
                return match.group(1)
        return f"demo_app/{signal.service}.py"

    def _build_pr_body(
        self, incident: Incident,
        auto_deploy: bool = False,
        llm_description: str = ""
    ) -> str:
        mode = "AUTO-DEPLOYED" if auto_deploy else "AWAITING REVIEW"
        return f"""## Self-Healing Fix [{mode}]

**Incident:** `{incident.id}`
**Service:** `{incident.signal.service}`
**Error:** `{incident.signal.error_message}`
**Deploy Decision:** `{incident.deploy_decision}` | existing_tests_modified: `{incident.existing_tests_modified}` | new_tests_added: `{incident.new_tests_added}`

### Root Cause
{incident.root_cause_analysis or 'See stack trace'}

### Changes
{llm_description or 'Direct autonomous fix applied.'}

### Diff
```diff
{incident.fix_patch or 'No diff available'}
```

### Test Results
```
{incident.test_output or 'Tests passed'}
```

---
*Autonomously fixed by Self-Healing System*
*No human was paged. No laptop was opened.*
*Resolved at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}*
"""
```

- [ ] **Step 1: Write tests for all code subagents**

```python
# tests/test_observer.py
from core.signal import Signal, SignalSource
from core.incident import Incident, IncidentCategory
from agents.code.observer import ObserverAgent

def test_observer_extracts_app_file():
    signal = Signal(
        source=SignalSource.LOG, service="payments",
        error_type="TypeError",
        error_message="NoneType not subscriptable",
        stack_trace=(
            'File "fastapi/routing.py", line 99\n'
            'File "demo_app/app.py", line 18\n'
            'File "demo_app/payments.py", line 18, in process_payment'
        ),
        raw_text="ERROR ...", occurrence_count=4,
    )
    incident = Incident.from_signal("inc-001", signal, IncidentCategory.CODE)
    agent = ObserverAgent()
    result = agent.run(incident)
    assert result["file_path"] == "demo_app/payments.py"
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_observer.py -v
```

Expected: PASS

- [ ] **Step 3: Commit all code subagents**

```bash
git add agents/code/ agents/shared/learner.py agents/shared/rollback.py
git commit -m "feat: add code healing subagents: Observer, Detective, Coder, Tester, Committer"
```

---

## Phase 6: Infra Healing Subagents

### Task 6.1: Operator, Executor, Verifier

```python
# agents/infra/operator.py
from core.incident import Incident
from core.llm import OllamaClient

INFRA_PLAYBOOKS = {
    "CrashLoopBackOff": {"action": "rollback", "risk": "low"},
    "OOMKilled":         {"action": "patch_memory", "risk": "low"},
    "Evicted":           {"action": "scale_up", "risk": "low"},
    "Unhealthy":         {"action": "restart", "risk": "low"},
    "FailedScheduling":  {"action": "scale_nodes", "risk": "medium"},
}


class OperatorAgent:
    """Reads cluster state and selects the appropriate infra action."""

    def __init__(self, llm: OllamaClient = None):
        self.llm = llm or OllamaClient()

    def run(self, incident: Incident) -> dict:
        error_type = incident.signal.error_type
        playbook = INFRA_PLAYBOOKS.get(error_type, {"action": "restart", "risk": "medium"})
        return {
            "action": playbook["action"],
            "risk": playbook["risk"],
            "service": incident.signal.service,
            "namespace": incident.signal.namespace or "default",
        }
```

```python
# agents/infra/executor.py
import subprocess
from core.incident import Incident


class ExecutorAgent:
    """Applies kubectl/helm actions to fix infra issues."""

    def run(self, incident: Incident, action: str, namespace: str = "default") -> dict:
        service = incident.signal.service
        result_msg, success = self._execute(action, service, namespace)
        incident.infra_action_taken = f"{action} on {service}: {result_msg}"
        return {"action": action, "result": result_msg, "success": success}

    def _execute(self, action: str, service: str, namespace: str) -> tuple[str, bool]:
        commands = {
            "rollback": ["kubectl", "-n", namespace, "rollout", "undo",
                         f"deployment/{service}"],
            "restart":  ["kubectl", "-n", namespace, "rollout", "restart",
                         f"deployment/{service}"],
            "scale_up": ["kubectl", "-n", namespace, "scale",
                         f"deployment/{service}", "--replicas=3"],
            "patch_memory": ["kubectl", "-n", namespace, "set", "resources",
                             f"deployment/{service}",
                             "--limits=memory=256Mi", "--requests=memory=128Mi"],
        }
        cmd = commands.get(action, commands["restart"])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.stdout + result.stderr, result.returncode == 0
        except Exception as e:
            return str(e), False
```

```python
# agents/infra/verifier.py
import time
from core.incident import Incident, IncidentStatus


class InfraVerifierAgent:
    """Polls cluster health after infra fix. Confirms service recovered."""

    def __init__(self, kubectl=None, wait_seconds: int = 15, checks: int = 4):
        self.kubectl = kubectl
        self.wait_seconds = wait_seconds
        self.checks = checks

    def run(self, incident: Incident) -> dict:
        service = incident.signal.service
        passed_checks = 0
        for i in range(self.checks):
            if i > 0:
                time.sleep(self.wait_seconds)
            if self._is_healthy(service):
                passed_checks += 1
        passed = passed_checks == self.checks
        incident.status = (
            IncidentStatus.RESOLVED if passed else IncidentStatus.FAILED
        )
        return {"passed": passed, "checks_passed": passed_checks}

    def _is_healthy(self, service: str) -> bool:
        if not self.kubectl:
            return True
        try:
            return self.kubectl.is_healthy(service)
        except Exception:
            return False
```

- [ ] **Step 1: Write infra subagent tests**

```python
# tests/test_operator.py
from unittest.mock import MagicMock
from core.signal import Signal, SignalSource
from core.incident import Incident, IncidentCategory
from agents.infra.operator import OperatorAgent

def test_operator_selects_rollback_for_crashloop():
    signal = Signal(
        source=SignalSource.KUBERNETES, service="payments",
        error_type="CrashLoopBackOff",
        error_message="back-off restarting",
        stack_trace="", raw_text="", occurrence_count=8,
    )
    incident = Incident.from_signal("inc-001", signal, IncidentCategory.INFRA)
    agent = OperatorAgent(llm=MagicMock())
    result = agent.run(incident)
    assert result["action"] == "rollback"
    assert result["risk"] == "low"
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_operator.py -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add agents/infra/ tests/test_operator.py
git commit -m "feat: add infra healing subagents: Operator, Executor, Verifier"
```

---

## Phase 7: Rollback Engine

### Task 7.1: Git revert + redeploy on failure

```python
# agents/shared/rollback.py
import subprocess
from core.incident import Incident, IncidentStatus
from rich.console import Console

console = Console()


class RollbackEngine:
    """
    When tests fail after max retries:
    1. Git revert the last commit on the fix branch
    2. Redeploy the previous known-good version
    3. Mark incident as ROLLED_BACK
    4. Escalate with full diagnostic context
    """

    def run(self, incident: Incident, fix_branch: str = None) -> dict:
        console.print(
            f"[bold red]ROLLBACK[/] Tests failed — reverting {incident.id}"
        )

        revert_result = self._git_revert(fix_branch or "main")
        incident.status = IncidentStatus.ROLLED_BACK

        escalation_context = self._build_escalation_context(incident)

        return {
            "rolled_back": True,
            "revert_result": revert_result,
            "escalation_context": escalation_context,
        }

    def _git_revert(self, branch: str) -> str:
        try:
            result = subprocess.run(
                ["git", "revert", "HEAD", "--no-edit"],
                capture_output=True, text=True,
            )
            return result.stdout + result.stderr
        except Exception as e:
            return f"Revert failed: {e}"

    def _build_escalation_context(self, incident: Incident) -> dict:
        return {
            "incident_id": incident.id,
            "service": incident.signal.service,
            "error": incident.signal.error_message,
            "stack_trace": incident.signal.stack_trace,
            "root_cause_analysis": incident.root_cause_analysis,
            "attempted_fix": incident.fix_patch,
            "test_output": incident.test_output,
            "deploy_decision": incident.deploy_decision,
            "message": (
                "Self-healing system attempted a fix but tests failed after "
                f"all retries. The fix has been reverted. "
                f"Human review required for incident {incident.id}."
            ),
        }
```

- [ ] **Step 1: Write rollback test**

```python
# tests/test_rollback.py
from unittest.mock import patch
from core.signal import Signal, SignalSource
from core.incident import Incident, IncidentCategory, IncidentStatus
from agents.shared.rollback import RollbackEngine

def test_rollback_marks_incident_rolled_back():
    signal = Signal(
        source=SignalSource.LOG, service="payments",
        error_type="TypeError", error_message="NoneType",
        stack_trace="", raw_text="", occurrence_count=4,
    )
    incident = Incident.from_signal("inc-001", signal, IncidentCategory.CODE)
    incident.root_cause_analysis = "missing null check"
    incident.fix_patch = "+    if x is None: raise ValueError"
    incident.test_output = "FAILED test_payments.py::test_unknown"

    engine = RollbackEngine()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "Revert commit abc123\n"
        mock_run.return_value.stderr = ""
        result = engine.run(incident, fix_branch="fix/inc-001")

    assert result["rolled_back"] is True
    assert incident.status == IncidentStatus.ROLLED_BACK
    assert "incident_id" in result["escalation_context"]
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_rollback.py -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add agents/shared/rollback.py tests/test_rollback.py
git commit -m "feat: add rollback engine — git revert + escalation on test failure"
```


---

## Phase 8: Learner + KG Feedback

### Task 8.1: Learner writes outcomes back to KG

```python
# agents/shared/learner.py
from datetime import datetime
from core.incident import Incident, IncidentStatus
from knowledge.kg_querier import KGQuerier


class LearnerAgent:
    """
    Writes every incident outcome back to the knowledge graph.
    Successful fix → stores patch + confidence for future reference.
    Failed fix → records attempt so future agents know what didn't work.
    The system gets smarter with every incident.
    """

    def __init__(self, kg: KGQuerier = None):
        self.kg = kg

    def run(self, incident: Incident, verified: bool) -> dict:
        if not self.kg:
            return {"learned": False, "reason": "No KG configured"}

        import re
        func_match = re.search(r"in (\w+)\s*$", incident.signal.stack_trace, re.MULTILINE)
        func_name = func_match.group(1) if func_match else incident.signal.service
        file_path = f"demo_app/{incident.signal.service}.py"

        # Always save the incident node
        self.kg.save_incident(
            incident_id=incident.id,
            function_name=func_name,
            file_path=file_path,
            error_type=incident.signal.error_type,
        )

        # Only save the fix if it was verified as successful
        # Use deploy_decision as the quality signal: direct_deploy = high confidence
        if verified and incident.fix_patch:
            # Map deploy decision to a stored confidence value for future KG lookups
            decision_to_confidence = {
                "direct_deploy": 1.0,   # new test added + all passed = high confidence
                "open_pr": 0.7,         # passed but no new test or existing test changed
            }
            stored_confidence = decision_to_confidence.get(
                incident.deploy_decision or "open_pr", 0.7
            )
            self.kg.save_fix(
                incident_id=incident.id,
                function_name=func_name,
                file_path=file_path,
                patch=incident.fix_patch,
                confidence=stored_confidence,
            )
            return {
                "learned": True,
                "fix_stored": True,
                "deploy_decision": incident.deploy_decision,
                "stored_confidence": stored_confidence,
            }

        return {"learned": True, "fix_stored": False}
```

- [ ] **Step 1: Write learner test**

```python
# tests/test_learner.py
from unittest.mock import MagicMock
from core.signal import Signal, SignalSource
from core.incident import Incident, IncidentCategory
from agents.shared.learner import LearnerAgent

def test_learner_stores_successful_fix_direct_deploy():
    """
    direct_deploy decision → stored confidence = 1.0
    (new test was added + all passed = highest confidence)
    """
    signal = Signal(
        source=SignalSource.LOG, service="payments",
        error_type="TypeError", error_message="NoneType",
        stack_trace='File "demo_app/payments.py", line 18, in process_payment',
        raw_text="ERROR", occurrence_count=4,
    )
    incident = Incident.from_signal("inc-001", signal, IncidentCategory.CODE)
    incident.fix_patch = "+    if inventory is None: raise ValueError"
    incident.deploy_decision = "direct_deploy"
    incident.existing_tests_modified = False
    incident.new_tests_added = True

    mock_kg = MagicMock()
    learner = LearnerAgent(kg=mock_kg)
    result = learner.run(incident, verified=True)

    assert result["learned"] is True
    assert result["fix_stored"] is True
    assert result["stored_confidence"] == 1.0
    mock_kg.save_incident.assert_called_once()
    mock_kg.save_fix.assert_called_once()

def test_learner_stores_successful_fix_open_pr():
    """
    open_pr decision → stored confidence = 0.7
    (passed but no new test added)
    """
    signal = Signal(
        source=SignalSource.LOG, service="payments",
        error_type="TypeError", error_message="NoneType",
        stack_trace='File "demo_app/payments.py", line 18, in process_payment',
        raw_text="ERROR", occurrence_count=4,
    )
    incident = Incident.from_signal("inc-003", signal, IncidentCategory.CODE)
    incident.fix_patch = "+    if inventory is None: raise ValueError"
    incident.deploy_decision = "open_pr"
    incident.existing_tests_modified = False
    incident.new_tests_added = False

    mock_kg = MagicMock()
    learner = LearnerAgent(kg=mock_kg)
    result = learner.run(incident, verified=True)

    assert result["learned"] is True
    assert result["fix_stored"] is True
    assert result["stored_confidence"] == 0.7

def test_learner_does_not_store_failed_fix():
    signal = Signal(
        source=SignalSource.LOG, service="payments",
        error_type="TypeError", error_message="NoneType",
        stack_trace="", raw_text="", occurrence_count=4,
    )
    incident = Incident.from_signal("inc-002", signal, IncidentCategory.CODE)
    incident.fix_patch = "+    if x is None: return"
    incident.deploy_decision = "rollback"

    mock_kg = MagicMock()
    learner = LearnerAgent(kg=mock_kg)
    result = learner.run(incident, verified=False)

    assert result["learned"] is True
    assert result["fix_stored"] is False
    mock_kg.save_incident.assert_called_once()
    mock_kg.save_fix.assert_not_called()
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_learner.py -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add agents/shared/learner.py tests/test_learner.py
git commit -m "feat: add Learner agent — writes incident outcomes to KG for future context"
```

---

## Phase 9: Supervisor Agent

### Task 9.1: The brain — skill+rule, understand→plan→dispatch

**Files:**
- Create: `agents/supervisor.py`
- Create: `tests/test_supervisor.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_supervisor.py
from unittest.mock import MagicMock
from core.signal import Signal, SignalSource
from core.incident import Incident, IncidentCategory, IncidentStatus
from agents.supervisor import SupervisorAgent

def test_supervisor_resolves_code_incident():
    signal = Signal(
        source=SignalSource.LOG, service="payments",
        error_type="TypeError",
        error_message="NoneType not subscriptable",
        stack_trace='File "demo_app/payments.py", line 18, in process_payment',
        raw_text="ERROR", occurrence_count=4,
    )
    incident = Incident.from_signal("inc-001", signal, IncidentCategory.CODE)

    mock_observer = MagicMock()
    mock_observer.run.return_value = {"file_path": "demo_app/payments.py"}

    mock_detective = MagicMock()
    mock_detective.run.return_value = {
        "root_cause_analysis": "ROOT_CAUSE: missing null check\nCERTAINTY: high",
        "file_path": "demo_app/payments.py",
    }

    mock_coder = MagicMock()
    mock_coder.run.return_value = {"fix_written": True, "patch_lines": 4}

    mock_tester = MagicMock()
    mock_tester.run.return_value = {
        "passed": True,
        "output": "3 passed",
        "attempts": 1,
        "decision": "direct_deploy",          # deterministic: new test added, none modified
        "existing_tests_modified": False,
        "new_tests_added": True,
        "new_test_names": ["test_process_payment_unknown_order"],
    }
    # Tester also sets these on the incident object directly
    def _tester_side_effect(incident):
        incident.existing_tests_modified = False
        incident.new_tests_added = True
        incident.deploy_decision = "direct_deploy"
        return mock_tester.run.return_value
    mock_tester.run.side_effect = _tester_side_effect

    mock_committer = MagicMock()
    mock_committer.run.return_value = {
        "committed": True,
        "pr_url": "https://github.com/org/repo/pull/42",
        "mode": "direct_deploy",
    }
    incident.pr_url = "https://github.com/org/repo/pull/42"

    mock_learner = MagicMock()
    mock_learner.run.return_value = {"learned": True, "fix_stored": True}

    mock_llm = MagicMock()
    mock_llm.create_todos.return_value = [
        "Read stack trace and locate file",
        "Query KG and analyse root cause",
        "Write code fix",
        "Run test suite and decide deployment",
        "Commit and deploy",
    ]

    supervisor = SupervisorAgent(
        observer=mock_observer, detective=mock_detective,
        coder=mock_coder, tester=mock_tester,
        committer=mock_committer,
        learner=mock_learner, llm=mock_llm,
    )

    result = supervisor.handle_code_incident(incident)

    assert result["outcome"] == "resolved"
    assert result["pr_url"] == "https://github.com/org/repo/pull/42"
    assert result["deploy_decision"] == "direct_deploy"
    assert result["existing_tests_modified"] is False
    assert result["new_tests_added"] is True
    assert result["mttr_seconds"] > 0
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_supervisor.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement SupervisorAgent**

```python
# agents/supervisor.py
import time
from core.incident import Incident, IncidentCategory, IncidentStatus
from core.todo_list import TodoList
from core.llm import OllamaClient
from agents.code.observer import ObserverAgent
from agents.code.detective import DetectiveAgent
from agents.code.coder import CoderAgent
from agents.code.tester import TesterAgent
from agents.code.guardrail import GuardrailAgent
from agents.code.committer import CommitterAgent
from agents.infra.operator import OperatorAgent
from agents.infra.executor import ExecutorAgent
from agents.infra.verifier import InfraVerifierAgent
from agents.shared.learner import LearnerAgent
from agents.shared.rollback import RollbackEngine
from config.tenant_registry import TenantConfig
from ui.terminal import TerminalUI


class SupervisorAgent:
    """
    The brain of the self-healing system.

    SKILL:  Understand the problem deeply before acting.
    RULE:   Never dispatch subagents without a written TodoList plan.

    Pattern (OpenCode-style):
      1. UNDERSTAND — query KG or cluster state for full context
      2. PLAN       — LLM creates a structured TodoList
      3. DISPATCH   — specialist subagents execute each task
      4. DECIDE     — Tester makes deployment decision deterministically
                      (no LLM scoring: test change analysis only)
      5. LEARN      — store outcome in KG for future incidents
    """

    def __init__(
        self,
        config: TenantConfig = None,
        observer: ObserverAgent = None,
        detective: DetectiveAgent = None,
        coder: CoderAgent = None,
        guardrail: GuardrailAgent = None,
        tester: TesterAgent = None,
        committer: CommitterAgent = None,
        operator: OperatorAgent = None,
        executor: ExecutorAgent = None,
        infra_verifier: InfraVerifierAgent = None,
        learner: LearnerAgent = None,
        rollback: RollbackEngine = None,
        llm: OllamaClient = None,
        ui: TerminalUI = None,
    ):
        self.config = config
        self.observer = observer or ObserverAgent()
        self.detective = detective or DetectiveAgent()
        self.coder = coder or CoderAgent()
        self.guardrail = guardrail or GuardrailAgent()
        self.tester = tester or TesterAgent(config=config)
        self.committer = committer or CommitterAgent()
        self.operator = operator or OperatorAgent()
        self.executor = executor or ExecutorAgent()
        self.infra_verifier = infra_verifier or InfraVerifierAgent()
        self.learner = learner or LearnerAgent()
        self.rollback = rollback or RollbackEngine()
        self.llm = llm or OllamaClient()
        self.ui = ui or TerminalUI()

    def handle(self, incident: Incident) -> dict:
        """Routes to code or infra healing based on category."""
        if incident.category == IncidentCategory.CODE:
            return self.handle_code_incident(incident)
        elif incident.category == IncidentCategory.INFRA:
            return self.handle_infra_incident(incident)
        elif incident.category == IncidentCategory.BOTH:
            return self._handle_both(incident)
        else:
            return {"outcome": "skipped", "reason": "transient or unknown"}

    def handle_code_incident(self, incident: Incident) -> dict:
        start = time.time()
        self.ui.incident_detected(incident)

        # ── UNDERSTAND + PLAN ─────────────────────────────────────────
        incident.status = IncidentStatus.PLANNING
        todos_raw = self.llm.create_todos(
            f"Code error: {incident.signal.error_type} "
            f"in {incident.signal.service} — {incident.signal.error_message}"
        )
        todo_list = TodoList(incident_id=incident.id)
        for todo in todos_raw:
            todo_list.add(todo)
        self.ui.todos_created(incident, todo_list)

        # ── OBSERVE ───────────────────────────────────────────────────
        self.ui.agent_started("OBSERVER", "Extracting file and line from stack trace")
        incident.status = IncidentStatus.UNDERSTANDING
        todo_list.start(0)
        obs = self.observer.run(incident)
        todo_list.complete(0, f"Located: {obs.get('file_path')}")
        self.ui.agent_done("OBSERVER", obs)

        # ── DETECT ────────────────────────────────────────────────────
        self.ui.agent_started("DETECTIVE", "Querying knowledge graph + LLM root cause analysis")
        todo_list.start(1)
        det = self.detective.run(incident)
        todo_list.complete(1, det.get("root_cause_analysis", "")[:80])
        self.ui.agent_done("DETECTIVE", det)

        # ── CODE FIX ──────────────────────────────────────────────────
        self.ui.agent_started("CODER", "Writing fix (LLM + KG context)")
        incident.status = IncidentStatus.CODING
        todo_list.start(2)
        code_result = self.coder.run(incident)
        if not code_result.get("fix_written"):
            todo_list.fail(2, "Coder failed to produce a fix")
            return self._escalate(incident, "Coder produced no fix", start)
        todo_list.complete(2, f"{code_result['patch_lines']} lines changed")
        self.ui.agent_done("CODER", code_result)
        self.ui.show_diff(incident)

        # ── GUARDRAIL ─────────────────────────────────────────────────
        # Validate the fix before any test is run:
        # Layer 1: static analysis (syntax, imports)
        # Layer 2: security scan (eval, shell=True, secrets) — hard block
        # Layer 3: semantic review (LLM-as-judge — independent critic)
        max_attempts = self.tester.config.max_fix_attempts if self.tester.config else 3
        guardrail_attempt = 0
        while True:
            self.ui.agent_started(
                "GUARDRAIL",
                f"Validating fix — attempt {guardrail_attempt + 1}/{max_attempts}"
            )
            guardrail_result = self.guardrail.run(incident)
            self.ui.agent_done("GUARDRAIL", {
                "passed": guardrail_result.passed,
                "layer": guardrail_result.layer,
                "reason": guardrail_result.reason,
                "hard_block": guardrail_result.hard_block,
            })

            if guardrail_result.passed:
                break

            if guardrail_result.hard_block:
                # Security violation — never retry, always escalate
                todo_list.fail(2, f"SECURITY BLOCK: {guardrail_result.reason}")
                return self._escalate(
                    incident,
                    f"Security violation in generated fix: {guardrail_result.reason}",
                    start,
                )

            guardrail_attempt += 1
            if guardrail_attempt >= max_attempts:
                todo_list.fail(2, "Guardrail failed after max attempts")
                self.rollback.run(incident, incident.pr_branch)
                self.learner.run(incident, verified=False)
                return self._fail(
                    incident,
                    f"Guardrail rejected fix after {max_attempts} attempts — rolled back",
                    start,
                )

            # Send specific failure reason back to Coder for revision
            self.ui.agent_started(
                "CODER",
                f"Revising fix based on guardrail feedback: {guardrail_result.specific_issue}"
            )
            revised_result = self.coder.run_revision(
                incident,
                feedback=guardrail_result.reason,
                specific_issue=guardrail_result.specific_issue,
            )
            if not revised_result.get("fix_written"):
                todo_list.fail(2, "Coder could not revise fix")
                return self._escalate(incident, "Coder revision failed", start)
            self.ui.agent_done("CODER", revised_result)
            self.ui.show_diff(incident)

        # ── TEST + DECISION ───────────────────────────────────────────
        self.ui.agent_started("TESTER", "Running tests + making deploy decision")
        incident.status = IncidentStatus.TESTING
        todo_list.start(3)
        test_result = self.tester.run(incident)

        if not test_result.get("passed"):
            todo_list.fail(3, "Tests failed after all retries — rolling back")
            self.rollback.run(incident, incident.pr_branch)
            self.learner.run(incident, verified=False)
            return self._fail(incident, "Tests failed — rolled back", start)

        decision = test_result["decision"]   # "direct_deploy" | "open_pr"
        todo_list.complete(
            3,
            f"Passed ({test_result.get('attempts',1)} attempt(s)) "
            f"| existing_tests_modified={incident.existing_tests_modified} "
            f"| new_tests_added={incident.new_tests_added} "
            f"→ {decision}"
        )
        self.ui.agent_done("TESTER", {
            "decision": decision,
            "existing_tests_modified": incident.existing_tests_modified,
            "new_tests_added": incident.new_tests_added,
            "new_test_names": test_result.get("new_test_names", []),
        })

        # ── COMMIT ────────────────────────────────────────────────────
        mode_label = "Direct deploy" if decision == "direct_deploy" else "Opening PR"
        self.ui.agent_started("COMMITTER", mode_label)
        incident.status = IncidentStatus.COMMITTING
        todo_list.start(4)
        commit_result = self.committer.run(incident, decision=decision)
        if not commit_result.get("committed"):
            todo_list.fail(4, "Commit failed")
            return self._escalate(incident, "Could not commit fix", start)
        todo_list.complete(4, f"PR: {commit_result['pr_url']}")
        self.ui.agent_done("COMMITTER", commit_result)

        # ── LEARN ─────────────────────────────────────────────────────
        incident.status = IncidentStatus.RESOLVED
        self.learner.run(incident, verified=True)

        mttr = time.time() - start
        self.ui.incident_closed(incident, "resolved", mttr)

        return {
            "incident_id": incident.id,
            "outcome": "resolved",
            "pr_url": incident.pr_url,
            "mode": commit_result.get("mode"),
            "deploy_decision": decision,
            "existing_tests_modified": incident.existing_tests_modified,
            "new_tests_added": incident.new_tests_added,
            "mttr_seconds": round(mttr, 1),
            "todos_summary": todo_list.summary(),
        }

    def handle_infra_incident(self, incident: Incident) -> dict:
        start = time.time()
        self.ui.incident_detected(incident)

        todos_raw = self.llm.create_todos(
            f"Infra error: {incident.signal.error_type} "
            f"on {incident.signal.service}"
        )
        todo_list = TodoList(incident_id=incident.id)
        for todo in todos_raw:
            todo_list.add(todo)
        self.ui.todos_created(incident, todo_list)

        todo_list.start(0)
        self.ui.agent_started("OPERATOR", "Identifying infra fix from playbook")
        op_result = self.operator.run(incident)
        todo_list.complete(0, f"Action: {op_result['action']}, risk: {op_result['risk']}")
        self.ui.agent_done("OPERATOR", op_result)

        todo_list.start(1)
        self.ui.agent_started("EXECUTOR", f"Applying {op_result['action']}")
        exec_result = self.executor.run(
            incident, op_result["action"], op_result["namespace"]
        )
        if not exec_result.get("success"):
            todo_list.fail(1, exec_result.get("result", "unknown error"))
            return self._escalate(incident, "Executor action failed", start)
        todo_list.complete(1, exec_result.get("result", "done")[:80])
        self.ui.agent_done("EXECUTOR", exec_result)

        todo_list.start(2)
        self.ui.agent_started("VERIFIER", "Confirming service health")
        ver_result = self.infra_verifier.run(incident)
        if not ver_result.get("passed"):
            todo_list.fail(2, "Health checks failed after fix")
            self.learner.run(incident, verified=False)
            return self._fail(incident, "Infra fix did not stabilise service", start)
        todo_list.complete(2, f"{ver_result['checks_passed']} health checks passed")
        self.ui.agent_done("VERIFIER", ver_result)

        incident.status = IncidentStatus.RESOLVED
        self.learner.run(incident, verified=True)
        mttr = time.time() - start
        self.ui.incident_closed(incident, "resolved", mttr)

        return {
            "incident_id": incident.id,
            "outcome": "resolved",
            "action_taken": incident.infra_action_taken,
            "mttr_seconds": round(mttr, 1),
            "todos_summary": todo_list.summary(),
        }

    def _handle_both(self, incident: Incident) -> dict:
        """Run code + infra in sequence, pick whichever succeeds."""
        infra_incident = Incident.from_signal(
            incident.id + "-infra", incident.signal, IncidentCategory.INFRA
        )
        infra_result = self.handle_infra_incident(infra_incident)
        if infra_result.get("outcome") == "resolved":
            return infra_result
        return self.handle_code_incident(incident)

    def _escalate(self, incident: Incident, reason: str, start: float) -> dict:
        incident.status = IncidentStatus.ESCALATED
        mttr = time.time() - start
        self.ui.incident_closed(incident, "escalated", mttr)
        return {
            "incident_id": incident.id,
            "outcome": "escalated",
            "reason": reason,
            "mttr_seconds": round(mttr, 1),
        }

    def _fail(self, incident: Incident, reason: str, start: float) -> dict:
        incident.status = IncidentStatus.ROLLED_BACK
        mttr = time.time() - start
        self.ui.incident_closed(incident, "failed", mttr)
        return {
            "incident_id": incident.id,
            "outcome": "failed",
            "reason": reason,
            "mttr_seconds": round(mttr, 1),
        }
```

- [ ] **Step 4: Run supervisor tests**

```bash
pytest tests/test_supervisor.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/supervisor.py tests/test_supervisor.py
git commit -m "feat: add Supervisor agent — skill+rule brain, understand→plan→dispatch→learn"
```

---

## Phase 10: Demo App + Log Watcher + Terminal UI + Main

### Task 10.1: Demo app with planted bugs

```python
# demo_app/payments.py — Bug 1: missing null check
def get_inventory(order_id: str):
    db = {"order-001": {"price": 29.99, "quantity": 2}}
    return db.get(order_id)  # Returns None for unknown orders

def process_payment(order_id: str) -> dict:
    inventory = get_inventory(order_id)
    total = inventory["price"] * inventory["quantity"]  # BUG: crashes if None
    return {"status": "ok", "order_id": order_id, "total": total}
```

```python
# demo_app/inventory.py — Bug 2: divide by zero
TOTAL_VALUE = {"prod-apple": 100.0, "prod-banana": 50.0}

def get_stock_count(product_id: str) -> int:
    db = {"prod-apple": 10, "prod-banana": 0}
    return db.get(product_id, 0)

def get_unit_price(product_id: str) -> float:
    stock = get_stock_count(product_id)
    return TOTAL_VALUE[product_id] / stock  # BUG: ZeroDivisionError when stock=0
```

```python
# demo_app/checkout.py — Bug 3: empty cart
def calculate_total(cart: list) -> float:
    return sum(item["price"] for item in cart) / len(cart)  # BUG: ZeroDivisionError on []
```

```python
# demo_app/tests/test_payments.py
import pytest
from demo_app.payments import process_payment

def test_valid_order():
    result = process_payment("order-001")
    assert result["status"] == "ok"

def test_unknown_order_raises_value_error():
    # FAILS before fix (TypeError), PASSES after fix (ValueError raised cleanly)
    with pytest.raises(ValueError, match="Inventory not found"):
        process_payment("order-unknown")
```

```python
# demo_app/tests/test_inventory.py
import pytest
from demo_app.inventory import get_unit_price

def test_in_stock_price():
    assert get_unit_price("prod-apple") == 10.0

def test_out_of_stock_raises():
    # FAILS before fix, PASSES after fix
    with pytest.raises(ValueError, match="out of stock"):
        get_unit_price("prod-banana")
```

```python
# demo_app/tests/test_checkout.py
import pytest
from demo_app.checkout import calculate_total

def test_normal_cart():
    cart = [{"price": 10.0}, {"price": 20.0}]
    # NOTE: after fix, returns sum (30.0) not average (15.0)
    assert calculate_total(cart) == pytest.approx(30.0)

def test_empty_cart_returns_zero():
    # FAILS before fix, PASSES after fix
    assert calculate_total([]) == 0.0
```

### Task 10.2: Log Watcher

```python
# watcher/log_watcher.py
import re
import time
import threading
from typing import Callable
from core.signal import Signal, SignalSource

ERROR_PATTERN = re.compile(
    r"(?P<level>ERROR|CRITICAL|FATAL)\s+"
    r"(?P<service>\w+)\s+-\s+"
    r"(?P<error_type>\w+Error|\w+Exception):\s*"
    r"(?P<message>[^\n]+)",
    re.MULTILINE,
)
TRACEBACK_PATTERN = re.compile(
    r'(Traceback.*?(?=\n\S|\Z))', re.DOTALL
)


class LogWatcher:
    """
    Tails a log file or log stream.
    Emits Signal objects when ERROR lines are detected.
    Deduplicates: same error within 60s = single signal.
    """

    def __init__(self, log_path: str, service_name: str, dedupe_seconds: int = 60):
        self.log_path = log_path
        self.service_name = service_name
        self.dedupe_seconds = dedupe_seconds
        self._seen: dict[str, float] = {}
        self._stop = threading.Event()

    def start(self, on_signal: Callable[[Signal], None]) -> threading.Thread:
        t = threading.Thread(target=self._tail, args=(on_signal,), daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()

    def _tail(self, on_signal: Callable[[Signal], None]) -> None:
        with open(self.log_path) as f:
            f.seek(0, 2)  # seek to end
            buffer = ""
            while not self._stop.is_set():
                line = f.readline()
                if line:
                    buffer += line
                    self._process_buffer(buffer, on_signal)
                    if len(buffer) > 10000:
                        buffer = buffer[-5000:]
                else:
                    time.sleep(0.5)

    def _process_buffer(self, text: str, on_signal: Callable[[Signal], None]) -> None:
        for match in ERROR_PATTERN.finditer(text):
            error_type = match.group("error_type")
            message = match.group("message").strip()
            dedup_key = f"{error_type}:{message[:50]}"

            now = time.time()
            last_seen = self._seen.get(dedup_key, 0)
            if now - last_seen < self.dedupe_seconds:
                continue
            self._seen[dedup_key] = now

            stack = ""
            tb_match = TRACEBACK_PATTERN.search(text)
            if tb_match:
                stack = tb_match.group(1).strip()

            occurrence_count = self._seen.get(dedup_key + ":count", 0) + 1
            self._seen[dedup_key + ":count"] = occurrence_count

            signal = Signal(
                source=SignalSource.LOG,
                service=self.service_name,
                error_type=error_type,
                error_message=message,
                stack_trace=stack,
                raw_text=match.group(0),
                occurrence_count=occurrence_count,
            )
            on_signal(signal)
```

### Task 10.3: Terminal UI

```python
# ui/terminal.py
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.syntax import Syntax
from rich import box
from core.incident import Incident
from core.todo_list import TodoList

console = Console()


class TerminalUI:
    def phase(self, name: str, description: str) -> None:
        console.print(f"\n[bold blue]━━ {name} ━━[/] [dim]{description}[/]")

    def incident_detected(self, incident: Incident) -> None:
        category_color = "red" if incident.category.value == "code" else "magenta"
        console.print(Panel(
            f"[bold {category_color}]INCIDENT DETECTED[/]\n\n"
            f"ID:        [yellow]{incident.id}[/]\n"
            f"Category:  [{category_color}]{incident.category.value.upper()}[/]\n"
            f"Service:   [cyan]{incident.signal.service}[/]\n"
            f"Error:     [white]{incident.signal.error_type}[/]\n"
            f"Message:   {incident.signal.error_message}\n\n"
            f"[dim]{incident.signal.stack_trace[:400]}[/]",
            title="[bold]Self-Healing System[/]",
            border_style=category_color,
        ))

    def todos_created(self, incident: Incident, todo_list: TodoList) -> None:
        table = Table(title=f"Repair Plan — {incident.id}", box=box.ROUNDED)
        table.add_column("#", style="dim", width=3)
        table.add_column("Task")
        table.add_column("Agent", style="cyan", width=12)
        for i, item in enumerate(todo_list.items):
            table.add_row(str(i + 1), item.description, item.assigned_to or "—")
        console.print(table)

    def agent_started(self, name: str, task: str) -> None:
        icons = {
            "OBSERVER": "👁", "DETECTIVE": "🔍", "CODER": "✏️",
            "TESTER": "🧪", "SCORER": "📊", "COMMITTER": "📤",
            "OPERATOR": "⚙️", "EXECUTOR": "🔧", "VERIFIER": "✅",
            "LEARNER": "🧠",
        }
        console.print(f"\n{icons.get(name,'▶')}  [bold cyan]{name}[/]  [dim]{task}...[/]")

    def agent_done(self, name: str, result: dict) -> None:
        console.print(f"   [bold green]✓ {name}[/] [dim]done[/]")

    def show_diff(self, incident: Incident) -> None:
        if incident.fix_patch:
            console.print(Panel(
                Syntax(incident.fix_patch, "diff", theme="monokai"),
                title="[bold yellow]Code Fix[/]",
                border_style="yellow",
            ))

    def incident_closed(self, incident: Incident, outcome: str, mttr: float) -> None:
        colours = {"resolved": "green", "failed": "red",
                   "escalated": "yellow", "rolled_back": "red"}
        colour = colours.get(outcome, "white")
        body = (
            f"[bold {colour}]{outcome.upper()}[/]\n\n"
            f"MTTR:       [bold yellow]{mttr:.1f}s[/]\n"
        )
        if incident.pr_url:
            body += f"PR:         [link={incident.pr_url}]{incident.pr_url}[/link]\n"
        if outcome == "resolved":
            body += (
                f"\n[dim italic]No human was paged. "
                f"No laptop was opened.[/]"
            )
        console.print(Panel(body, title=f"[bold {colour}]Incident {outcome}[/]",
                            border_style=colour))
```

### Task 10.4: Main entry point

```python
# main.py
"""
Self-Healing System
===================
Detects production failures, categorises them (code vs infra),
queries knowledge graph, dispatches subagents to fix,
gates on confidence, opens PR or deploys directly.

Usage:
  python main.py                    # watch mode
  python main.py --demo 1           # TypeError in payments
  python main.py --demo 2           # ZeroDivisionError in inventory
  python main.py --demo 3           # CrashLoopBackOff (infra)
  python main.py --demo 4           # Ambiguous: ConnectionError
  python main.py --parse            # Re-index codebase into KG
"""
import argparse
import os
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()
console = Console()

DEMO_SIGNALS = {
    1: {
        "source": "log", "service": "payments",
        "error_type": "TypeError",
        "error_message": "'NoneType' object is not subscriptable",
        "stack_trace": (
            'Traceback (most recent call last):\n'
            '  File "demo_app/app.py", line 18, in payment_endpoint\n'
            '    return process_payment(order_id)\n'
            '  File "demo_app/payments.py", line 18, in process_payment\n'
            '    total = inventory["price"] * inventory["quantity"]\n'
            "TypeError: 'NoneType' object is not subscriptable"
        ),
        "occurrence_count": 5,
    },
    2: {
        "source": "log", "service": "inventory",
        "error_type": "ZeroDivisionError",
        "error_message": "division by zero",
        "stack_trace": (
            'Traceback (most recent call last):\n'
            '  File "demo_app/app.py", line 30, in inventory_price_endpoint\n'
            '    return {"unit_price": get_unit_price(product_id)}\n'
            '  File "demo_app/inventory.py", line 22, in get_unit_price\n'
            '    return TOTAL_VALUE[product_id] / stock\n'
            'ZeroDivisionError: division by zero'
        ),
        "occurrence_count": 4,
    },
    3: {
        "source": "kubernetes", "service": "payments",
        "error_type": "CrashLoopBackOff",
        "error_message": "Back-off restarting failed container",
        "stack_trace": "",
        "occurrence_count": 8,
    },
    4: {
        "source": "log", "service": "payments",
        "error_type": "ConnectionError",
        "error_message": "database unreachable: connection refused on port 5432",
        "stack_trace": (
            'Traceback (most recent call last):\n'
            '  File "demo_app/payments.py", line 45, in get_inventory\n'
            '    conn = db_connect()\n'
            'ConnectionError: database unreachable'
        ),
        "occurrence_count": 6,
    },
}


def run_demo(demo_number: int) -> None:
    from core.signal import Signal, SignalSource
    from core.incident import Incident
    from categoriser.router import Categoriser
    from agents.supervisor import SupervisorAgent
    from config.tenant_registry import load_tenant_config

    config = load_tenant_config("self-healing.yaml")
    raw = DEMO_SIGNALS[demo_number]

    source_map = {"log": SignalSource.LOG, "kubernetes": SignalSource.KUBERNETES}
    signal = Signal(
        source=source_map[raw["source"]],
        service=raw["service"],
        error_type=raw["error_type"],
        error_message=raw["error_message"],
        stack_trace=raw["stack_trace"],
        raw_text=str(raw),
        occurrence_count=raw["occurrence_count"],
    )

    console.print(f"\n[bold yellow]Demo {demo_number}:[/] Firing signal...")

    categoriser = Categoriser()
    incident = categoriser.process(signal)

    if not incident:
        console.print("[yellow]Signal classified as transient — monitoring[/]")
        return

    supervisor = SupervisorAgent(config=config)
    result = supervisor.handle(incident)

    console.print(f"\n[bold]Result:[/]")
    for k, v in result.items():
        console.print(f"  {k}: [cyan]{v}[/]")


def run_parse() -> None:
    from parser.deployment_hook import run_deployment_parse
    run_deployment_parse("demo_app", "self-healing.yaml")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Self-Healing System")
    parser.add_argument("--demo", type=int, choices=[1, 2, 3, 4])
    parser.add_argument("--parse", action="store_true",
                        help="Re-index codebase into knowledge graph")
    args = parser.parse_args()

    if args.parse:
        run_parse()
    elif args.demo:
        run_demo(args.demo)
    else:
        console.print("""
[bold green]Self-Healing System — Watch Mode[/]

Commands:
  python main.py --parse          Index demo_app into KG
  python main.py --demo 1         TypeError in payments (code bug)
  python main.py --demo 2         ZeroDivisionError in inventory (code bug)
  python main.py --demo 3         CrashLoopBackOff in payments (infra)
  python main.py --demo 4         ConnectionError (ambiguous → Stage 2)
""")
```

- [ ] **Step 1: Write demo app files and verify tests fail on buggy code**

```bash
pytest demo_app/tests/ -v
```

Expected:
```
FAILED demo_app/tests/test_payments.py::test_unknown_order_raises_value_error
FAILED demo_app/tests/test_inventory.py::test_out_of_stock_raises
FAILED demo_app/tests/test_checkout.py::test_empty_cart_returns_zero
```

- [ ] **Step 2: Run full test suite for the healing engine**

```bash
pytest tests/ -v --tb=short
```

Expected: all healing engine tests PASS

- [ ] **Step 3: Index demo app into KG**

```bash
python main.py --parse
```

Expected: `KG updated: N files, M functions indexed`

- [ ] **Step 4: Run Demo 1 end-to-end**

```bash
export GITHUB_TOKEN=your_token
export GITHUB_REPO=your-username/self-healing-demo
python main.py --demo 1
```

Expected:
```
INCIDENT DETECTED — CODE
REPAIR PLAN (5 todos)
OBSERVER ✓
DETECTIVE ✓
CODER ✓ [shows diff]
TESTER ✓ — 3 passed
SCORER ✓ — 0.92, low risk → auto_deploy
COMMITTER ✓ — PR opened
RESOLVED — MTTR: 94.2s
No human was paged. No laptop was opened.
```

- [ ] **Step 5: Run Demo 3 (infra)**

```bash
python main.py --demo 3
```

Expected: INFRA PATH, Operator+Executor+Verifier run, resolved

- [ ] **Step 6: Run Demo 4 (ambiguous)**

```bash
python main.py --demo 4
```

Expected: BOTH → Stage 2 → score comparison → routes to correct path

- [ ] **Step 7: Final commit**

```bash
git add demo_app/ watcher/ ui/ main.py tests/
git commit -m "feat: complete self-healing system — demo app, watcher, UI, main entry point"
```

---

## Summary

| Phase | What Gets Built | Tests |
|---|---|---|
| 0 | Environment + Neo4j + dependencies | manual verification |
| 1 | TenantConfig + self-healing.yaml | test_tenant_registry |
| 2 | Signal, Incident, TodoList, OllamaClient | test_signal, test_incident, test_todo_list, test_llm |
| 3 | Neo4j client + KG builder + embedder + querier | test_kg_builder, test_kg_querier |
| 4 | Categoriser Stage 1 + Stage 2 + Transient + Router | test_categoriser_stage1, test_categoriser_stage2 |
| 5 | Observer, Detective, Coder, Guardrail, Tester (deploy decision), Committer | test_observer, test_coder, test_guardrail, test_tester, test_committer |
| 6 | Operator, Executor, InfraVerifier | test_operator |
| 7 | RollbackEngine | test_rollback |
| 8 | LearnerAgent → KG feedback | test_learner |
| 9 | SupervisorAgent (brain) | test_supervisor |
| 10 | Demo app + LogWatcher + TerminalUI + main.py | demo_app/tests + smoke tests |

**Four demo scenarios:**
```bash
python main.py --demo 1   # TypeError: code bug → detect→fix→test→PR
python main.py --demo 2   # ZeroDivisionError: code bug → detect→fix→test→PR
python main.py --demo 3   # CrashLoopBackOff: infra → rollback
python main.py --demo 4   # ConnectionError: ambiguous → Stage 2 → routes correctly
```

**What makes this win:**
- Every team builds: alert → restart pod
- You build: signal → categorise (code vs infra vs ambiguous) → query knowledge graph → understand deeply → plan (TodoList) → specialist subagents → confidence-gated delivery → learn → repeat
- The KG gets smarter with every incident. On Day 30, the system knows your codebase better than a new joiner.
