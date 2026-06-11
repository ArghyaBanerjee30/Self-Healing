"""
Self-Healing System — main entry point.

Pipeline:
    log file → LogWatcher → Signal → Categoriser → CategoryResult → Supervisor → TodoList

Usage:
    python main.py                                  # watches log from self-healing.yaml
    python main.py --log demo_app/app.log           # override log file
    python main.py --config path/to/self-healing.yaml
    python main.py --inject                         # write fake errors to log for testing
"""
import asyncio
import argparse
import logging
import os
import sys
import threading
import time

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("self-healing")

from config.tenant_registry import TenantConfig
from core.signal import Signal
from core.incident import IncidentPath
from categoriser.router import route
from categoriser.domain import CategoryResult
from watcher.log_watcher import LogWatcher
from agents.supervisor import Supervisor


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

async def run_pipeline(log_file: str, config: TenantConfig, skip_transient: bool = False) -> None:
    supervisor = Supervisor(verbose=True)
    signal_queue: asyncio.Queue[Signal] = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def on_signal(signal: Signal) -> None:
        log.info(
            "[LogWatcher] signal: service=%s error_type=%s",
            signal.service, signal.error_type,
        )
        loop.call_soon_threadsafe(signal_queue.put_nowait, signal)

    watcher = LogWatcher(config, on_signal)
    watcher_thread = threading.Thread(
        target=watcher.watch, args=(log_file,), daemon=True, name="log-watcher"
    )
    watcher_thread.start()

    print(f"\n{'━'*60}")
    print(f"  Self-Healing System")
    print(f"  Project  : {config.project_id}")
    print(f"  Watching : {log_file}")
    print(f"{'━'*60}\n")
    print("  Waiting for errors...\n")

    while True:
        signal = await signal_queue.get()

        print(f"\n{'━'*60}")
        print(f"  NEW SIGNAL")
        print(f"  Service   : {signal.service}")
        print(f"  Error     : {signal.error_type}: {signal.raw_message[:80]}")
        if signal.stack_trace:
            first_file = next(
                (l.strip() for l in signal.stack_trace.splitlines() if 'File "' in l),
                None,
            )
            if first_file:
                print(f"  Location  : {first_file}")
        print(f"{'━'*60}")

        # Categorise
        print("\n[CATEGORISER] Running...")
        try:
            result: CategoryResult = await route(signal, _skip_transient_gate=skip_transient)
        except Exception as e:
            log.error("[CATEGORISER] Failed: %s", e)
            continue

        path = result.incident.path
        conf = result.incident.confidence
        print(f"[CATEGORISER] → {path.value.upper()} ({conf.value} confidence)")

        if result.stage2:
            print(
                f"[CATEGORISER] Stage2 scores: "
                f"code={result.stage2.code_suspicion_score:.2f}  "
                f"infra={result.stage2.infra_suspicion_score:.2f}"
            )

        # Skip resolved transients
        if path == IncidentPath.TRANSIENT and result.incident.resolved:
            print("[CATEGORISER] Transient resolved — no healing action needed.\n")
            continue

        # Hand to Supervisor
        supervisor.run(result)


# ---------------------------------------------------------------------------
# Log injector — writes fake errors to a log file for pipeline testing
# ---------------------------------------------------------------------------

_TYPEERROR_LOG = (
    "ERROR payments - TypeError: 'NoneType' object is not subscriptable\n"
    "Traceback (most recent call last):\n"
    '  File "demo_app/payments.py", line 18, in process_payment\n'
    '    total = inventory["price"] * inventory["quantity"]\n'
    "TypeError: 'NoneType' object is not subscriptable\n"
)

_ZERODIV_LOG = (
    "ERROR inventory - ZeroDivisionError: division by zero\n"
    "Traceback (most recent call last):\n"
    '  File "demo_app/inventory.py", line 22, in get_unit_price\n'
    "    price = total_value / item_count\n"
    "ZeroDivisionError: division by zero\n"
)

# Each scenario is repeated 3x to pass the transient gate (threshold=3 occurrences)
_SCENARIOS = [
    ("TypeError in payments",     _TYPEERROR_LOG, 3),
    ("ZeroDivisionError in inventory", _ZERODIV_LOG, 3),
]


def inject_logs(log_file: str, delay: float = 2.0) -> None:
    os.makedirs(os.path.dirname(log_file) if os.path.dirname(log_file) else ".", exist_ok=True)
    # Wait briefly for the watcher thread to start and seek to end-of-file
    time.sleep(1.5)
    with open(log_file, "a") as f:
        for label, entry, repeat in _SCENARIOS:
            print(f"\n[INJECT] Scenario: {label} (repeating {repeat}x to pass transient gate)")
            for i in range(repeat):
                f.write(entry)
                f.flush()
                print(f"[INJECT]   → wrote occurrence {i+1}/{repeat}")
                time.sleep(delay)
            # pause between scenarios so the supervisor finishes before next one
            time.sleep(5.0)
    print("\n[INJECT] All scenarios injected.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Self-Healing System")
    parser.add_argument(
        "--log", default=None,
        help="Log file to watch (overrides self-healing.yaml production_log)",
    )
    parser.add_argument(
        "--config", default="repo_data/demo-commerce-api/self-healing.yaml",
        help="Path to self-healing.yaml",
    )
    parser.add_argument(
        "--inject", action="store_true",
        help="Inject fake error logs into the log file for testing",
    )
    parser.add_argument(
        "--inject-delay", type=float, default=1.0,
        help="Seconds between injected log entries (default: 1)",
    )
    parser.add_argument(
        "--skip-transient", action="store_true",
        help="Skip the transient gate — route every signal straight to the Supervisor",
    )
    args = parser.parse_args()

    config = TenantConfig.from_yaml(args.config)
    log_file = args.log or config.production_log or "demo_app/app.log"

    # Ensure the log file exists so the watcher can open it
    os.makedirs(os.path.dirname(log_file) if os.path.dirname(log_file) else ".", exist_ok=True)
    if not os.path.exists(log_file):
        open(log_file, "w").close()

    if args.inject:
        # Inject in background so the pipeline can process as they arrive
        inject_thread = threading.Thread(
            target=inject_logs,
            args=(log_file, args.inject_delay),
            daemon=True,
        )
        inject_thread.start()

    try:
        asyncio.run(run_pipeline(log_file, config, skip_transient=args.skip_transient))
    except KeyboardInterrupt:
        print("\n[STOPPED] Self-healing pipeline stopped.")


if __name__ == "__main__":
    main()
