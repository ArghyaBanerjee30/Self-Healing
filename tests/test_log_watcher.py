"""Tests for watcher/log_watcher.py.

Strategy: exercise _process_line() directly so tests don't need threads
or real file I/O. Use flush() to drain single-line errors that have no
following traceback.
"""
import time
from typing import List

import pytest

from config.tenant_registry import EntryPoint, TenantConfig
from core.signal import Signal, SignalSource
from watcher.log_watcher import LogWatcher

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PAYMENTS_TRACEBACK = [
    "ERROR payments - TypeError: 'NoneType' object is not subscriptable",
    "Traceback (most recent call last):",
    '  File "app/services/payment_service.py", line 12, in process_payment',
    '    total = inventory["price"] * inventory["quantity"]',
    "TypeError: 'NoneType' object is not subscriptable",
]

INVENTORY_TRACEBACK = [
    "ERROR inventory - ZeroDivisionError: division by zero",
    "Traceback (most recent call last):",
    '  File "app/services/inventory_service.py", line 9, in get_unit_price',
    "    return total_value / stock",
    "ZeroDivisionError: division by zero",
]

CHECKOUT_TRACEBACK = [
    "ERROR checkout - ZeroDivisionError: division by zero",
    "Traceback (most recent call last):",
    '  File "app/services/checkout_service.py", line 10, in preview_total',
    "    avg = sum(prices) / len(cart)",
    "ZeroDivisionError: division by zero",
]


def make_config() -> TenantConfig:
    return TenantConfig(
        project_id="demo-commerce-api",
        production_log="logs/production.log",
        entry_points=[
            EntryPoint(
                service="payments",
                log_pattern="app/services/payment_service.py",
            ),
            EntryPoint(
                service="inventory",
                log_pattern="app/services/inventory_service.py",
            ),
            EntryPoint(
                service="checkout",
                log_pattern="app/services/checkout_service.py",
            ),
        ],
    )


def make_watcher() -> tuple[LogWatcher, List[Signal]]:
    signals: List[Signal] = []
    watcher = LogWatcher(make_config(), signals.append)
    return watcher, signals


# ---------------------------------------------------------------------------
# Single-line error (no traceback)
# ---------------------------------------------------------------------------


def test_single_line_error_emits_signal():
    watcher, signals = make_watcher()

    watcher._process_line("ERROR payments - TypeError: something went wrong")
    watcher.flush()

    assert len(signals) == 1
    s = signals[0]
    assert s.service == "payments"
    assert s.error_type == "TypeError"
    assert s.error_message == "something went wrong"
    assert s.source == SignalSource.LOG
    assert s.stack_trace is None


def test_single_line_error_flushed_by_next_error():
    """Arriving second ERROR line must flush the first before recording itself."""
    watcher, signals = make_watcher()

    watcher._process_line("ERROR payments - TypeError: first error")
    watcher._process_line("ERROR inventory - ZeroDivisionError: second error")
    watcher.flush()

    assert len(signals) == 2
    assert signals[0].service == "payments"
    assert signals[1].service == "inventory"


# ---------------------------------------------------------------------------
# Multi-line traceback accumulation
# ---------------------------------------------------------------------------


def test_traceback_accumulation():
    watcher, signals = make_watcher()

    for line in PAYMENTS_TRACEBACK:
        watcher._process_line(line)

    assert len(signals) == 1
    s = signals[0]
    assert s.service == "payments"
    assert s.error_type == "TypeError"
    assert s.error_message == "'NoneType' object is not subscriptable"
    assert s.source == SignalSource.LOG
    assert s.stack_trace is not None
    assert "Traceback (most recent call last):" in s.stack_trace
    assert "payment_service.py" in s.stack_trace
    assert "TypeError: 'NoneType' object is not subscriptable" in s.stack_trace


def test_traceback_not_emitted_mid_accumulation():
    """Signal must not fire until the terminal exception line is seen."""
    watcher, signals = make_watcher()

    # Feed all lines except the final exception line
    for line in PAYMENTS_TRACEBACK[:-1]:
        watcher._process_line(line)

    assert len(signals) == 0


def test_multiple_different_tracebacks():
    watcher, signals = make_watcher()

    for line in PAYMENTS_TRACEBACK:
        watcher._process_line(line)
    for line in INVENTORY_TRACEBACK:
        watcher._process_line(line)
    for line in CHECKOUT_TRACEBACK:
        watcher._process_line(line)

    assert len(signals) == 3
    services = [s.service for s in signals]
    assert services == ["payments", "inventory", "checkout"]


def test_all_three_demo_commerce_scenarios():
    """Covers the exact log patterns produced by demo-commerce-api incidents."""
    watcher, signals = make_watcher()

    for block in (PAYMENTS_TRACEBACK, INVENTORY_TRACEBACK, CHECKOUT_TRACEBACK):
        for line in block:
            watcher._process_line(line)

    assert {s.error_type for s in signals} == {"TypeError", "ZeroDivisionError"}
    assert {s.service for s in signals} == {"payments", "inventory", "checkout"}


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def test_dedup_same_error_within_60s():
    """Two identical errors within the TTL window emit only one Signal."""
    watcher, signals = make_watcher()

    for line in PAYMENTS_TRACEBACK:
        watcher._process_line(line)
    for line in PAYMENTS_TRACEBACK:
        watcher._process_line(line)

    assert len(signals) == 1


def test_dedup_different_errors_not_suppressed():
    """Different (service, error_type, message) keys are each emitted once."""
    watcher, signals = make_watcher()

    for line in PAYMENTS_TRACEBACK:
        watcher._process_line(line)
    for line in INVENTORY_TRACEBACK:
        watcher._process_line(line)

    assert len(signals) == 2


def test_dedup_same_error_after_ttl_emits_again(monkeypatch):
    """After the 60s TTL expires the same error is emitted again."""
    watcher, signals = make_watcher()

    for line in PAYMENTS_TRACEBACK:
        watcher._process_line(line)

    assert len(signals) == 1

    # Advance time past TTL by patching time.time inside the module
    original_time = time.time()
    monkeypatch.setattr(
        "watcher.log_watcher.time.time", lambda: original_time + 61
    )

    for line in PAYMENTS_TRACEBACK:
        watcher._process_line(line)

    assert len(signals) == 2


# ---------------------------------------------------------------------------
# Signal metadata
# ---------------------------------------------------------------------------


def test_signal_has_timestamp():
    watcher, signals = make_watcher()
    for line in PAYMENTS_TRACEBACK:
        watcher._process_line(line)
    assert signals[0].timestamp > 0


def test_signal_source_is_log():
    watcher, signals = make_watcher()
    for line in INVENTORY_TRACEBACK:
        watcher._process_line(line)
    assert signals[0].source == SignalSource.LOG
