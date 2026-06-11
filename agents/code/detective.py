"""
Detective Agent — queries Neo4j for deep code context, then calls Ollama for RCA.

Three layers of knowledge graph context:
  1. Neighbourhood   — direct structural connections (MADE_OF, CALLS, DEPENDS_ON)
  2. Blast radius    — recursive caller traversal + similar-code callers via vector search
  3. Vector similarity — semantically similar functions (code embeddings) for pattern context
"""
import json
import logging
import os
import re
from dataclasses import dataclass, asdict
from typing import Optional

import httpx
from dotenv import load_dotenv
from neo4j import GraphDatabase

from core.signal import Signal
from agents.code.observer import ObserverResult

load_dotenv()
log = logging.getLogger(__name__)

# Suppress Neo4j deprecation warnings for vector index queries
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

# Singleton embedder — loaded once, reused across all Detective calls
_embedder = None

def _get_embedder():
    global _embedder
    if _embedder is None:
        from loader.embedder.code_embedder import CodeEmbedder
        _embedder = CodeEmbedder()
    return _embedder


# ---------------------------------------------------------------------------
# Neo4j helpers
# ---------------------------------------------------------------------------

def _driver():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USERNAME", "neo4j"), os.getenv("NEO4J_PASSWORD", "")),
    )


def _q(cypher: str, params: dict) -> list[dict]:
    with _driver() as d:
        with d.session() as s:
            return [dict(r) for r in s.run(cypher, params)]


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class DetectiveResult:
    file_path: str
    line: int
    function_name: str
    source_code: str

    # KG layers
    neighbourhood: list[dict]     # direct structural connections
    blast_radius: list[dict]      # callers + similarity-inferred callers
    similar_functions: list[dict] # vector similarity results

    # RCA
    root_cause: str
    pattern: str

    # Formatted summary for the Coder prompt
    kg_summary: str

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, s: str) -> "DetectiveResult":
        return cls(**json.loads(s))


# ---------------------------------------------------------------------------
# Layer 1 — Neighbourhood
# Direct structural connections: what file owns it, what it calls, what calls it
# ---------------------------------------------------------------------------

def _get_neighbourhood(name: str, fragment: str) -> list[dict]:
    """
    Returns all nodes within 1 hop of the target function.
    Covers: owning FILE, direct CALLS (out), direct CALLS (in), DEPENDS_ON.
    """
    rows = _q("""
        MATCH (fn:FUNCTION)
        WHERE fn.display_name = $name AND fn.path CONTAINS $fragment
        MATCH (fn)-[r]-(neighbor)
        RETURN
            type(r)                  AS rel_type,
            labels(neighbor)[0]      AS neighbor_label,
            neighbor.display_name    AS neighbor_name,
            neighbor.path            AS neighbor_path,
            startNode(r) = fn        AS outgoing
        ORDER BY rel_type, neighbor_name
    """, {"name": name, "fragment": fragment})

    return [
        {
            "rel": r["rel_type"],
            "direction": "→" if r["outgoing"] else "←",
            "label": r["neighbor_label"],
            "name": r["neighbor_name"] or "unknown",
            "file": os.path.basename(r["neighbor_path"] or ""),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Layer 2 — Blast radius
# Who calls this function (recursive), plus similarity-inferred callers
# ---------------------------------------------------------------------------

def _get_direct_callers(name: str, fragment: str) -> list[dict]:
    """Multi-hop CALLS traversal — finds callers up to 3 hops away."""
    rows = _q("""
        MATCH path = (caller:FUNCTION)-[:CALLS*1..3]->(fn:FUNCTION)
        WHERE fn.display_name = $name AND fn.path CONTAINS $fragment
        RETURN
            caller.display_name AS name,
            caller.path         AS path,
            length(path)        AS depth
        ORDER BY depth
        LIMIT 15
    """, {"name": name, "fragment": fragment})
    return [{"name": r["name"], "file": os.path.basename(r["path"] or ""), "depth": r["depth"]} for r in rows]


def _get_vector_callers(embedding: list[float], own_name: str, threshold: float = 0.80) -> list[dict]:
    """
    Uses vector similarity to find functions that likely call or interact with
    the target — catching module-qualified calls the AST parser missed.
    Returns results above the similarity threshold.
    """
    rows = _q("""
        CALL db.index.vector.queryNodes('function_embeddings', 10, $emb)
        YIELD node, score
        WHERE node.display_name <> $own AND score >= $threshold
        RETURN
            node.display_name AS name,
            node.path         AS path,
            node.code         AS code,
            score
        ORDER BY score DESC
    """, {"emb": embedding, "own": own_name, "threshold": threshold})
    return [
        {
            "name": r["name"],
            "file": os.path.basename(r["path"] or ""),
            "score": round(r["score"], 3),
            "code_preview": (r["code"] or "")[:120],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Layer 3 — Vector similarity
# Semantically similar functions: useful for spotting same-pattern bugs elsewhere
# ---------------------------------------------------------------------------

def _get_similar_functions(embedding: list[float], own_name: str, top_k: int = 5) -> list[dict]:
    """Find the most semantically similar functions using code embeddings."""
    rows = _q("""
        CALL db.index.vector.queryNodes('function_embeddings', $k, $emb)
        YIELD node, score
        WHERE node.display_name <> $own
        RETURN
            node.display_name AS name,
            node.path         AS path,
            node.code         AS code,
            score
        ORDER BY score DESC
        LIMIT $k
    """, {"emb": embedding, "own": own_name, "k": top_k + 1})
    return [
        {
            "name": r["name"],
            "file": os.path.basename(r["path"] or ""),
            "score": round(r["score"], 3),
            "code_preview": (r["code"] or "")[:200],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# KG context formatter — builds the prompt context for the Coder
# ---------------------------------------------------------------------------

def _build_kg_summary(
    neighbourhood: list[dict],
    blast_radius: list[dict],
    vector_callers: list[dict],
    similar: list[dict],
) -> str:
    lines = []

    # Neighbourhood
    if neighbourhood:
        lines.append("NEIGHBOURHOOD (direct graph connections):")
        for n in neighbourhood:
            lines.append(f"  {n['direction']} [{n['rel']}] {n['name']} ({n['label']}) in {n['file']}")
    else:
        lines.append("NEIGHBOURHOOD: no direct connections found in KG")

    lines.append("")

    # Blast radius — AST callers
    lines.append("BLAST RADIUS (what breaks if this function changes):")
    if blast_radius:
        for c in blast_radius:
            lines.append(f"  depth={c['depth']}  {c['name']} ({c['file']}) — direct CALLS edge")
    else:
        lines.append("  No direct CALLS edges found (module-qualified calls may be missing from graph)")

    # Blast radius — vector-inferred callers
    if vector_callers:
        lines.append("  Vector-inferred callers (similarity ≥ 0.80 — likely interact with this function):")
        for c in vector_callers:
            lines.append(f"  score={c['score']}  {c['name']} ({c['file']})")
            if c["code_preview"]:
                lines.append(f"    preview: {c['code_preview'][:100]}")

    lines.append("")

    # Similar functions (pattern reference)
    if similar:
        lines.append("SIMILAR CODE PATTERNS (vector search — may have same bug or useful fix patterns):")
        for s in similar:
            lines.append(f"  score={s['score']}  {s['name']} ({s['file']})")
            if s["code_preview"]:
                lines.append(f"    code: {s['code_preview'][:150]}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ollama RCA
# ---------------------------------------------------------------------------

_RCA_SYSTEM = """You are a senior software engineer performing root cause analysis.

Given an error, source code, and knowledge graph context (neighbourhood, blast radius, similar patterns),
identify:
1. The exact root cause (one sentence)
2. The fix pattern (e.g. "missing null check", "missing guard clause", "missing error handling")
3. Blast radius warning: which callers or dependents will be affected by a fix

Respond ONLY in this JSON format:
{
  "root_cause": "one sentence",
  "pattern": "short fix pattern name",
  "blast_radius_note": "one sentence about what else might be affected"
}"""


def _ollama_rca(signal: Signal, source_code: str, kg_summary: str) -> tuple[str, str, str]:
    model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    base_url = os.getenv("OLLAMA_URL", "http://localhost:11434")

    prompt = (
        f"Error: {signal.error_type}: {signal.raw_message}\n\n"
        f"Stack trace:\n{signal.stack_trace or 'not available'}\n\n"
        f"Source code:\n```python\n{source_code[:3000]}\n```\n\n"
        f"Knowledge graph context:\n{kg_summary}\n\n"
        "Perform root cause analysis. Return JSON only."
    )

    try:
        resp = httpx.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _RCA_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        raw = resp.json()["message"]["content"]
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            return (
                parsed.get("root_cause", raw),
                parsed.get("pattern", "unknown pattern"),
                parsed.get("blast_radius_note", ""),
            )
        return raw.strip(), "unknown pattern", ""
    except Exception as e:
        log.warning("[Detective] Ollama RCA failed: %s", e)
        return f"{signal.error_type} in {signal.service}", "unknown pattern", ""


# ---------------------------------------------------------------------------
# Source reader
# ---------------------------------------------------------------------------

def _read_source(file_path: str) -> str:
    if not os.path.exists(file_path):
        return f"[File not found: {file_path}]"
    try:
        with open(file_path) as f:
            return f.read()
    except OSError as e:
        return f"[Could not read: {e}]"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(signal: Signal, observer: ObserverResult) -> DetectiveResult:
    log.info(
        "[Detective] investigating %s in %s:%d",
        observer.function_name, observer.path_fragment, observer.line,
    )

    source_code = _read_source(observer.file_path)

    # --- Embed the source code for vector queries (singleton — loads once) ---
    try:
        embedding = _get_embedder().embed(source_code)
        has_embedding = True
    except Exception as e:
        log.warning("[Detective] embedding failed: %s — skipping vector queries", e)
        embedding = []
        has_embedding = False

    # --- Layer 1: Neighbourhood ---
    neighbourhood = _get_neighbourhood(observer.function_name, observer.path_fragment)
    if neighbourhood:
        log.info("[Detective] neighbourhood: %d nodes", len(neighbourhood))
    else:
        log.warning("[Detective] function not found in KG — no neighbourhood")

    # --- Layer 2: Blast radius ---
    ast_callers = _get_direct_callers(observer.function_name, observer.path_fragment)
    vector_callers = _get_vector_callers(embedding, observer.function_name) if has_embedding else []
    blast_radius = ast_callers

    log.info(
        "[Detective] blast radius: %d AST callers, %d vector-inferred callers",
        len(ast_callers), len(vector_callers),
    )

    # --- Layer 3: Similar functions ---
    similar = _get_similar_functions(embedding, observer.function_name) if has_embedding else []
    log.info("[Detective] similar functions: %d found via vector search", len(similar))

    # --- Build KG summary ---
    kg_summary = _build_kg_summary(neighbourhood, ast_callers, vector_callers, similar)

    # --- Ollama RCA (now with full KG context) ---
    root_cause, pattern, blast_note = _ollama_rca(signal, source_code, kg_summary)

    if blast_note:
        kg_summary += f"\n\nBLAST RADIUS NOTE (from RCA): {blast_note}"

    log.info("[Detective] root_cause: %s", root_cause)
    log.info("[Detective] pattern: %s", pattern)

    return DetectiveResult(
        file_path=observer.file_path,
        line=observer.line,
        function_name=observer.function_name,
        source_code=source_code,
        neighbourhood=neighbourhood,
        blast_radius=blast_radius,
        similar_functions=similar,
        root_cause=root_cause,
        pattern=pattern,
        kg_summary=kg_summary,
    )
