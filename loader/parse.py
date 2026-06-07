import argparse
import hashlib
import json
import logging
from pathlib import Path

from loader.parsers.python.python_parser import PythonParser
from loader.parsers.python.python_to_json import convert

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

HASHES_SUFFIX = ".hashes.json"


class _NoOpObserver:
    def file_accessed(self, path: str) -> None:
        pass


# ── Hashing helpers ──────────────────────────────────────────────────────────

def _hash_file(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def _hash_node(node: dict) -> str:
    return hashlib.md5(
        json.dumps(node, sort_keys=True, default=str).encode()
    ).hexdigest()


def _load_hashes(path: str) -> dict:
    if Path(path).exists():
        with open(path) as f:
            return json.load(f)
    return {}


def _save_hashes(path: str, hashes: dict) -> None:
    with open(path, "w") as f:
        json.dump(hashes, f, indent=2)


# ── Core parse + differential check ─────────────────────────────────────────

def parse(input_path: str, project_name: str, output_path: str) -> None:
    output = Path(output_path)
    hashes_path = str(output) + HASHES_SUFFIX

    # ── Step 1: Parse source files ───────────────────────────────────────────
    file_paths = {str(p) for p in Path(input_path).rglob("*.py")}
    if not file_paths:
        logger.warning(f"No .py files found in {input_path}")
        return

    logger.info(f"Parsing {len(file_paths)} .py files from {input_path} ...")

    parser = PythonParser(observer=_NoOpObserver())
    nodes, relationships = parser.traverse_directory_tree(
        file_paths, pipeline_id="loader", base_path=input_path
    )
    result = convert(nodes, relationships, project_name=project_name)

    # ── Step 2: Write manifest ────────────────────────────────────────────────
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        json.dump(result, f, indent=2, default=str)

    # ── Step 3: File-level gate — did the manifest actually change? ──────────
    stored_hashes = _load_hashes(hashes_path)
    file_hash = _hash_file(str(output))

    if stored_hashes.get("__file__") == file_hash:
        logger.info("Manifest unchanged since last run — nothing to do.")
        return

    # ── Step 4: Node-level diff ──────────────────────────────────────────────
    current_nodes: dict[str, dict] = {n["id"]: n for n in result.get("nodes", [])}
    current_edges: list[dict] = result.get("edges", [])

    current_hashes: dict[str, dict] = {
        nid: {"hash": _hash_node(n), "path": n.get("path", "")}
        for nid, n in current_nodes.items()
    }
    stored_node_hashes = {
        k: v
        for k, v in stored_hashes.items()
        if k not in ("__file__", "__edges__", "__edge_list__")
    }

    new_ids     = set(current_nodes) - set(stored_node_hashes)
    changed_ids = {
        nid
        for nid in set(current_nodes) & set(stored_node_hashes)
        if isinstance(stored_node_hashes.get(nid), dict)
        and current_hashes[nid]["hash"] != stored_node_hashes[nid].get("hash", "")
    }
    deleted_ids = set(stored_node_hashes) - set(current_nodes)

    # ── Step 5: Edge-level diff ───────────────────────────────────────────────
    sorted_edges = sorted(
        current_edges,
        key=lambda e: (e.get("from_id", ""), e.get("to_id", ""), e.get("type", "")),
    )
    current_edges_hash = hashlib.md5(
        json.dumps(sorted_edges, sort_keys=True).encode()
    ).hexdigest()
    edges_changed = current_edges_hash != stored_hashes.get("__edges__", "")

    # ── Step 6: Report ────────────────────────────────────────────────────────
    logger.info(f"Written  → {output_path}")
    logger.info(f"  Total  : {len(current_nodes)} nodes, {len(current_edges)} edges")

    if not stored_node_hashes:
        logger.info("  Status : first run — all nodes are new")
    elif not new_ids and not changed_ids and not deleted_ids and not edges_changed:
        logger.info("  Status : all nodes and edges unchanged")
    else:
        if new_ids:
            logger.info(f"  New     : {len(new_ids)} nodes")
        if changed_ids:
            logger.info(f"  Changed : {len(changed_ids)} nodes")
        if deleted_ids:
            logger.info(f"  Deleted : {len(deleted_ids)} nodes")
        if edges_changed:
            logger.info("  Edges   : changed")

    # ── Step 7: Save sidecar hashes ───────────────────────────────────────────
    _save_hashes(hashes_path, {
        **current_hashes,
        "__file__": file_hash,
        "__edges__": current_edges_hash,
        "__edge_list__": sorted_edges,
    })


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Parse a Python repo into nodes/edges JSON")
    ap.add_argument("--input",        required=True,                          help="Path to the repo directory")
    ap.add_argument("--output",       default="loader/output/graph.json",     help="Output JSON path")
    ap.add_argument("--project-name", default="",                             help="Project label")
    args = ap.parse_args()

    parse(args.input, args.project_name, args.output)
