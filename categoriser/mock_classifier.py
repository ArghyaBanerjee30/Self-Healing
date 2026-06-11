"""
Mock log classifier — simulates a classified log result for demo/dev purposes.

In production this would be replaced by the real Stage1 + Stage2 categoriser.
Each scenario here maps to a pre-classified ClassifiedLog that the Supervisor
consumes directly, skipping the log parsing pipeline.
"""
from dataclasses import dataclass
from enum import Enum
from core.signal import Signal, SignalSource
from core.incident import IncidentCategory


class Confidence(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ClassifiedLog:
    incident_id: str
    signal: Signal
    category: IncidentCategory
    confidence: Confidence
    classification_reason: str


# ---------------------------------------------------------------------------
# Pre-classified demo scenarios
# ---------------------------------------------------------------------------

DEMO_SCENARIOS: dict[str, ClassifiedLog] = {

    # Scenario 1: Classic code bug — TypeError (direct_deploy path)
    "demo-001": ClassifiedLog(
        incident_id="demo-001",
        signal=Signal(
            source=SignalSource.LOG,
            service="payments",
            error_type="TypeError",
            error_message="'NoneType' object is not subscriptable",
            stack_trace=(
                'Traceback (most recent call last):\n'
                '  File "demo_app/payments.py", line 18, in process_payment\n'
                '    total = inventory["price"] * inventory["quantity"]\n'
                "TypeError: 'NoneType' object is not subscriptable"
            ),
            raw_text=(
                "2026-06-11T10:23:41Z ERROR payments - "
                "TypeError: 'NoneType' object is not subscriptable "
                "in process_payment (payments.py:18)"
            ),
            occurrence_count=5,
        ),
        category=IncidentCategory.CODE,
        confidence=Confidence.HIGH,
        classification_reason=(
            "Stack trace points to application code (payments.py:18). "
            "TypeError is a code-side error type. No pod failure events."
        ),
    ),

    # Scenario 2: Code bug — ZeroDivisionError (open_pr path)
    "demo-002": ClassifiedLog(
        incident_id="demo-002",
        signal=Signal(
            source=SignalSource.LOG,
            service="inventory",
            error_type="ZeroDivisionError",
            error_message="division by zero",
            stack_trace=(
                'Traceback (most recent call last):\n'
                '  File "demo_app/inventory.py", line 22, in get_unit_price\n'
                '    price = total_value / item_count\n'
                "ZeroDivisionError: division by zero"
            ),
            raw_text=(
                "2026-06-11T10:31:07Z ERROR inventory - "
                "ZeroDivisionError: division by zero "
                "in get_unit_price (inventory.py:22)"
            ),
            occurrence_count=8,
        ),
        category=IncidentCategory.CODE,
        confidence=Confidence.HIGH,
        classification_reason=(
            "Stack trace in application code (inventory.py:22). "
            "ZeroDivisionError is deterministic and code-side."
        ),
    ),

    # Scenario 3: Infra failure — CrashLoopBackOff
    "demo-003": ClassifiedLog(
        incident_id="demo-003",
        signal=Signal(
            source=SignalSource.KUBERNETES,
            service="payments",
            error_type="CrashLoopBackOff",
            error_message="Back-off restarting failed container",
            stack_trace="",
            raw_text=(
                "2026-06-11T10:45:22Z WARN kubernetes - "
                "pod payments-7d9f8b6c4-xk2pq is in CrashLoopBackOff "
                "(restart_count=12, namespace=default)"
            ),
            occurrence_count=12,
            pod_name="payments-7d9f8b6c4-xk2pq",
            namespace="default",
        ),
        category=IncidentCategory.INFRA,
        confidence=Confidence.HIGH,
        classification_reason=(
            "Kubernetes event. No application stack trace. "
            "CrashLoopBackOff is a pure infra failure type. "
            "restart_count=12 indicates a bad deployment."
        ),
    ),

    # Scenario 4: Ambiguous — ConnectionError (both code stack trace + db pod failing)
    "demo-004": ClassifiedLog(
        incident_id="demo-004",
        signal=Signal(
            source=SignalSource.LOG,
            service="payments",
            error_type="ConnectionError",
            error_message="database unreachable at db:5432",
            stack_trace=(
                'Traceback (most recent call last):\n'
                '  File "demo_app/payments.py", line 45, in _get_db_connection\n'
                '    conn = psycopg2.connect(DATABASE_URL)\n'
                "ConnectionError: database unreachable at db:5432"
            ),
            raw_text=(
                "2026-06-11T11:02:55Z ERROR payments - "
                "ConnectionError: database unreachable at db:5432 "
                "in _get_db_connection (payments.py:45)\n"
                "CONCURRENT: pod db-5c8d9f7b6-m3nqr CrashLoopBackOff restart_count=9"
            ),
            occurrence_count=6,
        ),
        category=IncidentCategory.BOTH,
        confidence=Confidence.MEDIUM,
        classification_reason=(
            "Stack trace in app code (payments.py:45) AND db pod is CrashLoopBackOff. "
            "ConnectionError is ambiguous — could be code (wrong connection string) "
            "or infra (db pod down). Stage 2 investigation required."
        ),
    ),
}


def get_classified_log(incident_id: str) -> ClassifiedLog:
    result = DEMO_SCENARIOS.get(incident_id)
    if not result:
        raise KeyError(
            f"No mock scenario for incident_id='{incident_id}'. "
            f"Available: {list(DEMO_SCENARIOS.keys())}"
        )
    return result


def list_scenarios() -> list[dict]:
    return [
        {
            "incident_id": log.incident_id,
            "service": log.signal.service,
            "error_type": log.signal.error_type,
            "category": log.category.value,
            "confidence": log.confidence.value,
            "reason": log.classification_reason,
        }
        for log in DEMO_SCENARIOS.values()
    ]
