# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current Task

Build the demo FastAPI app (`demo_app/`) and the LogWatcher (`watcher/log_watcher.py`) that monitors it. Neither exists yet.

## Environment Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Commands

```bash
# Run tests
pytest tests/ -v
pytest tests/test_log_watcher.py -v

# Run the demo app
uvicorn demo_app.app:app --host 0.0.0.0 --port 8000 --log-level debug

# Trigger bugs manually
curl -X POST http://localhost:8000/payments -d '{"order_id": null}'   # TypeError
curl -X POST http://localhost:8000/inventory -d '{"quantity": 0}'     # ZeroDivisionError
curl -X POST http://localhost:8000/checkout  -d '{"cart": []}'        # empty cart crash

# Run the LogWatcher standalone (prints signals to stdout)
python watcher/log_watcher.py --log-file demo_app/app.log --config self-healing.yaml
```

## Demo App

**File:** `demo_app/` — does not exist yet, must be created.

### Structure

```
demo_app/
├── app.py              ← FastAPI app, mounts all routers, configures file logging
├── payments.py         ← POST /payments  — Bug: get_inventory() can return None → TypeError
├── inventory.py        ← POST /inventory — Bug: quantity can be 0 → ZeroDivisionError
├── checkout.py         ← POST /checkout  — Bug: empty cart → IndexError or similar
└── tests/
    ├── test_payments.py
    ├── test_inventory.py
    └── test_checkout.py
```

### Logging requirements

The app **must** write logs to both stdout and `demo_app/app.log`. Configure in `app.py`:

```python
import logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("demo_app/app.log"),
    ]
)
```

Every route handler must catch exceptions, log at `ERROR` level with `exc_info=True`, then re-raise. Do not swallow exceptions silently — the stack trace in the log is what the LogWatcher parses.

## LogWatcher

**File:** `watcher/log_watcher.py` — does not exist yet, must be created.

### Behaviour

- Tails `demo_app/app.log` continuously using a polling loop
- Detects lines containing `ERROR`, `EXCEPTION`, `FATAL`, or `Traceback (most recent call last)`
- Accumulates multi-line tracebacks: starts at `Traceback (most recent call last):`, ends at the exception line (e.g. `TypeError: ...`)
- **Deduplicates**: same `(service, error_type, error_message)` within 60 seconds emits only one `Signal`
- Maps the log file path to a service name via `self-healing.yaml` `stack.entry_points[].log_pattern`
- Emits a `Signal` (from `core/signal.py`) with `source=SignalSource.LOG`

### Interface

```python
class LogWatcher:
    def __init__(self, config: TenantConfig, signal_callback: Callable[[Signal], None]):
        ...

    def watch(self, log_file: str) -> None:
        """Blocking. Tails log_file and calls signal_callback for each new Signal."""
        ...
```

`signal_callback` is what the Categoriser registers to receive signals.

### Tests

`tests/test_log_watcher.py` — use a `tempfile` log file, write fake log lines, assert correct `Signal` objects are emitted. Must cover: single-line errors, multi-line traceback accumulation, and deduplication (two identical errors within 60s → one signal).
