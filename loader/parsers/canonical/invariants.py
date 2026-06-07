# canonical/invariants.py

import sys
from dataclasses import dataclass
from enum import Enum
from typing import Callable


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass
class Invariant:
    check: Callable[[dict], list[str]]
    severity: Severity
    name: str


class ParseResultInvariantError(Exception):
    pass


def _check_file_code_chunk_edges(result: dict) -> list[str]:
    nodes = result.get("nodes", [])
    edges = result.get("edges", [])
    code_chunk_ids = {
        n["id"] for n in nodes if "CODE_CHUNK" in n.get("category", [])
    }
    files_with_chunks = {
        e["from_id"]
        for e in edges
        if e.get("type") == "MADE_OF" and e.get("to_id") in code_chunk_ids
    }
    return [
        f"FILE '{n.get('path', n['id'])}' has no MADE_OF edge to any CODE_CHUNK node"
        for n in nodes
        if n.get("type") == "FILE" and n["id"] not in files_with_chunks
    ]


_INVARIANTS: list[Invariant] = [
    Invariant(
        check=_check_file_code_chunk_edges,
        severity=Severity.WARNING,
        name="file_code_chunk_edges",
    ),
]


def build_parse_result(generator: str, nodes: list[dict], edges: list[dict]) -> dict:
    """Build a canonical parse result dict and validate it against all invariants."""
    result = {"version": "1.0", "generator": generator, "nodes": nodes, "edges": edges}
    validate(result)
    return result


def validate(result: dict, _invariants: list[Invariant] | None = None) -> None:
    """Run all invariants. Raises ParseResultInvariantError on any ERROR violations.
    Prints WARNING violations to stderr."""
    if _invariants is None:
        _invariants = _INVARIANTS
    error_lines: list[str] = []
    for inv in _invariants:
        for violation in inv.check(result):
            msg = f"[{inv.name}] {violation}"
            if inv.severity == Severity.ERROR:
                error_lines.append(f"  {msg}")
            else:
                print(f"WARNING {msg}", file=sys.stderr)
    if error_lines:
        body = "\n".join(error_lines)
        raise ParseResultInvariantError(
            f"Parse result failed {len(error_lines)} invariant check(s):\n{body}"
        )
