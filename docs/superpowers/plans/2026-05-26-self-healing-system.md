# Self-Healing System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a laptop-local self-healing Kubernetes system with a Supervisor + SubAgent architecture (OpenCode-style) that autonomously detects, diagnoses, remediates, and proactively prevents infrastructure failures — with zero cloud dependency.

**Architecture:** A LangGraph-based Supervisor Agent receives incident signals, reasons about them using a local Ollama LLM, creates a structured TodoList, and dispatches specialist subagents (Observer, Detective, Surgeon, Verifier, Learner). A separate Janitor Agent runs on a cron schedule, scans the cluster for proactive hygiene issues, and produces a clean diff without any failure trigger.

**Tech Stack:** Python 3.11+, LangGraph, Ollama (llama3.1:8b), kind (local Kubernetes), Prometheus + Loki + kube-state-metrics, kubectl Python client, SQLite (incident DB + playbooks), Rich (terminal UI), PyYAML, pip-audit, Helm

---

## Project File Structure

```
self-healing/
├── main.py                          # Entry point: starts supervisor + janitor
├── requirements.txt
├── .env.example
│
├── cluster/                         # KIND cluster + fake microservices
│   ├── kind-config.yaml             # Local K8s cluster definition
│   ├── manifests/
│   │   ├── namespace.yaml
│   │   ├── frontend-deployment.yaml
│   │   ├── checkout-deployment.yaml
│   │   ├── payments-deployment.yaml
│   │   ├── inventory-deployment.yaml
│   │   └── ingress.yaml             # Intentionally deprecated API (for Janitor demo)
│   ├── monitoring/
│   │   ├── prometheus-config.yaml
│   │   └── loki-config.yaml
│   └── chaos/
│       ├── inject_crashloop.sh      # Demo 1: delete pod / bad env var
│       ├── inject_cascade.sh        # Demo 2: kill payments, watch cascade
│       └── inject_janitor_issues.sh # Demo 3: plant CVE + memory limit + deprecated API
│
├── agents/
│   ├── supervisor.py                # LangGraph state machine, TodoList creator
│   ├── janitor.py                   # Cron-driven proactive scanner
│   └── subagents/
│       ├── observer.py              # Fetches logs, metrics, events from K8s
│       ├── detective.py             # LLM-powered RCA + blame chain
│       ├── surgeon.py               # Executes kubectl / Helm remediations
│       ├── verifier.py              # Health checks + metric validation
│       └── learner.py               # Writes to incident DB, updates playbooks
│
├── core/
│   ├── incident.py                  # Incident dataclass (shared state object)
│   ├── todo_list.py                 # TodoItem + TodoList types
│   ├── tool_registry.py             # All kubectl/Prometheus tools in one place
│   └── llm.py                       # Ollama client wrapper
│
├── knowledge/
│   ├── db.py                        # SQLite: incidents + playbooks tables
│   ├── playbooks/
│   │   ├── crashloop.yaml           # Seed playbook: CrashLoopBackOff
│   │   ├── oom.yaml                 # Seed playbook: OOMKilled
│   │   └── service_unavailable.yaml # Seed playbook: 503 cascade
│   └── rag.py                       # Simple embedding search over playbooks
│
├── ui/
│   └── terminal.py                  # Rich-based live agent stream display
│
└── tests/
    ├── test_incident.py
    ├── test_todo_list.py
    ├── test_observer.py
    ├── test_detective.py
    ├── test_surgeon.py
    ├── test_verifier.py
    ├── test_learner.py
    ├── test_supervisor.py
    └── test_janitor.py
```

---

## Phase 0: Environment Bootstrap

### Task 0.1: Install prerequisites

**Files:** None (system setup)

- [ ] **Step 1: Install kind, kubectl, ollama**

```bash
brew install kind kubectl helm
brew install ollama
```

- [ ] **Step 2: Pull the LLM model**

```bash
ollama pull llama3.1:8b
ollama serve &
```

Expected: model downloads (~4.7GB), server starts on localhost:11434

- [ ] **Step 3: Create Python virtual environment**

```bash
cd "/Users/arghyabanerjee/Desktop/Self Healing"
python3 -m venv .venv
source .venv/bin/activate
```

- [ ] **Step 4: Create requirements.txt**

```
langgraph==0.2.28
langchain-community==0.3.1
langchain-ollama==0.2.0
kubernetes==30.1.0
prometheus-api-client==0.5.5
rich==13.7.1
pyyaml==6.0.2
sqlalchemy==2.0.36
pip-audit==2.7.3
schedule==1.2.2
httpx==0.27.2
pytest==8.3.3
pytest-asyncio==0.24.0
```

- [ ] **Step 5: Install dependencies**

```bash
pip install -r requirements.txt
```

Expected: all packages install without error

- [ ] **Step 6: Commit**

```bash
git init
git add requirements.txt .env.example
git commit -m "chore: bootstrap project with dependencies"
```

---

## Phase 1: Fake Microservice Cluster

### Task 1.1: KIND cluster config

**Files:**
- Create: `cluster/kind-config.yaml`

- [ ] **Step 1: Write failing test**

```python
# tests/test_cluster.py
import subprocess

def test_kind_config_valid():
    result = subprocess.run(
        ["kind", "create", "cluster", "--config", "cluster/kind-config.yaml", "--dry-run"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_cluster.py -v
```

Expected: FAIL — `cluster/kind-config.yaml` does not exist

- [ ] **Step 3: Write the cluster config**

```yaml
# cluster/kind-config.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: self-healing-demo
nodes:
  - role: control-plane
    extraPortMappings:
      - containerPort: 30000
        hostPort: 30000
        protocol: TCP
  - role: worker
  - role: worker
```

- [ ] **Step 4: Create the cluster**

```bash
kind create cluster --config cluster/kind-config.yaml
kubectl cluster-info --context kind-self-healing-demo
```

Expected: cluster running, 3 nodes Ready

- [ ] **Step 5: Commit**

```bash
git add cluster/kind-config.yaml
git commit -m "feat: add KIND cluster config with 2 workers"
```

---

### Task 1.2: Fake microservice manifests

**Files:**
- Create: `cluster/manifests/namespace.yaml`
- Create: `cluster/manifests/checkout-deployment.yaml`
- Create: `cluster/manifests/payments-deployment.yaml`
- Create: `cluster/manifests/inventory-deployment.yaml`
- Create: `cluster/manifests/frontend-deployment.yaml`
- Create: `cluster/manifests/ingress.yaml`

These are real Kubernetes deployments using public images (nginx, hashicorp/http-echo) — no custom Docker builds needed.

- [ ] **Step 1: Write namespace manifest**

```yaml
# cluster/manifests/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: ecommerce
```

- [ ] **Step 2: Write checkout deployment**

```yaml
# cluster/manifests/checkout-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: checkout
  namespace: ecommerce
  labels:
    app: checkout
    tier: backend
spec:
  replicas: 2
  selector:
    matchLabels:
      app: checkout
  template:
    metadata:
      labels:
        app: checkout
    spec:
      containers:
        - name: checkout
          image: hashicorp/http-echo:0.2.3
          args: ["-text=checkout-ok", "-listen=:8080"]
          ports:
            - containerPort: 8080
          resources:
            requests:
              memory: "32Mi"
              cpu: "50m"
            limits:
              memory: "64Mi"
              cpu: "100m"
          env:
            - name: SERVICE_VERSION
              value: "1.0.0"
---
apiVersion: v1
kind: Service
metadata:
  name: checkout
  namespace: ecommerce
spec:
  selector:
    app: checkout
  ports:
    - port: 8080
      targetPort: 8080
```

- [ ] **Step 3: Write payments deployment**

```yaml
# cluster/manifests/payments-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payments
  namespace: ecommerce
  labels:
    app: payments
    tier: backend
    depends-on: inventory
spec:
  replicas: 2
  selector:
    matchLabels:
      app: payments
  template:
    metadata:
      labels:
        app: payments
    spec:
      containers:
        - name: payments
          image: hashicorp/http-echo:0.2.3
          args: ["-text=payments-ok", "-listen=:8081"]
          ports:
            - containerPort: 8081
          resources:
            requests:
              memory: "64Mi"
              cpu: "50m"
            limits:
              memory: "128Mi"    # intentionally low for Janitor demo
              cpu: "200m"
---
apiVersion: v1
kind: Service
metadata:
  name: payments
  namespace: ecommerce
spec:
  selector:
    app: payments
  ports:
    - port: 8081
      targetPort: 8081
```

- [ ] **Step 4: Write inventory deployment**

```yaml
# cluster/manifests/inventory-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: inventory
  namespace: ecommerce
  labels:
    app: inventory
    tier: backend
spec:
  replicas: 1
  selector:
    matchLabels:
      app: inventory
  template:
    metadata:
      labels:
        app: inventory
    spec:
      containers:
        - name: inventory
          image: hashicorp/http-echo:0.2.3
          args: ["-text=inventory-ok", "-listen=:8082"]
          ports:
            - containerPort: 8082
          resources:
            requests:
              memory: "32Mi"
              cpu: "25m"
            limits:
              memory: "64Mi"
              cpu: "100m"
---
apiVersion: v1
kind: Service
metadata:
  name: inventory
  namespace: ecommerce
spec:
  selector:
    app: inventory
  ports:
    - port: 8082
      targetPort: 8082
```

- [ ] **Step 5: Write frontend deployment**

```yaml
# cluster/manifests/frontend-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend
  namespace: ecommerce
  labels:
    app: frontend
    tier: frontend
spec:
  replicas: 2
  selector:
    matchLabels:
      app: frontend
  template:
    metadata:
      labels:
        app: frontend
    spec:
      containers:
        - name: frontend
          image: nginx:1.25.3
          ports:
            - containerPort: 80
          resources:
            requests:
              memory: "32Mi"
              cpu: "25m"
            limits:
              memory: "64Mi"
              cpu: "100m"
---
apiVersion: v1
kind: Service
metadata:
  name: frontend
  namespace: ecommerce
spec:
  selector:
    app: frontend
  ports:
    - port: 80
      targetPort: 80
  type: NodePort
```

- [ ] **Step 6: Write ingress with intentionally deprecated API (for Janitor demo)**

```yaml
# cluster/manifests/ingress.yaml
# NOTE: networking.k8s.io/v1beta1 is deprecated — intentional for Janitor scan demo
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: ecommerce-ingress
  namespace: ecommerce
  annotations:
    deprecated-annotation: "true"  # Janitor will flag this
spec:
  rules:
    - host: ecommerce.local
      http:
        paths:
          - path: /checkout
            pathType: Prefix
            backend:
              service:
                name: checkout
                port:
                  number: 8080
          - path: /payments
            pathType: Prefix
            backend:
              service:
                name: payments
                port:
                  number: 8081
```

- [ ] **Step 7: Apply all manifests**

```bash
kubectl apply -f cluster/manifests/namespace.yaml
kubectl apply -f cluster/manifests/
kubectl -n ecommerce get pods --watch
```

Expected: all pods Running within 60s

- [ ] **Step 8: Commit**

```bash
git add cluster/manifests/
git commit -m "feat: add fake ecommerce microservice mesh to KIND cluster"
```

---

### Task 1.3: Chaos injection scripts

**Files:**
- Create: `cluster/chaos/inject_crashloop.sh`
- Create: `cluster/chaos/inject_cascade.sh`
- Create: `cluster/chaos/inject_janitor_issues.sh`

- [ ] **Step 1: Write crashloop injection script (Demo 1)**

```bash
#!/bin/bash
# cluster/chaos/inject_crashloop.sh
# Demo 1: patch checkout with a bad env var, causing CrashLoopBackOff
set -e
echo "[CHAOS] Injecting CrashLoop into checkout deployment..."
kubectl -n ecommerce patch deployment checkout --type=json \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/args","value":["-text=broken","-listen=INVALID_PORT"]}]'
echo "[CHAOS] Checkout deployment patched. Watch pods enter CrashLoopBackOff."
echo "[CHAOS] Run: kubectl -n ecommerce get pods --watch"
```

- [ ] **Step 2: Write cascade injection script (Demo 2)**

```bash
#!/bin/bash
# cluster/chaos/inject_cascade.sh
# Demo 2: scale payments to 0, simulating service unavailability cascade
set -e
echo "[CHAOS] Scaling payments to 0 replicas — simulating 503 cascade..."
kubectl -n ecommerce scale deployment payments --replicas=0
echo "[CHAOS] Payments is down. Checkout will start failing."
echo "[CHAOS] Self-healing system should detect and restore within 60s."
```

- [ ] **Step 3: Write janitor issue injection script (Demo 3)**

```bash
#!/bin/bash
# cluster/chaos/inject_janitor_issues.sh
# Demo 3: plant issues the Janitor will find and fix
set -e

echo "[CHAOS] Planting memory limit time-bomb in payments (128Mi -> borderline)..."
# Already set in manifest, just annotate for tracking
kubectl -n ecommerce annotate deployment payments \
  self-healing/janitor-target=memory-limit --overwrite

echo "[CHAOS] Adding deprecated annotation to ingress..."
kubectl -n ecommerce annotate ingress ecommerce-ingress \
  self-healing/janitor-target=deprecated-api --overwrite

echo "[CHAOS] Janitor issues planted. Run the Janitor agent to see it discover and fix."
```

- [ ] **Step 4: Make scripts executable**

```bash
chmod +x cluster/chaos/*.sh
```

- [ ] **Step 5: Commit**

```bash
git add cluster/chaos/
git commit -m "feat: add chaos injection scripts for three demo scenarios"
```

---

## Phase 2: Core Data Types

### Task 2.1: Incident and TodoList types

**Files:**
- Create: `core/incident.py`
- Create: `core/todo_list.py`
- Create: `tests/test_incident.py`
- Create: `tests/test_todo_list.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_incident.py
from core.incident import Incident, IncidentStatus, IncidentType

def test_incident_creation():
    inc = Incident(
        id="inc-001",
        type=IncidentType.CRASHLOOP,
        namespace="ecommerce",
        affected_resource="checkout",
        raw_signal={"reason": "CrashLoopBackOff", "pod": "checkout-abc123"}
    )
    assert inc.id == "inc-001"
    assert inc.status == IncidentStatus.DETECTED
    assert inc.todos == []
    assert inc.resolution is None

def test_incident_status_transition():
    inc = Incident(
        id="inc-002",
        type=IncidentType.OOM,
        namespace="ecommerce",
        affected_resource="payments",
        raw_signal={"reason": "OOMKilled"}
    )
    inc.status = IncidentStatus.HEALING
    assert inc.status == IncidentStatus.HEALING
```

```python
# tests/test_todo_list.py
from core.todo_list import TodoList, TodoItem, TodoStatus

def test_todo_list_creation():
    tl = TodoList(incident_id="inc-001")
    tl.add("Collect logs from checkout pods")
    tl.add("Query Prometheus for memory spike")
    tl.add("Identify failing deployment")
    assert len(tl.items) == 3
    assert all(i.status == TodoStatus.PENDING for i in tl.items)

def test_todo_list_complete_item():
    tl = TodoList(incident_id="inc-001")
    tl.add("Collect logs")
    tl.start(0)
    assert tl.items[0].status == TodoStatus.IN_PROGRESS
    tl.complete(0, result="logs: OOMKilled at 03:14:22")
    assert tl.items[0].status == TodoStatus.DONE
    assert tl.items[0].result == "logs: OOMKilled at 03:14:22"

def test_todo_list_all_done():
    tl = TodoList(incident_id="inc-001")
    tl.add("Task A")
    tl.complete(0, result="done")
    assert tl.all_done() is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_incident.py tests/test_todo_list.py -v
```

Expected: FAIL — modules not found

- [ ] **Step 3: Implement Incident**

```python
# core/incident.py
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from datetime import datetime


class IncidentType(Enum):
    CRASHLOOP = "CrashLoopBackOff"
    OOM = "OOMKilled"
    SERVICE_UNAVAILABLE = "ServiceUnavailable"
    DEPLOYMENT_FAILED = "DeploymentFailed"
    RESOURCE_EXHAUSTION = "ResourceExhaustion"
    UNKNOWN = "Unknown"


class IncidentStatus(Enum):
    DETECTED = "detected"
    ANALYZING = "analyzing"
    HEALING = "healing"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    FAILED = "failed"
    ESCALATED = "escalated"


@dataclass
class Incident:
    id: str
    type: IncidentType
    namespace: str
    affected_resource: str
    raw_signal: dict[str, Any]
    status: IncidentStatus = IncidentStatus.DETECTED
    todos: list = field(default_factory=list)
    root_cause: Optional[str] = None
    resolution: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None
    context: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 4: Implement TodoList**

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
    status: TodoStatus = TodoStatus.PENDING
    result: Optional[str] = None
    assigned_to: Optional[str] = None


@dataclass
class TodoList:
    incident_id: str
    items: list[TodoItem] = field(default_factory=list)

    def add(self, description: str, assigned_to: Optional[str] = None) -> int:
        item = TodoItem(description=description, assigned_to=assigned_to)
        self.items.append(item)
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
        return all(i.status in (TodoStatus.DONE, TodoStatus.FAILED) for i in self.items)

    def pending_items(self) -> list[tuple[int, TodoItem]]:
        return [(i, item) for i, item in enumerate(self.items)
                if item.status == TodoStatus.PENDING]

    def summary(self) -> str:
        done = sum(1 for i in self.items if i.status == TodoStatus.DONE)
        failed = sum(1 for i in self.items if i.status == TodoStatus.FAILED)
        total = len(self.items)
        return f"{done}/{total} done, {failed} failed"
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_incident.py tests/test_todo_list.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add core/ tests/test_incident.py tests/test_todo_list.py
git commit -m "feat: add Incident and TodoList core types"
```

---

### Task 2.2: LLM client wrapper

**Files:**
- Create: `core/llm.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_llm.py
from unittest.mock import patch, MagicMock
from core.llm import OllamaClient

def test_ollama_client_classify():
    client = OllamaClient(model="llama3.1:8b", base_url="http://localhost:11434")
    with patch("httpx.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"message": {"content": "CrashLoopBackOff"}}
        )
        result = client.chat("Classify this incident: pod restarting repeatedly")
        assert isinstance(result, str)
        assert len(result) > 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_llm.py -v
```

Expected: FAIL — module not found

- [ ] **Step 3: Implement OllamaClient**

```python
# core/llm.py
import httpx
from typing import Optional


class OllamaClient:
    def __init__(self, model: str = "llama3.1:8b", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url

    def chat(self, prompt: str, system: Optional[str] = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = httpx.post(
            f"{self.base_url}/api/chat",
            json={"model": self.model, "messages": messages, "stream": False},
            timeout=120.0
        )
        response.raise_for_status()
        return response.json()["message"]["content"]

    def classify_incident(self, signal: dict) -> str:
        system = (
            "You are an expert SRE. Given a Kubernetes incident signal, "
            "classify the root cause type. Be concise. Output ONLY the classification "
            "and a one-sentence reason. Valid types: CrashLoopBackOff, OOMKilled, "
            "ServiceUnavailable, DeploymentFailed, ResourceExhaustion, Unknown."
        )
        prompt = f"Incident signal:\n{signal}\n\nClassify this."
        return self.chat(prompt, system=system)

    def create_todos(self, incident_summary: str, playbook_hint: Optional[str] = None) -> list[str]:
        system = (
            "You are an expert SRE creating a repair plan. "
            "Given an incident, output a numbered list of concrete diagnostic and "
            "remediation steps. Each step must be specific and actionable. "
            "Output ONLY the numbered list, nothing else."
        )
        prompt = f"Incident: {incident_summary}"
        if playbook_hint:
            prompt += f"\n\nRelevant past playbook hint:\n{playbook_hint}"
        raw = self.chat(prompt, system=system)
        lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]
        todos = []
        for line in lines:
            # strip numbering like "1." or "1)"
            if line and line[0].isdigit():
                cleaned = line.split(".", 1)[-1].strip() if "." in line[:3] else line
                cleaned = cleaned.split(")", 1)[-1].strip() if ")" in line[:3] else cleaned
                if cleaned:
                    todos.append(cleaned)
        return todos if todos else [line for line in lines if line]

    def diagnose_root_cause(self, context: dict) -> str:
        system = (
            "You are a senior SRE performing root cause analysis. "
            "Given the collected context (logs, metrics, events, cluster state), "
            "identify the single most likely root cause. "
            "Format: ROOT CAUSE: <one sentence>. EVIDENCE: <bullet points>. "
            "RECOMMENDED ACTION: <specific kubectl or config command>."
        )
        prompt = f"Context collected:\n{context}"
        return self.chat(prompt, system=system)

    def select_remediation(self, root_cause: str, playbooks: list[dict]) -> dict:
        system = (
            "You are an expert SRE selecting the safest remediation. "
            "Given a root cause and available playbooks, select the best playbook "
            "and output JSON: {\"playbook_name\": \"...\", \"action\": \"...\", "
            "\"risk\": \"low|medium|high\", \"reason\": \"...\"}"
        )
        playbook_list = "\n".join(
            f"- {p['name']}: {p['description']}" for p in playbooks
        )
        prompt = f"Root cause: {root_cause}\n\nAvailable playbooks:\n{playbook_list}"
        import json
        raw = self.chat(prompt, system=system)
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            return json.loads(raw[start:end])
        except Exception:
            return {"playbook_name": "manual", "action": raw, "risk": "unknown", "reason": raw}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_llm.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/llm.py tests/test_llm.py
git commit -m "feat: add Ollama LLM client with classify, todos, diagnose, remediation"
```

---

### Task 2.3: Tool registry (kubectl + Prometheus wrappers)

**Files:**
- Create: `core/tool_registry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_tool_registry.py
from unittest.mock import patch, MagicMock
from core.tool_registry import KubectlTools, PrometheusTools

def test_kubectl_get_pod_status():
    tools = KubectlTools(namespace="ecommerce")
    with patch("kubernetes.client.CoreV1Api") as mock_api:
        mock_pod = MagicMock()
        mock_pod.metadata.name = "checkout-abc123"
        mock_pod.status.phase = "Running"
        mock_pod.status.container_statuses = []
        mock_api.return_value.list_namespaced_pod.return_value.items = [mock_pod]
        pods = tools.get_pod_status("checkout")
        assert len(pods) == 1
        assert pods[0]["name"] == "checkout-abc123"
        assert pods[0]["phase"] == "Running"

def test_kubectl_tools_list_events():
    tools = KubectlTools(namespace="ecommerce")
    with patch("kubernetes.client.CoreV1Api") as mock_api:
        mock_event = MagicMock()
        mock_event.reason = "BackOff"
        mock_event.message = "Back-off restarting failed container"
        mock_event.involved_object.name = "checkout-abc123"
        mock_event.count = 5
        mock_api.return_value.list_namespaced_event.return_value.items = [mock_event]
        events = tools.get_events("checkout")
        assert len(events) == 1
        assert events[0]["reason"] == "BackOff"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_tool_registry.py -v
```

Expected: FAIL — module not found

- [ ] **Step 3: Implement KubectlTools and PrometheusTools**

```python
# core/tool_registry.py
import subprocess
import json
from typing import Optional
from kubernetes import client, config


def _load_kube_config():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


class KubectlTools:
    def __init__(self, namespace: str = "ecommerce"):
        self.namespace = namespace
        _load_kube_config()
        self.v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()

    def get_pod_status(self, label_selector: str) -> list[dict]:
        pods = self.v1.list_namespaced_pod(
            self.namespace, label_selector=f"app={label_selector}"
        ).items
        result = []
        for pod in pods:
            waiting = None
            if pod.status.container_statuses:
                cs = pod.status.container_statuses[0]
                if cs.state.waiting:
                    waiting = cs.state.waiting.reason
            result.append({
                "name": pod.metadata.name,
                "phase": pod.status.phase,
                "restart_count": (
                    pod.status.container_statuses[0].restart_count
                    if pod.status.container_statuses else 0
                ),
                "waiting_reason": waiting,
            })
        return result

    def get_events(self, resource_name: str) -> list[dict]:
        events = self.v1.list_namespaced_event(self.namespace).items
        filtered = [
            e for e in events
            if resource_name in (e.involved_object.name or "")
        ]
        return [
            {
                "reason": e.reason,
                "message": e.message,
                "object": e.involved_object.name,
                "count": e.count,
            }
            for e in filtered
        ]

    def get_pod_logs(self, pod_name: str, tail_lines: int = 100) -> str:
        try:
            return self.v1.read_namespaced_pod_log(
                pod_name, self.namespace, tail_lines=tail_lines
            )
        except Exception as e:
            return f"[log error: {e}]"

    def rollout_undo(self, deployment_name: str) -> str:
        result = subprocess.run(
            ["kubectl", "-n", self.namespace, "rollout", "undo",
             f"deployment/{deployment_name}"],
            capture_output=True, text=True
        )
        return result.stdout + result.stderr

    def restart_deployment(self, deployment_name: str) -> str:
        result = subprocess.run(
            ["kubectl", "-n", self.namespace, "rollout", "restart",
             f"deployment/{deployment_name}"],
            capture_output=True, text=True
        )
        return result.stdout + result.stderr

    def scale_deployment(self, deployment_name: str, replicas: int) -> str:
        result = subprocess.run(
            ["kubectl", "-n", self.namespace, "scale",
             f"deployment/{deployment_name}", f"--replicas={replicas}"],
            capture_output=True, text=True
        )
        return result.stdout + result.stderr

    def patch_resource_limits(self, deployment_name: str,
                               memory_limit: str, cpu_limit: str) -> str:
        patch = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [{
                            "name": deployment_name,
                            "resources": {
                                "limits": {
                                    "memory": memory_limit,
                                    "cpu": cpu_limit
                                }
                            }
                        }]
                    }
                }
            }
        }
        self.apps_v1.patch_namespaced_deployment(
            deployment_name, self.namespace, patch
        )
        return f"Patched {deployment_name}: memory={memory_limit}, cpu={cpu_limit}"

    def get_deployment_status(self, deployment_name: str) -> dict:
        d = self.apps_v1.read_namespaced_deployment(deployment_name, self.namespace)
        return {
            "name": deployment_name,
            "replicas": d.spec.replicas,
            "ready_replicas": d.status.ready_replicas or 0,
            "available_replicas": d.status.available_replicas or 0,
        }

    def is_healthy(self, deployment_name: str) -> bool:
        status = self.get_deployment_status(deployment_name)
        return status["ready_replicas"] >= status["replicas"]


class PrometheusTools:
    def __init__(self, base_url: str = "http://localhost:9090"):
        self.base_url = base_url

    def query(self, promql: str) -> list[dict]:
        import httpx
        try:
            resp = httpx.get(
                f"{self.base_url}/api/v1/query",
                params={"query": promql},
                timeout=10.0
            )
            resp.raise_for_status()
            return resp.json().get("data", {}).get("result", [])
        except Exception as e:
            return [{"error": str(e)}]

    def get_pod_memory_usage(self, namespace: str, pod_name: str) -> Optional[float]:
        results = self.query(
            f'container_memory_working_set_bytes{{namespace="{namespace}",'
            f'pod=~"{pod_name}.*"}}'
        )
        if results and "value" in results[0]:
            return float(results[0]["value"][1]) / (1024 * 1024)  # MB
        return None

    def get_error_rate(self, service: str, namespace: str) -> Optional[float]:
        results = self.query(
            f'rate(http_requests_total{{namespace="{namespace}",'
            f'service="{service}",status=~"5.."}}[5m])'
        )
        if results and "value" in results[0]:
            return float(results[0]["value"][1])
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_tool_registry.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/tool_registry.py tests/test_tool_registry.py
git commit -m "feat: add kubectl and prometheus tool registry"
```

---

## Phase 3: SubAgents

### Task 3.1: Observer SubAgent

**Files:**
- Create: `agents/subagents/observer.py`
- Create: `tests/test_observer.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_observer.py
from unittest.mock import MagicMock, patch
from core.incident import Incident, IncidentType
from agents.subagents.observer import ObserverAgent

def test_observer_collects_context():
    incident = Incident(
        id="inc-001",
        type=IncidentType.CRASHLOOP,
        namespace="ecommerce",
        affected_resource="checkout",
        raw_signal={"reason": "CrashLoopBackOff", "pod": "checkout-abc"}
    )
    mock_tools = MagicMock()
    mock_tools.get_pod_status.return_value = [
        {"name": "checkout-abc", "phase": "Running", "restart_count": 8, "waiting_reason": "CrashLoopBackOff"}
    ]
    mock_tools.get_events.return_value = [
        {"reason": "BackOff", "message": "restarting failed container", "object": "checkout-abc", "count": 8}
    ]
    mock_tools.get_pod_logs.return_value = "Error: invalid port INVALID_PORT"

    observer = ObserverAgent(kubectl_tools=mock_tools)
    context = observer.run(incident)

    assert "pod_status" in context
    assert "events" in context
    assert "logs" in context
    assert context["pod_status"][0]["restart_count"] == 8
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_observer.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement ObserverAgent**

```python
# agents/subagents/observer.py
from core.incident import Incident
from core.tool_registry import KubectlTools, PrometheusTools


class ObserverAgent:
    """
    Collects all observable context for an incident:
    pod status, events, logs, and metrics.
    Returns a context dict consumed by the Detective.
    """

    def __init__(
        self,
        kubectl_tools: KubectlTools = None,
        prometheus_tools: PrometheusTools = None
    ):
        self.kubectl = kubectl_tools or KubectlTools()
        self.prometheus = prometheus_tools or PrometheusTools()

    def run(self, incident: Incident) -> dict:
        resource = incident.affected_resource
        namespace = incident.namespace

        pod_status = self.kubectl.get_pod_status(resource)
        events = self.kubectl.get_events(resource)

        logs = {}
        for pod in pod_status:
            logs[pod["name"]] = self.kubectl.get_pod_logs(pod["name"])

        memory_usage = None
        error_rate = None
        if self.prometheus:
            memory_usage = self.prometheus.get_pod_memory_usage(namespace, resource)
            error_rate = self.prometheus.get_error_rate(resource, namespace)

        context = {
            "pod_status": pod_status,
            "events": events,
            "logs": logs,
            "memory_usage_mb": memory_usage,
            "error_rate_5m": error_rate,
            "raw_signal": incident.raw_signal,
        }
        incident.context.update(context)
        return context
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_observer.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/subagents/observer.py tests/test_observer.py
git commit -m "feat: add Observer subagent"
```

---

### Task 3.2: Detective SubAgent

**Files:**
- Create: `agents/subagents/detective.py`
- Create: `tests/test_detective.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_detective.py
from unittest.mock import MagicMock
from core.incident import Incident, IncidentType
from agents.subagents.detective import DetectiveAgent

def test_detective_produces_root_cause():
    incident = Incident(
        id="inc-001",
        type=IncidentType.CRASHLOOP,
        namespace="ecommerce",
        affected_resource="checkout",
        raw_signal={"reason": "CrashLoopBackOff"}
    )
    incident.context = {
        "pod_status": [{"name": "checkout-abc", "phase": "Running", "restart_count": 10, "waiting_reason": "CrashLoopBackOff"}],
        "events": [{"reason": "BackOff", "message": "back-off restarting", "object": "checkout-abc", "count": 10}],
        "logs": {"checkout-abc": "Error: listen INVALID_PORT"},
        "memory_usage_mb": None,
        "error_rate_5m": None,
    }

    mock_llm = MagicMock()
    mock_llm.diagnose_root_cause.return_value = (
        "ROOT CAUSE: Invalid port in container args from bad deployment.\n"
        "EVIDENCE:\n- restart_count=10\n- Error: listen INVALID_PORT\n"
        "RECOMMENDED ACTION: kubectl rollout undo deployment/checkout"
    )

    detective = DetectiveAgent(llm=mock_llm)
    result = detective.run(incident)

    assert result["root_cause"] is not None
    assert "RECOMMENDED ACTION" in result["root_cause"]
    assert incident.root_cause is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_detective.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement DetectiveAgent**

```python
# agents/subagents/detective.py
from core.incident import Incident
from core.llm import OllamaClient


class DetectiveAgent:
    """
    Performs LLM-powered root cause analysis.
    Takes the Observer's context and produces a structured root cause + recommendation.
    """

    def __init__(self, llm: OllamaClient = None):
        self.llm = llm or OllamaClient()

    def run(self, incident: Incident) -> dict:
        context = incident.context

        # Build a compact context summary for the LLM
        summary = {
            "incident_type": incident.type.value,
            "affected": incident.affected_resource,
            "namespace": incident.namespace,
            "restart_counts": [
                f"{p['name']}: {p['restart_count']} restarts, waiting={p['waiting_reason']}"
                for p in context.get("pod_status", [])
            ],
            "recent_events": [
                f"{e['reason']}: {e['message']} (x{e['count']})"
                for e in context.get("events", [])[:5]
            ],
            "log_snippets": {
                pod: logs[-500:] if len(logs) > 500 else logs
                for pod, logs in context.get("logs", {}).items()
            },
            "memory_usage_mb": context.get("memory_usage_mb"),
            "error_rate_5m": context.get("error_rate_5m"),
        }

        root_cause = self.llm.diagnose_root_cause(summary)

        incident.root_cause = root_cause
        return {
            "root_cause": root_cause,
            "context_summary": summary,
        }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_detective.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/subagents/detective.py tests/test_detective.py
git commit -m "feat: add Detective subagent with LLM-powered RCA"
```

---

### Task 3.3: Surgeon SubAgent

**Files:**
- Create: `agents/subagents/surgeon.py`
- Create: `knowledge/playbooks/crashloop.yaml`
- Create: `knowledge/playbooks/oom.yaml`
- Create: `knowledge/playbooks/service_unavailable.yaml`
- Create: `tests/test_surgeon.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_surgeon.py
from unittest.mock import MagicMock
from core.incident import Incident, IncidentType
from agents.subagents.surgeon import SurgeonAgent

def test_surgeon_executes_rollback():
    incident = Incident(
        id="inc-001",
        type=IncidentType.CRASHLOOP,
        namespace="ecommerce",
        affected_resource="checkout",
        raw_signal={}
    )
    incident.root_cause = "ROOT CAUSE: Bad deployment. RECOMMENDED ACTION: kubectl rollout undo deployment/checkout"

    mock_tools = MagicMock()
    mock_tools.rollout_undo.return_value = "deployment.apps/checkout rolled back"
    mock_llm = MagicMock()
    mock_llm.select_remediation.return_value = {
        "playbook_name": "crashloop",
        "action": "rollback",
        "risk": "low",
        "reason": "Bad deployment detected"
    }

    surgeon = SurgeonAgent(kubectl_tools=mock_tools, llm=mock_llm)
    result = surgeon.run(incident)

    assert result["action_taken"] is not None
    assert result["success"] is True
    mock_tools.rollout_undo.assert_called_once_with("checkout")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_surgeon.py -v
```

Expected: FAIL

- [ ] **Step 3: Write seed playbooks**

```yaml
# knowledge/playbooks/crashloop.yaml
name: crashloop
description: Handles CrashLoopBackOff by rolling back the last deployment
triggers:
  - CrashLoopBackOff
  - repeated restarts
  - bad container args
actions:
  primary: rollback
  fallback: restart
risk: low
steps:
  - action: rollout_undo
    description: Roll back to previous deployment revision
  - action: verify_running
    description: Confirm pods reach Running state within 120s
```

```yaml
# knowledge/playbooks/oom.yaml
name: oom
description: Handles OOMKilled by patching memory limits upward
triggers:
  - OOMKilled
  - memory limit exceeded
  - out of memory
actions:
  primary: patch_memory
  fallback: scale_up
risk: low
steps:
  - action: patch_resource_limits
    description: Increase memory limit by 2x current setting
  - action: restart_deployment
    description: Rolling restart to apply new limits
  - action: verify_running
    description: Confirm pods stable for 120s
```

```yaml
# knowledge/playbooks/service_unavailable.yaml
name: service_unavailable
description: Handles service 503s by scaling up replicas
triggers:
  - ServiceUnavailable
  - 503
  - connection refused
  - replicas=0
actions:
  primary: scale_up
  fallback: rollback
risk: low
steps:
  - action: scale_deployment
    description: Scale to 3 replicas minimum
  - action: verify_running
    description: Confirm endpoint responding within 60s
```

- [ ] **Step 4: Implement SurgeonAgent**

```python
# agents/subagents/surgeon.py
import yaml
import os
from core.incident import Incident, IncidentType
from core.tool_registry import KubectlTools
from core.llm import OllamaClient


PLAYBOOKS_DIR = os.path.join(os.path.dirname(__file__), "../../knowledge/playbooks")


def load_playbooks() -> list[dict]:
    playbooks = []
    for fname in os.listdir(PLAYBOOKS_DIR):
        if fname.endswith(".yaml"):
            with open(os.path.join(PLAYBOOKS_DIR, fname)) as f:
                playbooks.append(yaml.safe_load(f))
    return playbooks


class SurgeonAgent:
    """
    Selects a playbook via LLM reasoning and executes the remediation action.
    Falls back to rollback if primary action fails.
    """

    def __init__(self, kubectl_tools: KubectlTools = None, llm: OllamaClient = None):
        self.kubectl = kubectl_tools or KubectlTools()
        self.llm = llm or OllamaClient()
        self.playbooks = load_playbooks()

    def run(self, incident: Incident) -> dict:
        root_cause = incident.root_cause or ""

        # LLM selects the best playbook
        selection = self.llm.select_remediation(root_cause, self.playbooks)
        action = selection.get("action", "rollback")
        resource = incident.affected_resource

        result_msg, success = self._execute_action(action, resource, incident)

        if not success and action != "rollback":
            result_msg, success = self._execute_action("rollback", resource, incident)

        incident.resolution = result_msg
        return {
            "action_taken": action,
            "playbook_used": selection.get("playbook_name"),
            "result": result_msg,
            "success": success,
            "risk": selection.get("risk", "unknown"),
        }

    def _execute_action(self, action: str, resource: str, incident: Incident) -> tuple[str, bool]:
        try:
            if action == "rollback":
                msg = self.kubectl.rollout_undo(resource)
                return msg, "rolled back" in msg.lower() or "undo" in msg.lower()
            elif action == "restart":
                msg = self.kubectl.restart_deployment(resource)
                return msg, True
            elif action == "scale_up":
                msg = self.kubectl.scale_deployment(resource, replicas=3)
                return msg, True
            elif action == "patch_memory":
                msg = self.kubectl.patch_resource_limits(resource, "256Mi", "200m")
                return msg, True
            else:
                msg = self.kubectl.restart_deployment(resource)
                return msg, True
        except Exception as e:
            return f"Action {action} failed: {e}", False
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_surgeon.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add agents/subagents/surgeon.py knowledge/playbooks/ tests/test_surgeon.py
git commit -m "feat: add Surgeon subagent with playbook-driven remediation"
```

---

### Task 3.4: Verifier SubAgent

**Files:**
- Create: `agents/subagents/verifier.py`
- Create: `tests/test_verifier.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_verifier.py
import time
from unittest.mock import MagicMock
from core.incident import Incident, IncidentType
from agents.subagents.verifier import VerifierAgent

def test_verifier_passes_when_healthy():
    incident = Incident(
        id="inc-001",
        type=IncidentType.CRASHLOOP,
        namespace="ecommerce",
        affected_resource="checkout",
        raw_signal={}
    )
    mock_tools = MagicMock()
    mock_tools.is_healthy.return_value = True

    verifier = VerifierAgent(kubectl_tools=mock_tools, wait_seconds=0, checks=1)
    result = verifier.run(incident)

    assert result["passed"] is True
    assert result["checks_passed"] == 1

def test_verifier_fails_when_unhealthy():
    incident = Incident(
        id="inc-002",
        type=IncidentType.CRASHLOOP,
        namespace="ecommerce",
        affected_resource="checkout",
        raw_signal={}
    )
    mock_tools = MagicMock()
    mock_tools.is_healthy.return_value = False

    verifier = VerifierAgent(kubectl_tools=mock_tools, wait_seconds=0, checks=2)
    result = verifier.run(incident)

    assert result["passed"] is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_verifier.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement VerifierAgent**

```python
# agents/subagents/verifier.py
import time
from core.incident import Incident, IncidentStatus
from core.tool_registry import KubectlTools


class VerifierAgent:
    """
    Polls deployment health after remediation.
    Returns PASS if all health checks succeed, FAIL otherwise.
    """

    def __init__(
        self,
        kubectl_tools: KubectlTools = None,
        wait_seconds: int = 15,
        checks: int = 4,
    ):
        self.kubectl = kubectl_tools or KubectlTools()
        self.wait_seconds = wait_seconds
        self.checks = checks

    def run(self, incident: Incident) -> dict:
        resource = incident.affected_resource
        passed_checks = 0

        for i in range(self.checks):
            if i > 0:
                time.sleep(self.wait_seconds)
            healthy = self.kubectl.is_healthy(resource)
            if healthy:
                passed_checks += 1

        passed = passed_checks == self.checks
        incident.status = IncidentStatus.RESOLVED if passed else IncidentStatus.FAILED

        return {
            "passed": passed,
            "checks_passed": passed_checks,
            "total_checks": self.checks,
            "resource": resource,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_verifier.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/subagents/verifier.py tests/test_verifier.py
git commit -m "feat: add Verifier subagent with polling health checks"
```

---

### Task 3.5: Learner SubAgent

**Files:**
- Create: `knowledge/db.py`
- Create: `agents/subagents/learner.py`
- Create: `tests/test_learner.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_learner.py
import os, tempfile
from core.incident import Incident, IncidentType, IncidentStatus
from knowledge.db import IncidentDB
from agents.subagents.learner import LearnerAgent

def test_learner_saves_incident():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        db = IncidentDB(db_path)
        incident = Incident(
            id="inc-001",
            type=IncidentType.CRASHLOOP,
            namespace="ecommerce",
            affected_resource="checkout",
            raw_signal={"reason": "CrashLoopBackOff"},
        )
        incident.root_cause = "Bad deployment env var"
        incident.resolution = "Rolled back deployment"
        incident.status = IncidentStatus.RESOLVED

        learner = LearnerAgent(db=db)
        learner.run(incident, verification_result={"passed": True, "checks_passed": 4})

        incidents = db.get_recent_incidents(limit=5)
        assert len(incidents) == 1
        assert incidents[0]["incident_id"] == "inc-001"
        assert incidents[0]["resolution"] == "Rolled back deployment"
    finally:
        os.unlink(db_path)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_learner.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement IncidentDB**

```python
# knowledge/db.py
import sqlite3
import json
from datetime import datetime
from typing import Optional


class IncidentDB:
    def __init__(self, db_path: str = "knowledge/incidents.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id TEXT NOT NULL,
                    incident_type TEXT,
                    namespace TEXT,
                    affected_resource TEXT,
                    root_cause TEXT,
                    resolution TEXT,
                    status TEXT,
                    verification_passed INTEGER,
                    created_at TEXT,
                    resolved_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS playbook_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    playbook_name TEXT,
                    incident_type TEXT,
                    success INTEGER,
                    created_at TEXT
                )
            """)
            conn.commit()

    def save_incident(self, incident_data: dict) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO incidents
                (incident_id, incident_type, namespace, affected_resource,
                 root_cause, resolution, status, verification_passed,
                 created_at, resolved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                incident_data["incident_id"],
                incident_data.get("incident_type"),
                incident_data.get("namespace"),
                incident_data.get("affected_resource"),
                incident_data.get("root_cause"),
                incident_data.get("resolution"),
                incident_data.get("status"),
                1 if incident_data.get("verification_passed") else 0,
                incident_data.get("created_at", datetime.utcnow().isoformat()),
                incident_data.get("resolved_at"),
            ))
            conn.commit()

    def save_playbook_feedback(self, playbook_name: str,
                                incident_type: str, success: bool) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO playbook_feedback (playbook_name, incident_type, success, created_at)
                VALUES (?, ?, ?, ?)
            """, (playbook_name, incident_type, 1 if success else 0,
                  datetime.utcnow().isoformat()))
            conn.commit()

    def get_recent_incidents(self, limit: int = 10) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM incidents ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    def get_playbook_success_rate(self, playbook_name: str) -> Optional[float]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("""
                SELECT
                    SUM(success) as wins,
                    COUNT(*) as total
                FROM playbook_feedback WHERE playbook_name = ?
            """, (playbook_name,)).fetchone()
            if row and row[1] > 0:
                return row[0] / row[1]
            return None
```

- [ ] **Step 4: Implement LearnerAgent**

```python
# agents/subagents/learner.py
from datetime import datetime
from core.incident import Incident, IncidentStatus
from knowledge.db import IncidentDB


class LearnerAgent:
    """
    Records the incident outcome to the DB and updates playbook success metrics.
    This is how the system learns: every healing attempt, successful or not, feeds back.
    """

    def __init__(self, db: IncidentDB = None):
        self.db = db or IncidentDB()

    def run(self, incident: Incident, verification_result: dict) -> dict:
        passed = verification_result.get("passed", False)

        self.db.save_incident({
            "incident_id": incident.id,
            "incident_type": incident.type.value,
            "namespace": incident.namespace,
            "affected_resource": incident.affected_resource,
            "root_cause": incident.root_cause,
            "resolution": incident.resolution,
            "status": incident.status.value,
            "verification_passed": passed,
            "created_at": incident.created_at.isoformat(),
            "resolved_at": datetime.utcnow().isoformat() if passed else None,
        })

        # Feed playbook success signal back
        if incident.resolution:
            # Extract playbook name heuristically from resolution
            playbook = "unknown"
            if "rolled back" in (incident.resolution or "").lower():
                playbook = "crashloop"
            elif "memory" in (incident.resolution or "").lower():
                playbook = "oom"
            elif "scale" in (incident.resolution or "").lower():
                playbook = "service_unavailable"

            self.db.save_playbook_feedback(playbook, incident.type.value, passed)

        return {
            "saved": True,
            "incident_id": incident.id,
            "outcome": "resolved" if passed else "failed",
        }
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_learner.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add knowledge/db.py agents/subagents/learner.py tests/test_learner.py
git commit -m "feat: add Learner subagent and IncidentDB with feedback loop"
```

---

## Phase 4: Supervisor Agent (The Brain)

### Task 4.1: Supervisor — LangGraph state machine

**Files:**
- Create: `agents/supervisor.py`
- Create: `tests/test_supervisor.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_supervisor.py
from unittest.mock import MagicMock, patch
from agents.supervisor import SupervisorAgent
from core.incident import IncidentType

def test_supervisor_full_cycle_resolved():
    mock_observer = MagicMock()
    mock_observer.run.return_value = {
        "pod_status": [{"name": "checkout-abc", "phase": "Running",
                        "restart_count": 8, "waiting_reason": "CrashLoopBackOff"}],
        "events": [{"reason": "BackOff", "message": "restarting", "object": "checkout-abc", "count": 8}],
        "logs": {"checkout-abc": "Error: INVALID_PORT"},
        "memory_usage_mb": None, "error_rate_5m": None,
    }
    mock_detective = MagicMock()
    mock_detective.run.return_value = {
        "root_cause": "ROOT CAUSE: Bad deployment. RECOMMENDED ACTION: rollback"
    }
    mock_surgeon = MagicMock()
    mock_surgeon.run.return_value = {
        "action_taken": "rollback", "playbook_used": "crashloop",
        "result": "deployment rolled back", "success": True, "risk": "low"
    }
    mock_verifier = MagicMock()
    mock_verifier.run.return_value = {
        "passed": True, "checks_passed": 4, "total_checks": 4
    }
    mock_learner = MagicMock()
    mock_learner.run.return_value = {"saved": True, "outcome": "resolved"}

    supervisor = SupervisorAgent(
        observer=mock_observer,
        detective=mock_detective,
        surgeon=mock_surgeon,
        verifier=mock_verifier,
        learner=mock_learner,
    )

    signal = {
        "reason": "CrashLoopBackOff",
        "namespace": "ecommerce",
        "resource": "checkout",
        "pod": "checkout-abc"
    }
    result = supervisor.handle_incident(signal)

    assert result["outcome"] == "resolved"
    assert result["mttr_seconds"] > 0
    mock_observer.run.assert_called_once()
    mock_detective.run.assert_called_once()
    mock_surgeon.run.assert_called_once()
    mock_verifier.run.assert_called_once()
    mock_learner.run.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_supervisor.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement SupervisorAgent**

```python
# agents/supervisor.py
import uuid
import time
from datetime import datetime
from typing import Optional

from core.incident import Incident, IncidentType, IncidentStatus
from core.todo_list import TodoList
from core.llm import OllamaClient
from agents.subagents.observer import ObserverAgent
from agents.subagents.detective import DetectiveAgent
from agents.subagents.surgeon import SurgeonAgent
from agents.subagents.verifier import VerifierAgent
from agents.subagents.learner import LearnerAgent
from ui.terminal import TerminalUI


SIGNAL_TO_TYPE = {
    "CrashLoopBackOff": IncidentType.CRASHLOOP,
    "OOMKilled": IncidentType.OOM,
    "ServiceUnavailable": IncidentType.SERVICE_UNAVAILABLE,
    "DeploymentFailed": IncidentType.DEPLOYMENT_FAILED,
}


class SupervisorAgent:
    """
    The brain of the self-healing system.
    Receives an incident signal, creates a TodoList, dispatches subagents
    in sequence, and drives the incident to resolution or escalation.
    Mirrors the OpenCode pattern: problem → plan → subagents → resolution.
    """

    def __init__(
        self,
        observer: ObserverAgent = None,
        detective: DetectiveAgent = None,
        surgeon: SurgeonAgent = None,
        verifier: VerifierAgent = None,
        learner: LearnerAgent = None,
        llm: OllamaClient = None,
        ui: TerminalUI = None,
    ):
        self.observer = observer or ObserverAgent()
        self.detective = detective or DetectiveAgent()
        self.surgeon = surgeon or SurgeonAgent()
        self.verifier = verifier or VerifierAgent()
        self.learner = learner or LearnerAgent()
        self.llm = llm or OllamaClient()
        self.ui = ui or TerminalUI()

    def handle_incident(self, signal: dict) -> dict:
        start_time = time.time()

        # 1. Create Incident object
        incident_type = SIGNAL_TO_TYPE.get(
            signal.get("reason", ""), IncidentType.UNKNOWN
        )
        incident = Incident(
            id=f"inc-{uuid.uuid4().hex[:8]}",
            type=incident_type,
            namespace=signal.get("namespace", "ecommerce"),
            affected_resource=signal.get("resource", "unknown"),
            raw_signal=signal,
        )

        self.ui.incident_detected(incident)

        # 2. Create TodoList (LLM-generated plan)
        todos = self.llm.create_todos(
            f"Incident: {incident.type.value} on {incident.affected_resource} "
            f"in namespace {incident.namespace}. Signal: {signal}"
        )
        todo_list = TodoList(incident_id=incident.id)
        for todo in todos:
            todo_list.add(todo)

        # Add fixed execution steps
        todo_list.add("Execute remediation action", assigned_to="surgeon")
        todo_list.add("Verify healing success", assigned_to="verifier")
        todo_list.add("Record outcome and update playbooks", assigned_to="learner")

        self.ui.todos_created(incident, todo_list)

        # 3. OBSERVER — collect all context
        incident.status = IncidentStatus.ANALYZING
        self.ui.agent_started("OBSERVER", "Collecting logs, metrics, events")
        todo_list.start(0)
        obs_result = self.observer.run(incident)
        todo_list.complete(0, result=f"Collected: {list(obs_result.keys())}")
        self.ui.agent_done("OBSERVER", obs_result)

        # 4. DETECTIVE — root cause analysis
        self.ui.agent_started("DETECTIVE", "Analysing root cause")
        if len(todo_list.items) > 1:
            todo_list.start(1)
        det_result = self.detective.run(incident)
        if len(todo_list.items) > 1:
            todo_list.complete(1, result=det_result["root_cause"][:100])
        self.ui.agent_done("DETECTIVE", det_result)

        # 5. SURGEON — execute remediation
        incident.status = IncidentStatus.HEALING
        self.ui.agent_started("SURGEON", "Executing remediation")
        sur_idx = len(todo_list.items) - 3
        todo_list.start(sur_idx)
        sur_result = self.surgeon.run(incident)
        todo_list.complete(sur_idx, result=sur_result["result"][:100])
        self.ui.agent_done("SURGEON", sur_result)

        # 6. VERIFIER — confirm healing
        incident.status = IncidentStatus.VERIFYING
        self.ui.agent_started("VERIFIER", "Verifying system health")
        ver_idx = len(todo_list.items) - 2
        todo_list.start(ver_idx)
        ver_result = self.verifier.run(incident)
        todo_list.complete(ver_idx, result=f"passed={ver_result['passed']}")
        self.ui.agent_done("VERIFIER", ver_result)

        # 7. LEARNER — record and learn
        learn_idx = len(todo_list.items) - 1
        todo_list.start(learn_idx)
        learn_result = self.learner.run(incident, ver_result)
        todo_list.complete(learn_idx, result="incident recorded")
        self.ui.agent_done("LEARNER", learn_result)

        mttr = time.time() - start_time
        outcome = "resolved" if ver_result["passed"] else "failed"

        self.ui.incident_closed(incident, outcome, mttr)

        return {
            "incident_id": incident.id,
            "outcome": outcome,
            "mttr_seconds": round(mttr, 1),
            "root_cause": incident.root_cause,
            "resolution": incident.resolution,
            "todos_summary": todo_list.summary(),
        }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_supervisor.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/supervisor.py tests/test_supervisor.py
git commit -m "feat: add Supervisor agent - the OpenCode-style brain of the system"
```

---

## Phase 5: Terminal UI

### Task 5.1: Rich-based live stream display

**Files:**
- Create: `ui/terminal.py`

- [ ] **Step 1: Implement TerminalUI**

```python
# ui/terminal.py
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from core.incident import Incident, IncidentStatus
from core.todo_list import TodoList


console = Console()


class TerminalUI:
    def incident_detected(self, incident: Incident) -> None:
        console.print(Panel(
            f"[bold red]INCIDENT DETECTED[/]\n"
            f"ID:        [yellow]{incident.id}[/]\n"
            f"Type:      [red]{incident.type.value}[/]\n"
            f"Resource:  [cyan]{incident.affected_resource}[/]\n"
            f"Namespace: [cyan]{incident.namespace}[/]\n"
            f"Signal:    {incident.raw_signal}",
            title="[bold red]Self-Healing System[/]",
            border_style="red",
        ))

    def todos_created(self, incident: Incident, todo_list: TodoList) -> None:
        table = Table(title=f"TodoList — {incident.id}", box=box.SIMPLE)
        table.add_column("#", style="dim")
        table.add_column("Task", style="white")
        table.add_column("Assigned To", style="cyan")
        for i, item in enumerate(todo_list.items):
            table.add_row(
                str(i + 1),
                item.description,
                item.assigned_to or "supervisor"
            )
        console.print(table)

    def agent_started(self, agent_name: str, task: str) -> None:
        console.print(
            f"\n[bold cyan]▶ {agent_name}[/] [dim]{task}...[/]"
        )

    def agent_done(self, agent_name: str, result: dict) -> None:
        console.print(
            f"[bold green]✓ {agent_name}[/] [dim]done[/]"
        )

    def incident_closed(self, incident: Incident, outcome: str, mttr: float) -> None:
        color = "green" if outcome == "resolved" else "red"
        emoji = "✓" if outcome == "resolved" else "✗"
        console.print(Panel(
            f"[bold {color}]{emoji} INCIDENT {outcome.upper()}[/]\n"
            f"ID:           {incident.id}\n"
            f"Root Cause:   {(incident.root_cause or '')[:120]}\n"
            f"Resolution:   {(incident.resolution or '')[:120]}\n"
            f"MTTR:         [bold yellow]{mttr:.1f}s[/]",
            title=f"[bold {color}]Incident Closed[/]",
            border_style=color,
        ))

    def janitor_report(self, issues_found: list[dict], fixes_applied: list[dict]) -> None:
        console.print(Panel(
            f"[bold yellow]JANITOR RUN COMPLETE[/]\n"
            f"Issues found: {len(issues_found)}\n"
            f"Fixes applied: {len(fixes_applied)}",
            title="[bold yellow]Janitor Report[/]",
            border_style="yellow",
        ))
        for fix in fixes_applied:
            console.print(f"  [green]✓[/] {fix['description']}")
```

- [ ] **Step 2: Commit**

```bash
git add ui/terminal.py
git commit -m "feat: add Rich-based terminal UI for live agent stream"
```

---

## Phase 6: Janitor Agent

### Task 6.1: Janitor — proactive scanner

**Files:**
- Create: `agents/janitor.py`
- Create: `tests/test_janitor.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_janitor.py
from unittest.mock import MagicMock, patch
from agents.janitor import JanitorAgent

def test_janitor_detects_memory_limit_issue():
    mock_tools = MagicMock()
    mock_tools.get_deployment_status.return_value = {
        "name": "payments", "replicas": 2,
        "ready_replicas": 2, "available_replicas": 2
    }

    mock_prometheus = MagicMock()
    # avg usage 110Mi, limit is 128Mi — 85% used, should flag
    mock_prometheus.get_pod_memory_usage.return_value = 110.0

    janitor = JanitorAgent(kubectl_tools=mock_tools, prometheus_tools=mock_prometheus)

    # Simulate scanning a deployment with 128Mi limit
    issue = janitor._check_memory_headroom("payments", memory_limit_mi=128)
    assert issue is not None
    assert "memory" in issue["type"].lower()
    assert issue["severity"] == "warning"

def test_janitor_produces_fix_summary():
    mock_tools = MagicMock()
    mock_tools.patch_resource_limits.return_value = "patched"
    mock_prometheus = MagicMock()
    mock_prometheus.get_pod_memory_usage.return_value = 110.0

    janitor = JanitorAgent(kubectl_tools=mock_tools, prometheus_tools=mock_prometheus)
    issues = [{"type": "memory_headroom", "resource": "payments",
               "severity": "warning", "detail": "usage 110Mi / limit 128Mi"}]
    fixes = janitor._apply_fixes(issues)

    assert len(fixes) == 1
    assert fixes[0]["applied"] is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_janitor.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement JanitorAgent**

```python
# agents/janitor.py
import subprocess
import yaml
import os
from datetime import datetime
from typing import Optional
from core.tool_registry import KubectlTools, PrometheusTools
from ui.terminal import TerminalUI, console


MEMORY_HEADROOM_THRESHOLD = 0.80   # flag if usage > 80% of limit
DEPLOYMENTS_TO_SCAN = ["checkout", "payments", "inventory", "frontend"]
MEMORY_LIMITS = {
    "checkout": 64, "payments": 128, "inventory": 64, "frontend": 64
}  # in Mi — matches manifests


class JanitorAgent:
    """
    Proactive background agent. Runs on a cron schedule.
    Scans the cluster for hygiene issues:
      1. Memory headroom (pods near OOMKill)
      2. CVEs in Python requirements (pip-audit)
      3. Deprecated Kubernetes API usage (kubent or manifest scan)
    Applies safe fixes autonomously and produces a human-readable diff summary.
    """

    def __init__(
        self,
        kubectl_tools: KubectlTools = None,
        prometheus_tools: PrometheusTools = None,
        namespace: str = "ecommerce",
        ui: TerminalUI = None,
    ):
        self.kubectl = kubectl_tools or KubectlTools(namespace=namespace)
        self.prometheus = prometheus_tools or PrometheusTools()
        self.namespace = namespace
        self.ui = ui or TerminalUI()

    def run(self) -> dict:
        console.print("\n[bold yellow]JANITOR[/] waking up — scanning cluster...\n")
        issues = []
        fixes = []

        # Scan 1: Memory headroom
        for deployment in DEPLOYMENTS_TO_SCAN:
            limit_mi = MEMORY_LIMITS.get(deployment, 64)
            issue = self._check_memory_headroom(deployment, limit_mi)
            if issue:
                issues.append(issue)

        # Scan 2: CVEs in requirements.txt
        cve_issues = self._check_cves()
        issues.extend(cve_issues)

        # Scan 3: Deprecated API usage
        deprecated_issues = self._check_deprecated_apis()
        issues.extend(deprecated_issues)

        console.print(f"[yellow]Janitor found {len(issues)} issue(s).[/]")
        for issue in issues:
            sev_color = "red" if issue["severity"] == "critical" else "yellow"
            console.print(
                f"  [{sev_color}]▲[/] [{issue['severity']}] "
                f"{issue['type']} — {issue['detail']}"
            )

        # Apply fixes
        fixes = self._apply_fixes(issues)

        # Produce summary
        summary = self._produce_summary(issues, fixes)
        self.ui.janitor_report(issues, fixes)

        return {"issues": issues, "fixes": fixes, "summary": summary}

    def _check_memory_headroom(self, deployment: str, memory_limit_mi: int) -> Optional[dict]:
        usage = self.prometheus.get_pod_memory_usage(self.namespace, deployment)
        if usage is None:
            return None
        usage_ratio = usage / memory_limit_mi
        if usage_ratio > MEMORY_HEADROOM_THRESHOLD:
            return {
                "type": "memory_headroom",
                "resource": deployment,
                "severity": "warning",
                "detail": f"usage {usage:.0f}Mi / limit {memory_limit_mi}Mi ({usage_ratio:.0%})",
                "fix": {"action": "patch_memory", "new_limit": f"{memory_limit_mi * 2}Mi"},
            }
        return None

    def _check_cves(self) -> list[dict]:
        issues = []
        try:
            result = subprocess.run(
                ["pip-audit", "--format", "json", "-r", "requirements.txt"],
                capture_output=True, text=True
            )
            if result.returncode != 0 and result.stdout:
                import json
                data = json.loads(result.stdout)
                for dep in data.get("dependencies", []):
                    for vuln in dep.get("vulns", []):
                        issues.append({
                            "type": "cve",
                            "resource": dep["name"],
                            "severity": "critical",
                            "detail": f"{dep['name']}=={dep['version']}: {vuln['id']} — {vuln['description'][:80]}",
                            "fix": {
                                "action": "bump_dependency",
                                "package": dep["name"],
                                "fix_version": vuln.get("fix_versions", ["latest"])[0],
                            },
                        })
        except FileNotFoundError:
            pass  # pip-audit not available in test env
        return issues

    def _check_deprecated_apis(self) -> list[dict]:
        issues = []
        manifests_dir = os.path.join(
            os.path.dirname(__file__), "../cluster/manifests"
        )
        if not os.path.exists(manifests_dir):
            return issues

        deprecated_apis = [
            "extensions/v1beta1",
            "networking.k8s.io/v1beta1",
            "batch/v1beta1",
        ]
        for fname in os.listdir(manifests_dir):
            if not fname.endswith(".yaml"):
                continue
            fpath = os.path.join(manifests_dir, fname)
            with open(fpath) as f:
                content = f.read()
            for api in deprecated_apis:
                if api in content:
                    issues.append({
                        "type": "deprecated_api",
                        "resource": fname,
                        "severity": "warning",
                        "detail": f"{fname} uses deprecated apiVersion {api}",
                        "fix": {
                            "action": "update_api_version",
                            "file": fpath,
                            "old_api": api,
                            "new_api": api.replace("v1beta1", "v1"),
                        },
                    })
        return issues

    def _apply_fixes(self, issues: list[dict]) -> list[dict]:
        fixes = []
        for issue in issues:
            fix = issue.get("fix", {})
            action = fix.get("action")
            applied = False
            description = ""

            if action == "patch_memory":
                try:
                    self.kubectl.patch_resource_limits(
                        issue["resource"],
                        fix["new_limit"],
                        "200m"
                    )
                    applied = True
                    description = (
                        f"Patched {issue['resource']} memory limit "
                        f"→ {fix['new_limit']}"
                    )
                except Exception as e:
                    description = f"Failed to patch memory: {e}"

            elif action == "update_api_version":
                try:
                    with open(fix["file"]) as f:
                        content = f.read()
                    updated = content.replace(fix["old_api"], fix["new_api"])
                    with open(fix["file"], "w") as f:
                        f.write(updated)
                    applied = True
                    description = (
                        f"Updated {fix['file']}: "
                        f"{fix['old_api']} → {fix['new_api']}"
                    )
                except Exception as e:
                    description = f"Failed to update API version: {e}"

            elif action == "bump_dependency":
                description = (
                    f"CVE in {fix['package']}: recommend upgrading to "
                    f"{fix['fix_version']} (manual bump required)"
                )
                applied = False  # Flag only; don't auto-modify deps in prod

            fixes.append({
                "action": action,
                "resource": issue["resource"],
                "applied": applied,
                "description": description,
            })
        return fixes

    def _produce_summary(self, issues: list[dict], fixes: list[dict]) -> str:
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        applied = [f for f in fixes if f["applied"]]
        flagged = [f for f in fixes if not f["applied"]]
        lines = [
            f"# Janitor Run — {ts}",
            f"Issues found: {len(issues)}",
            f"Fixes applied: {len(applied)}",
            f"Flagged for review: {len(flagged)}",
            "",
            "## Applied Fixes",
        ]
        for fix in applied:
            lines.append(f"- {fix['description']}")
        lines.append("\n## Flagged (manual action needed)")
        for fix in flagged:
            lines.append(f"- {fix['description']}")
        return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_janitor.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add agents/janitor.py tests/test_janitor.py
git commit -m "feat: add Janitor agent - proactive CVE, memory, deprecated API scanner"
```

---

## Phase 7: Event Watcher + Main Entry Point

### Task 7.1: Kubernetes event watcher

**Files:**
- Create: `core/event_watcher.py`

- [ ] **Step 1: Implement event watcher**

```python
# core/event_watcher.py
import time
import threading
from typing import Callable
from kubernetes import client, config, watch


WATCHED_REASONS = {
    "BackOff", "CrashLoopBackOff", "OOMKilling",
    "Failed", "Unhealthy", "FailedScheduling"
}

REASON_TO_SIGNAL = {
    "BackOff": "CrashLoopBackOff",
    "CrashLoopBackOff": "CrashLoopBackOff",
    "OOMKilling": "OOMKilled",
    "Failed": "DeploymentFailed",
    "Unhealthy": "ServiceUnavailable",
}


class KubernetesEventWatcher:
    """
    Watches the Kubernetes event stream and fires a callback
    when a significant failure event is detected.
    """

    def __init__(self, namespace: str = "ecommerce"):
        self.namespace = namespace
        self._stop = threading.Event()
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        self.v1 = client.CoreV1Api()

    def start(self, on_incident: Callable[[dict], None]) -> None:
        thread = threading.Thread(
            target=self._watch_loop, args=(on_incident,), daemon=True
        )
        thread.start()
        return thread

    def stop(self) -> None:
        self._stop.set()

    def _watch_loop(self, on_incident: Callable[[dict], None]) -> None:
        w = watch.Watch()
        seen_events: set[str] = set()

        while not self._stop.is_set():
            try:
                for event in w.stream(
                    self.v1.list_namespaced_event,
                    namespace=self.namespace,
                    timeout_seconds=30
                ):
                    obj = event["object"]
                    reason = obj.reason or ""
                    event_key = f"{obj.involved_object.name}:{reason}:{obj.count}"

                    if reason in WATCHED_REASONS and event_key not in seen_events:
                        seen_events.add(event_key)
                        signal = {
                            "reason": REASON_TO_SIGNAL.get(reason, reason),
                            "namespace": self.namespace,
                            "resource": obj.involved_object.name.rsplit("-", 2)[0],
                            "pod": obj.involved_object.name,
                            "message": obj.message,
                            "count": obj.count,
                        }
                        on_incident(signal)
            except Exception:
                if not self._stop.is_set():
                    time.sleep(5)
```

- [ ] **Step 2: Commit**

```bash
git add core/event_watcher.py
git commit -m "feat: add Kubernetes event watcher with failure signal routing"
```

---

### Task 7.2: Main entry point

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Write main.py**

```python
# main.py
"""
Self-Healing System — Entry Point
Usage:
  python main.py               # Start reactive supervisor + janitor
  python main.py --demo 1      # Inject Demo 1: CrashLoop
  python main.py --demo 2      # Inject Demo 2: Service cascade
  python main.py --demo 3      # Run Janitor scan (Demo 3)
  python main.py --janitor     # Run Janitor once and exit
"""
import sys
import time
import threading
import argparse
import schedule

from rich.console import Console

from agents.supervisor import SupervisorAgent
from agents.janitor import JanitorAgent
from core.event_watcher import KubernetesEventWatcher

console = Console()


def run_supervisor(signal: dict) -> None:
    supervisor = SupervisorAgent()
    try:
        result = supervisor.handle_incident(signal)
        console.print(f"\n[bold]Incident result:[/] {result}")
    except Exception as e:
        console.print(f"[red]Supervisor error: {e}[/]")


def run_janitor() -> None:
    janitor = JanitorAgent()
    result = janitor.run()
    print("\n" + result["summary"])


def start_reactive_mode() -> None:
    console.print("[bold green]Self-Healing System starting in REACTIVE mode...[/]")
    console.print("[dim]Watching namespace: ecommerce[/]")
    console.print("[dim]Press Ctrl+C to stop[/]\n")

    watcher = KubernetesEventWatcher(namespace="ecommerce")

    def on_incident(signal: dict) -> None:
        console.print(f"\n[bold red]Event received:[/] {signal}")
        t = threading.Thread(target=run_supervisor, args=(signal,), daemon=True)
        t.start()

    watcher.start(on_incident)

    # Schedule Janitor at 02:00 daily
    schedule.every().day.at("02:00").do(run_janitor)

    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/]")
        watcher.stop()


def demo_mode(demo_number: int) -> None:
    import subprocess

    demos = {
        1: "cluster/chaos/inject_crashloop.sh",
        2: "cluster/chaos/inject_cascade.sh",
        3: "cluster/chaos/inject_janitor_issues.sh",
    }
    script = demos.get(demo_number)
    if not script:
        console.print(f"[red]Unknown demo: {demo_number}[/]")
        return

    console.print(f"[bold yellow]Injecting Demo {demo_number}...[/]")
    subprocess.run(["bash", script])

    if demo_number == 3:
        console.print("\n[bold yellow]Running Janitor scan...[/]")
        run_janitor()
    else:
        console.print("\n[bold green]Starting supervisor to heal the injected failure...[/]")
        start_reactive_mode()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Self-Healing System")
    parser.add_argument("--demo", type=int, choices=[1, 2, 3],
                        help="Run a specific demo scenario")
    parser.add_argument("--janitor", action="store_true",
                        help="Run Janitor scan once and exit")
    args = parser.parse_args()

    if args.janitor:
        run_janitor()
    elif args.demo:
        demo_mode(args.demo)
    else:
        start_reactive_mode()
```

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: all tests PASS

- [ ] **Step 3: Smoke test Demo 1 end-to-end**

```bash
# Terminal 1: start system
python main.py

# Terminal 2: inject failure
bash cluster/chaos/inject_crashloop.sh
```

Expected: supervisor detects CrashLoopBackOff within 30s, creates todos, dispatches agents, heals, prints MTTR

- [ ] **Step 4: Smoke test Demo 3 (Janitor)**

```bash
python main.py --demo 3
```

Expected: Janitor wakes, scans, finds memory issue + deprecated API, applies fixes, prints summary

- [ ] **Step 5: Final commit**

```bash
git add main.py
git commit -m "feat: complete self-healing system with reactive + janitor modes"
```

---

## Summary: What This Builds

| Component | Purpose | Demo Moment |
|---|---|---|
| SupervisorAgent | Problem → plan → subagents → resolution | "Agent thinks like a senior SRE" |
| ObserverAgent | Collects all observable evidence | Live log/metrics stream |
| DetectiveAgent | LLM root cause analysis | "Root cause: bad deployment env var" |
| SurgeonAgent | Playbook-driven remediation | `kubectl rollout undo` live |
| VerifierAgent | Confirms system recovered | Green health checks |
| LearnerAgent | Records outcome, updates playbooks | Self-improving loop |
| JanitorAgent | Proactive scan while team sleeps | "You woke up to a clean diff" |
| KIND cluster | Local K8s — no cloud needed | Runs on any MacBook |
| Ollama llama3.1:8b | Local LLM — no API cost | Fully offline |

**Winning angle:** Not just reactive healing — two-mode intelligence (reactive + proactive), OpenCode-style plan-then-dispatch architecture, 100% local, MTTR measurable live on screen.
