"""
Observer Agent — extracts the real app file, line, and function from a stack trace.

Skips framework and venv paths (starlette, fastapi, site-packages, etc.)
and returns the first stack frame that belongs to application code.
"""
import re
from dataclasses import dataclass, asdict
from typing import Optional
import json

from core.signal import Signal

# Paths that belong to the framework / stdlib / venv — not app code
_SKIP_FRAGMENTS = (
    "site-packages",
    "dist-packages",
    ".venv",
    "/starlette/",
    "/fastapi/",
    "/uvicorn/",
    "/httpx/",
    "/pydantic/",
    "/anyio/",
    "/asyncio/",
    "threading.py",
    "concurrent/",
    "<frozen",
    "<string>",
    "/usr/lib/python",
    "/usr/local/lib/python",
)

# Matches:  File "/path/to/file.py", line 42, in function_name
_FRAME_RE = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')


@dataclass
class ObserverResult:
    file_path: str       # absolute path to the app file
    line: int            # line number of the failure
    function_name: str   # name of the failing function
    path_fragment: str   # basename used for Neo4j lookup (e.g. "payment_service.py")
    found: bool = True

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, s: str) -> "ObserverResult":
        return cls(**json.loads(s))

    @classmethod
    def not_found(cls, reason: str) -> "ObserverResult":
        return cls(file_path="", line=0, function_name="", path_fragment="", found=False)


def _is_app_frame(path: str) -> bool:
    return not any(frag in path for frag in _SKIP_FRAGMENTS)


def run(signal: Signal) -> ObserverResult:
    """
    Parse the stack trace in *signal* and return the first app-owned frame.
    Returns ObserverResult(found=False) when no app frame can be identified.
    """
    if not signal.stack_trace:
        return ObserverResult.not_found("no stack trace in signal")

    # Walk frames from the bottom (innermost) upward — the bug is closest to
    # the bottom of the trace, not the middleware at the top.
    frames = _FRAME_RE.findall(signal.stack_trace)

    # Reverse: innermost first
    for path, line_str, func in reversed(frames):
        if _is_app_frame(path):
            import os
            return ObserverResult(
                file_path=path,
                line=int(line_str),
                function_name=func,
                path_fragment=os.path.basename(path),
                found=True,
            )

    # Fallback: if every frame is framework, take the last non-stdlib frame
    for path, line_str, func in reversed(frames):
        if "site-packages" not in path and ".venv" not in path:
            import os
            return ObserverResult(
                file_path=path,
                line=int(line_str),
                function_name=func,
                path_fragment=os.path.basename(path),
                found=True,
            )

    return ObserverResult.not_found("all frames are framework/venv paths")
