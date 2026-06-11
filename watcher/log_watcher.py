"""
Tails a log file and emits Signal objects for each detected error or exception.

Log format expected (demo-commerce-api):
    ERROR {service} - {ErrorType}: {message}
    Traceback (most recent call last):
      File "...", line X, in fn
        code
    ErrorType: message
"""
import re
import time
from typing import Callable, Optional

from config.tenant_registry import TenantConfig
from core.signal import Signal, SignalSource

# Matches: "ERROR payments - TypeError: 'NoneType' object is not subscriptable"
_ERROR_LINE_RE = re.compile(
    r"^(?:ERROR|EXCEPTION|FATAL)\s+([\w][\w-]*)\s+-\s+(\w+):\s+(.*)"
)

# Matches the terminal exception line of a traceback, e.g. "TypeError: foo"
# Must start at column 0 (not indented) to avoid matching mid-traceback file lines.
_FINAL_EXCEPTION_RE = re.compile(
    r"^([A-Z][a-zA-Z0-9_]+(?:Error|Exception|Warning|Interrupt|Exit|Stop)):\s*(.*)"
)

_DEDUP_TTL_SECONDS = 60.0


class LogWatcher:
    def __init__(self, config: TenantConfig, signal_callback: Callable[[Signal], None]):
        self._config = config
        self._callback = signal_callback
        # Maps (service, error_type, error_message) → last-emitted timestamp
        self._seen: dict[tuple[str, str, str], float] = {}
        self._reset_state()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def watch(self, log_file: str) -> None:
        """Blocking. Seeks to the end of log_file and tails it, calling
        signal_callback for each newly detected error signal."""
        with open(log_file) as f:
            f.seek(0, 2)  # start from the current end
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.1)
                    continue
                self._process_line(line.rstrip("\n"))

    def flush(self) -> None:
        """Emit any pending single-line error that has no following traceback.
        Call after processing a batch of lines in tests or at shutdown."""
        if self._service and self._error_type:
            stack = "\n".join(self._traceback_lines) if self._traceback_lines else None
            self._emit_signal(stack)
            self._reset_state()

    # ------------------------------------------------------------------
    # Internal state machine (exposed as _process_line for unit tests)
    # ------------------------------------------------------------------

    def _process_line(self, line: str) -> None:
        """Feed one log line into the state machine."""
        # ── New top-level ERROR / EXCEPTION / FATAL line ──────────────
        m = _ERROR_LINE_RE.match(line)
        if m:
            # Flush whatever was pending (incomplete or single-line error)
            if self._service and self._error_type:
                stack = (
                    "\n".join(self._traceback_lines)
                    if self._traceback_lines
                    else None
                )
                self._emit_signal(stack)
            self._reset_state()
            self._service = m.group(1)
            self._error_type = m.group(2)
            self._error_message = m.group(3)
            return

        # ── Traceback header ──────────────────────────────────────────
        if line.strip() == "Traceback (most recent call last):":
            if not self._in_traceback:
                # First traceback for this error - begin accumulation
                self._in_traceback = True
                self._traceback_lines = [line]
            else:
                # Chained exception ("During handling of the above exception...")
                # Keep accumulating into the same buffer
                self._traceback_lines.append(line)
            return

        # ── Inside a traceback: accumulate until the terminal line ─────
        if self._in_traceback:
            self._traceback_lines.append(line)
            # Terminal line: unindented and matches the exception type we already know,
            # or any exception type if no ERROR-line context is available.
            if not line.startswith(" "):
                is_terminal = (
                    self._error_type and line.startswith(f"{self._error_type}:")
                ) or (not self._error_type and _FINAL_EXCEPTION_RE.match(line))
                if is_terminal:
                    self._emit_signal("\n".join(self._traceback_lines))
                    self._reset_state()
            return

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _reset_state(self) -> None:
        self._service: Optional[str] = None
        self._error_type: Optional[str] = None
        self._error_message: Optional[str] = None
        self._traceback_lines: list[str] = []
        self._in_traceback: bool = False

    def _emit_signal(self, stack_trace: Optional[str]) -> None:
        if not self._service or not self._error_type:
            return
        key = (self._service, self._error_type, self._error_message or "")
        now = time.time()
        last = self._seen.get(key)
        if last is not None and now - last < _DEDUP_TTL_SECONDS:
            return
        self._seen[key] = now
        self._callback(
            Signal(
                service=self._service,
                error_type=self._error_type,
                error_message=self._error_message or "",
                source=SignalSource.LOG,
                stack_trace=stack_trace,
            )
        )
