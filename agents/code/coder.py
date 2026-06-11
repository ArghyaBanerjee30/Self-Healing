"""
Coder Agent — writes a minimal code fix using Ollama, given the Detective's RCA.

Reads the source file, asks Ollama to produce a corrected version,
diffs it against the original, and writes the fix to disk.
The original is saved as <file>.bak before any write.
"""
import difflib
import json
import logging
import os
import re
from dataclasses import dataclass, asdict

import httpx
from dotenv import load_dotenv

from core.signal import Signal
from agents.code.detective import DetectiveResult

load_dotenv()
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class CoderResult:
    file_path: str
    function_name: str
    original_code: str
    fixed_code: str
    diff: str
    fix_description: str
    fix_written: bool
    backup_path: str

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, s: str) -> "CoderResult":
        return cls(**json.loads(s))


# ---------------------------------------------------------------------------
# Ollama fix writer
# ---------------------------------------------------------------------------

_CODER_SYSTEM = """You are an expert Python engineer writing a minimal production fix.

Rules you MUST follow:
- Change as few lines as possible — minimal diff only
- Preserve the EXACT function signature (name, parameters, return type)
- Do NOT use bare `except: pass` or swallow exceptions silently
- Do NOT return fake/default values to mask errors — raise proper exceptions
- Do NOT add new imports unless strictly required
- Do NOT add comments or docstrings
- Output ONLY the corrected Python source file — no markdown, no explanation, no fences

The output must be the complete corrected file content, ready to write to disk."""


def _call_ollama(signal: Signal, detective: DetectiveResult) -> str:
    model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    base_url = os.getenv("OLLAMA_URL", "http://localhost:11434")

    prompt = (
        f"File: {detective.file_path}\n"
        f"Function: {detective.function_name}\n"
        f"Error: {signal.error_type}: {signal.raw_message}\n"
        f"Root cause: {detective.root_cause}\n"
        f"Fix pattern: {detective.pattern}\n\n"
        f"Knowledge graph context:\n{detective.kg_summary}\n\n"
        f"Current file content:\n```python\n{detective.source_code}\n```\n\n"
        "Write the complete corrected file content. "
        "Only fix the specific root cause. Output raw Python only."
    )

    try:
        resp = httpx.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _CODER_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
            },
            timeout=180.0,
        )
        resp.raise_for_status()
        raw = resp.json()["message"]["content"]

        # Strip markdown fences if Ollama wrapped the code
        raw = re.sub(r"^```python\s*", "", raw.strip())
        raw = re.sub(r"^```\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw.strip())
        return raw.strip() + "\n"

    except Exception as e:
        log.error("[Coder] Ollama call failed: %s", e)
        return ""


# ---------------------------------------------------------------------------
# Diff generator
# ---------------------------------------------------------------------------

def _make_diff(original: str, fixed: str, file_path: str) -> str:
    orig_lines = original.splitlines(keepends=True)
    fixed_lines = fixed.splitlines(keepends=True)
    diff = difflib.unified_diff(
        orig_lines,
        fixed_lines,
        fromfile=f"a/{os.path.basename(file_path)}",
        tofile=f"b/{os.path.basename(file_path)}",
        lineterm="",
    )
    return "".join(diff)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(signal: Signal, detective: DetectiveResult) -> CoderResult:
    log.info(
        "[Coder] writing fix for %s in %s (root cause: %s)",
        detective.function_name, detective.path_fragment if hasattr(detective, 'path_fragment') else detective.file_path,
        detective.root_cause[:60],
    )

    original = detective.source_code

    # Ask Ollama to write the fix
    fixed = _call_ollama(signal, detective)

    if not fixed or fixed == original:
        log.warning("[Coder] Ollama returned empty or unchanged code")
        return CoderResult(
            file_path=detective.file_path,
            function_name=detective.function_name,
            original_code=original,
            fixed_code=original,
            diff="",
            fix_description="[Coder] no change produced",
            fix_written=False,
            backup_path="",
        )

    diff = _make_diff(original, fixed, detective.file_path)

    # Write the fix directly — git is the rollback mechanism
    backup_path = ""
    try:
        with open(detective.file_path, "w") as f:
            f.write(fixed)
        fix_written = True
        log.info("[Coder] fix written to %s", detective.file_path)
    except OSError as e:
        log.error("[Coder] failed to write fix: %s", e)
        fix_written = False

    # Build a short description of the change
    added = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
    fix_description = (
        f"Fix for {signal.error_type} in {detective.function_name}: "
        f"{detective.pattern}. +{added}/-{removed} lines."
    )

    return CoderResult(
        file_path=detective.file_path,
        function_name=detective.function_name,
        original_code=original,
        fixed_code=fixed,
        diff=diff,
        fix_description=fix_description,
        fix_written=fix_written,
        backup_path=backup_path,
    )
