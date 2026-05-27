# Self-Healing System — Architecture Specification

**Version:** 4.0 (Final — synced with implementation plan)
**Date:** 2026-05-27

---

## Problem Statement

Every time a routine production failure requires a human, that is:
- Engineering time stolen from creative work
- MTTR measured in hours instead of seconds
- Organisational dependency on human availability
- A solvable problem the system could handle itself

**The mission:** A bug or failure hits production. The system fixes it. No human involved.

---

## Core Design Principles

1. **Understand before acting** — Never attempt a fix without a written plan (TodoList)
2. **Safe by default** — Tests fail → rollback immediately, never leave production broken
3. **Deterministic deployment gate** — Deploy decision based on test change analysis, not LLM scoring
4. **Knowledge compounds** — Every fix makes the system smarter for that project via Neo4j KG
5. **Language agnostic core** — The LLM handles language; the engine handles reasoning
6. **Multi-tenant isolation** — Each project's knowledge is completely isolated in Neo4j
7. **Categorise before acting** — Code bugs and infra failures are different problems, solved differently

---

## Full System Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        PRODUCTION ENVIRONMENT                             │
│                                                                           │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────────────┐ │
│  │ Service A│   │ Service B│   │ Service C│   │  Kubernetes Cluster  │ │
│  │ (Python) │   │  (Node)  │   │  (Java)  │   │  pods / deployments  │ │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘   └──────────┬───────────┘ │
│       │              │              │                      │             │
│       └──────────────┴──────────────┘                      │             │
│                            │                               │             │
│                     application logs                   k8s events        │
└────────────────────────────┼───────────────────────────────┼─────────────┘
                             │                               │
                             └──────────────┬────────────────┘
                                            │
                                            ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                            LOG WATCHER                                    │
│                                                                           │
│  Tails log stream + Kubernetes event stream continuously                  │
│  Detects: ERROR, EXCEPTION, FATAL lines + pod failure events             │
│  Deduplicates: same error within 60s = one signal (no duplicate healing) │
│  Emits: structured Signal{source, service, error_type, stack_trace, ...} │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                           CATEGORISER                                     │
│                                                                           │
│  STAGE 1 — Fast signal analysis (< 1 second, no external calls)          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  Q1: Stack trace pointing to application code?  → code_signal    │   │
│  │  Q2: Pod / container in failed state?           → infra_signal   │   │
│  │  Q3: Error count < 3 in 5 minutes?              → transient_flag │   │
│  │                                                                    │   │
│  │  code=T, infra=F                → CODE PATH  (confidence: high)  │   │
│  │  code=F, infra=T                → INFRA PATH (confidence: high)  │   │
│  │  code=T, infra=T                → AMBIGUOUS  → Stage 2           │   │
│  │  ambiguous error type           → AMBIGUOUS  → Stage 2           │   │
│  │  transient_flag=T               → WATCH (TransientWatcher 5 min) │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                           │
│  STAGE 2 — Parallel investigation (ambiguous only, ~10 seconds)          │
│  ┌──────────────────────────┐  ┌────────────────────────────────────┐   │
│  │  CODE SIDE CHECK          │  │  INFRA SIDE CHECK                  │   │
│  │  KG query:                │  │  kubectl get pod status            │   │
│  │  - past incidents here?   │  │  check restart counts              │   │
│  │  - past fixes in KG?      │  │  check resource metrics            │   │
│  │  → code_suspicion_score   │  │  → infra_suspicion_score           │   │
│  └──────────────────────────┘  └────────────────────────────────────┘   │
│                   │                           │                           │
│                   └─────────────┬─────────────┘                          │
│                                 │                                         │
│  infra_score > code_score+0.2  → INFRA PATH                             │
│  code_score > infra_score+0.2  → CODE PATH                              │
│  scores roughly equal          → BOTH PATHS (run parallel, pick winner) │
│  both scores low               → TRANSIENT (watch + wait)               │
└─────────────────────────────────┬────────────────────────────────────────┘
                                  │
         ┌────────────────────────┼────────────────────────┐
         │                        │                         │
    CODE PATH               INFRA PATH               TRANSIENT
         │                        │                  monitor 5min
         │                        │                  re-evaluate
         └────────────┬───────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                         SUPERVISOR AGENT                                  │
│                                                                           │
│  SKILL: Understand the problem deeply before acting                       │
│  RULE:  Never dispatch subagents without a written TodoList               │
│                                                                           │
│  1. UNDERSTAND                                                            │
│     Code path:  query KG → call graph, past incidents, test coverage     │
│     Infra path: query cluster → pod status, events, metrics              │
│                                                                           │
│  2. PLAN (LLM creates TodoList)                                           │
│     Structured task list, each item assigned to a specific subagent      │
│                                                                           │
│  3. DISPATCH subagents in sequence                                        │
│                                                                           │
│  4. READ deployment decision from Tester (deterministic rule)            │
│                                                                           │
│  5. DELIVER via Committer (direct deploy or PR)                          │
│                                                                           │
│  6. LEARN — write outcome to KG                                          │
└───────────────────┬──────────────────────────────────────────────────────┘
                    │
       ┌────────────┴──────────────┐
       │                           │
  CODE SUBAGENTS             INFRA SUBAGENTS
       │                           │
  ┌────▼──────────┐          ┌─────▼──────────┐
  │  OBSERVER     │          │  OPERATOR       │
  │  stack trace  │          │  reads cluster  │
  │  → file+line  │          │  selects action │
  └────┬──────────┘          └─────┬──────────┘
       │                           │
  ┌────▼──────────┐          ┌─────▼──────────┐
  │  DETECTIVE    │          │  EXECUTOR       │
  │  queries KG:  │          │  kubectl/helm   │
  │  call graph   │          │  scale/restart  │
  │  past fixes   │          │  rollback       │
  │  test map     │          └─────┬──────────┘
  │  LLM RCA      │                │
  └────┬──────────┘          ┌─────▼──────────┐
       │                     │  INFRA VERIFIER │
  ┌────▼──────────┐          │  pod health     │
  │  CODER        │          │  service up?    │
  │  LLM writes   │          └─────────────────┘
  │  fix using KG │
  │  context +    │
  │  past patterns│
  │  + diff       │
  └────┬──────────┘
       │
  ┌────▼──────────────────────────────────────────────┐
  │  TESTER                                            │
  │                                                    │
  │  1. Analyse fix patch for test file changes        │
  │  2. Write fix to disk                              │
  │  3. Run full test suite                            │
  │  4. If fail → LLM revises → retry (max N times)   │
  │  5. Restore original file regardless of outcome   │
  │                                                    │
  │  DEPLOYMENT DECISION (deterministic rule):         │
  │                                                    │
  │  existing tests modified?         → open_pr        │
  │  no existing tests modified                        │
  │    + new test added + all pass    → direct_deploy  │
  │  no existing tests modified                        │
  │    + no new test + all pass       → open_pr        │
  │  any test failing                 → rollback       │
  └────┬──────────────────────────────────────────────┘
       │
       │  decision: "direct_deploy" | "open_pr" | "rollback"
       │
  ┌────▼──────────┐
  │  ROLLBACK     │◄── if decision = rollback
  │  git revert   │    git revert + redeploy previous
  │  escalate     │    escalate with full diagnostic
  └───────────────┘
       │
  ┌────▼──────────┐
  │  COMMITTER    │◄── if decision = direct_deploy or open_pr
  │  create branch│
  │  commit fix   │    direct_deploy → push to main → CI/CD
  │  open PR      │    open_pr       → PR for human review
  │  OR direct    │
  │  push         │
  └────┬──────────┘
       │
  ┌────▼──────────┐
  │  LEARNER      │
  │  writes to KG │
  │  Incident node│
  │  Fix node     │
  │  confidence:  │
  │  direct=1.0   │
  │  pr=0.7       │
  │  System learns│
  └───────────────┘
```

---

## Deployment Decision Rule (replaces ConfidenceScorer)

The Tester makes the deployment decision deterministically by analysing what files changed in the fix patch. No LLM scoring. No weighted formulas.

```
┌──────────────────────────────────────────────────────────────────────┐
│                    TESTER DEPLOYMENT DECISION                         │
│                                                                       │
│  INPUT: unified diff patch from the Coder                            │
│                                                                       │
│  STEP 1: Parse patch → identify which files were changed             │
│  STEP 2: Classify each changed file:                                 │
│    - Is it a test file? (contains test_, /tests/, _spec, etc.)      │
│    - Was it a pre-existing file or a new file?                       │
│    - Does it add new def test_* functions?                           │
│                                                                       │
│  STEP 3: Apply rule:                                                 │
│                                                                       │
│  existing test file modified?                                        │
│  └─ YES → open_pr                                                    │
│     (fix changed existing tests = functionality may have changed     │
│      human must verify what was altered)                             │
│                                                                       │
│  existing test file modified = NO                                    │
│  + new test function added = YES                                     │
│  + all tests pass = YES                                              │
│  └─ → direct_deploy                                                  │
│     (fix is additive + tested + provably non-breaking)               │
│                                                                       │
│  existing test file modified = NO                                    │
│  + new test added = NO                                               │
│  + all tests pass = YES                                              │
│  └─ → open_pr                                                        │
│     (tests pass but no coverage for the fix — scope unclear)         │
│                                                                       │
│  any test failing (after all LLM retries)                            │
│  └─ → rollback                                                       │
│     (never leave production in a broken state)                       │
└──────────────────────────────────────────────────────────────────────┘

WHY THIS IS BETTER THAN LLM SCORING:
  - Deterministic: same input always produces same decision
  - Auditable: a human can inspect the diff and verify the decision
  - Honest: doesn't pretend to measure "confidence" in LLM output
  - Incentivises correctness: agent is motivated to write tests
```

---

## Multi-Tenant Knowledge Architecture

```
NEO4J 5.x (one database, isolated by project_id property)
│
├── Tenant: project-x  (e.g. Ecommerce Platform — Python/FastAPI)
│   │
│   ├── STRUCTURE NODES (updated on every deployment via parser)
│   │   (:File     {project_id, path, language})
│   │   (:Function {project_id, name, file, line_start, line_end,
│   │               body, embedding: float[384]})
│   │   (:Class    {project_id, name, file})
│   │   (:Test     {project_id, name, file})
│   │
│   ├── HISTORY NODES (written by Learner after each incident)
│   │   (:Incident {project_id, id, error_type, resolved: bool})
│   │   (:Fix      {project_id, incident_id, patch, confidence: float})
│   │
│   └── RELATIONSHIPS
│         (:File)-[:CONTAINS]->(:Function)       — structure
│         (:Function)-[:CALLS]->(:Function)       — call graph
│         (:Function)-[:IMPORTS]->(:Module)       — dependencies
│         (:Class)-[:INHERITS]->(:Class)          — inheritance
│         (:Test)-[:TESTS]->(:Function)           — coverage map
│         (:Incident)-[:OCCURRED_IN]->(:Function) — incident history
│         (:Incident)-[:FIXED_BY]->(:Fix)         — fix history
│         (:Fix)-[:APPLIED_TO]->(:Function)       — what was fixed
│
├── Tenant: project-y  (e.g. Billing Service — Node.js/Express)
│   └── (completely isolated — no cross-tenant queries ever)
│
└── Tenant: project-z  (e.g. Analytics — Java/Spring)
    └── (completely isolated)

VECTOR INDEX (per tenant):
  Each Function node has an embedding[] property (384 dimensions, all-MiniLM-L6-v2)
  Neo4j 5.x native vector index enables semantic search:
    "Find functions semantically similar to this failing stack trace"
    "Find past incidents that look like this new error"
```

---

## On Every New Deployment

```
CI/CD pipeline completes
         │
         ▼  (post-deploy hook or manual trigger)
python parser/deployment_hook.py --project-dir ./src --config self-healing.yaml
         │
         ▼
For each source file:
  1. Detect language from file extension
  2. Parse AST → extract functions, classes, imports, call sites
  3. Upsert Function nodes in Neo4j (MERGE on name+file+project_id)
  4. Generate embedding for each function body (sentence-transformers)
  5. Store embedding on Function node
  6. Build CALLS relationships from call sites
  7. Diff against previous parse → only update changed nodes

Result: KG is always current with the deployed codebase
        Detective queries reflect exactly what is running in production
```

---

## self-healing.yaml — Project Configuration

```yaml
# self-healing.yaml
# Lives in the root of the project being healed.
# Contains ONLY what the agent cannot discover itself.

project:
  id: "project-x"                      # unique tenant ID in Neo4j
  name: "Ecommerce Platform"
  repo: "your-username/self-healing-demo"  # GitHub repo for PR creation

stack:
  test_command: "pytest demo_app/tests/ -v"  # how to run this project's tests
  entry_points:                              # which services emit logs to watch
    - service: "payments"
      log_pattern: "demo_app/payments.py"
    - service: "inventory"
      log_pattern: "demo_app/inventory.py"
    - service: "checkout"
      log_pattern: "demo_app/checkout.py"

healing:
  max_fix_attempts: 3          # LLM retry limit before giving up
  rollback_on_test_failure: true
  notify_slack_channel: "#alerts"  # optional

# NOTE: No confidence thresholds.
# Deployment decision is made deterministically by the Tester
# using test change analysis — not numeric scoring.
```

---

## Technology Stack

| Component | Technology | Reason |
|---|---|---|
| Language | Python 3.11+ | Best LLM tooling, clean AST support |
| LLM | Ollama llama3.1:8b | Local, no API cost, fully offline |
| Knowledge Graph | Neo4j 5.x | Native graph traversal + vector index built-in |
| Code Embeddings | sentence-transformers (all-MiniLM-L6-v2) | 384-dim, fast, runs locally |
| Demo App | FastAPI (Python) | Simple, produces real stack traces |
| Infra Runtime | KIND (local Kubernetes) | Real kubectl, no cloud cost |
| GitHub Integration | PyGithub | Branch, commit, PR creation |
| Test Runner | subprocess (language-agnostic) | Works for pytest / jest / mvn |
| Terminal UI | Rich | Live agent stream with diff display |
| Config | PyYAML | self-healing.yaml parsing |
| Persistence | Neo4j (KG + embeddings) | Single store, no extra DB needed |

---

## The Four Demo Scenarios

### Demo 1: Code Bug — TypeError (direct_deploy)
```
Signal:    TypeError: 'NoneType' object is not subscriptable
           File "demo_app/payments.py", line 18, in process_payment

Categorise: CODE PATH — stack trace present, no pod failure

Supervisor: query KG → no past incidents on process_payment
            LLM creates TodoList (5 tasks)

Observer:   extracts file = demo_app/payments.py

Detective:  reads payments.py source
            KG: callers=[checkout_handler], tests=[test_process_payment]
            LLM: "ROOT_CAUSE: get_inventory() returns None for unknown order"

Coder:      LLM writes null check + adds test_process_payment_unknown_order
            generates unified diff (4 lines changed)

Tester:     patch analysis:
              existing_tests_modified = False
              new_tests_added = True (test_process_payment_unknown_order)
            runs pytest → 3 passed
            DECISION: direct_deploy

Committer:  creates branch fix/inc-xxxxx-type-error
            commits fix to branch
            opens PR + merges to main directly

Learner:    writes Incident + Fix nodes to KG
            stored_confidence = 1.0 (direct_deploy)

MTTR: ~90 seconds | Human involvement: 0
```

### Demo 2: Code Bug — ZeroDivisionError (open_pr)
```
Signal:    ZeroDivisionError: division by zero
           File "demo_app/inventory.py", line 22, in get_unit_price

Categorise: CODE PATH

Tester:     fix adds guard clause, no new test written
            DECISION: open_pr (fix untested — scope unclear)

Committer:  opens PR for human review

MTTR: ~85 seconds | Human reviews + merges PR
```

### Demo 3: Infra Bug — CrashLoopBackOff
```
Signal:    CrashLoopBackOff on payments pod (Kubernetes event)

Categorise: INFRA PATH — no stack trace, pod in failed state

Operator:   playbook match: CrashLoopBackOff → rollback
Executor:   kubectl rollout undo deployment/payments
Verifier:   polls pod health × 4 checks → all passing

Learner:    writes incident to KG

MTTR: ~45 seconds | Human involvement: 0
```

### Demo 4: Ambiguous — ConnectionError
```
Signal:    ConnectionError: database unreachable
           File "demo_app/payments.py", line 45 (stack trace present)
           + db pod restarting (infra signal also present)

Categorise: AMBIGUOUS → Stage 2

Stage 2:   Code side: KG has no recent incidents on this function → score 0.3
           Infra side: db pod CrashLoopBackOff restart_count=12 → score 0.9

Route:     INFRA PATH (infra_score >> code_score)

Executor:  kubectl rollout undo deployment/db
Verifier:  service healthy

MTTR: ~60 seconds | Human involvement: 0
```

---

## What Happens When Everything Goes Wrong

```
FAILURE SCENARIO: LLM writes a bad fix, tests fail after 3 retries

Tester:     all retries exhausted
            DECISION: rollback

Rollback:   git revert HEAD on fix branch
            escalation_context = {
              incident_id, service, error,
              stack_trace, root_cause_analysis,
              attempted_fix_patch, test_output,
              deploy_decision: "rollback"
            }

Learner:    writes Incident node to KG (resolved=false)
            does NOT write Fix node
            (failed fixes are not stored as patterns)

Result:     production is in known-good state
            human receives full diagnostic context
            system has learned: this error pattern needs human intervention
```

---

## How The System Gets Smarter Over Time

```
Day 1:    No fix history in KG
          Detective has no past patterns to reference
          Coder writes generic fix
          Decision: open_pr (cautious — no test added)

Day 7:    7 incidents fixed, all stored in KG
          Detective sees: "process_payment had 3 past TypeErrors,
                          all fixed with null checks, confidence=1.0"
          Coder has past fix patterns as context
          Coder writes correct fix + test on first attempt
          Decision: direct_deploy

Day 30:   KG is rich with project-specific patterns
          Fix quality matches team's code style exactly
          More incidents resolved as direct_deploy
          Human only reviews PRs for genuinely novel failures

This is the "living organism" Matt described.
The system doesn't just fix bugs — it learns HOW to fix bugs
in your specific codebase, getting better with every incident.
```

---

## Project File Structure (Reference)

```
self-healing/
├── self-healing.yaml              ← tenant config
├── main.py                        ← entry point
├── requirements.txt
│
├── config/
│   └── tenant_registry.py         ← loads self-healing.yaml
│
├── knowledge/
│   ├── neo4j_client.py            ← Neo4j connection + queries
│   ├── graph_schema.py            ← node/relationship constants
│   ├── kg_builder.py              ← builds KG from parsed codebase
│   └── kg_querier.py              ← all read queries
│
├── parser/
│   ├── code_parser.py             ← AST parser (language-agnostic)
│   ├── embedder.py                ← generates function embeddings
│   └── deployment_hook.py         ← triggered on each deployment
│
├── core/
│   ├── signal.py                  ← Signal dataclass
│   ├── incident.py                ← Incident dataclass
│   ├── todo_list.py               ← TodoList + TodoItem
│   ├── llm.py                     ← Ollama client
│   └── github_tools.py            ← GitHub branch/commit/PR
│
├── categoriser/
│   ├── stage1.py                  ← fast signal classifier
│   ├── stage2.py                  ← parallel ambiguous investigation
│   ├── transient_watcher.py       ← watch-and-wait for transients
│   └── router.py                  ← combines stages, emits Incident
│
├── agents/
│   ├── supervisor.py              ← brain: understand→plan→dispatch
│   ├── code/
│   │   ├── observer.py            ← extracts file+line from trace
│   │   ├── detective.py           ← KG query + LLM root cause
│   │   ├── coder.py               ← writes fix (LLM + KG context)
│   │   ├── tester.py              ← runs tests + deployment decision
│   │   └── committer.py           ← branch + commit + PR/deploy
│   ├── infra/
│   │   ├── operator.py            ← playbook selection
│   │   ├── executor.py            ← kubectl/helm actions
│   │   └── verifier.py            ← health checks
│   └── shared/
│       ├── learner.py             ← writes outcomes to KG
│       └── rollback.py            ← git revert + escalation
│
├── watcher/
│   └── log_watcher.py             ← tails logs, emits signals
│
├── ui/
│   └── terminal.py                ← Rich live display
│
└── demo_app/                      ← fake production app with planted bugs
    ├── payments.py                ← Bug 1: missing null check
    ├── inventory.py               ← Bug 2: divide by zero
    ├── checkout.py                ← Bug 3: empty cart crash
    └── tests/
        ├── test_payments.py       ← FAILS before fix, PASSES after
        ├── test_inventory.py      ← FAILS before fix, PASSES after
        └── test_checkout.py       ← FAILS before fix, PASSES after
```
