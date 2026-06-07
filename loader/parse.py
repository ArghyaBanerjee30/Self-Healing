import argparse
import json
import logging
from pathlib import Path

from loader.parsers.python.python_parser import PythonParser
from loader.parsers.python.python_to_json import convert
from loader.uploader.neo4j_uploader import Neo4jUploader
from loader.utils import (
    HASHES_SUFFIX,
    hash_file,
    hash_node,
    hash_edges,
    load_hashes,
    save_hashes,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


class _NoOpObserver:
    def file_accessed(self, path: str) -> None:
        pass


def parse_and_upload(input_path: str, project_name: str, output_path: str) -> None:
    output = Path(output_path)
    hashes_path = str(output) + HASHES_SUFFIX

    # ── Step 1: Parse source files ────────────────────────────────────────────
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

    # ── Step 3: File-level gate ───────────────────────────────────────────────
    stored_hashes = load_hashes(hashes_path)
    file_hash = hash_file(str(output))

    if stored_hashes.get("__file__") == file_hash:
        logger.info("Manifest unchanged since last run — skipping upload.")
        return

    # ── Step 4: Diff nodes ────────────────────────────────────────────────────
    current_nodes: dict[str, dict] = {n["id"]: n for n in result.get("nodes", [])}
    current_edges: list[dict] = result.get("edges", [])

    current_node_hashes = {
        nid: {"hash": hash_node(n), "path": n.get("path", "")}
        for nid, n in current_nodes.items()
    }
    stored_node_hashes = {
        k: v for k, v in stored_hashes.items()
        if k not in ("__file__", "__edges__", "__edge_list__")
    }

    new_ids     = set(current_nodes) - set(stored_node_hashes)
    changed_ids = {
        nid
        for nid in set(current_nodes) & set(stored_node_hashes)
        if isinstance(stored_node_hashes.get(nid), dict)
        and current_node_hashes[nid]["hash"] != stored_node_hashes[nid].get("hash", "")
    }
    deleted_ids = set(stored_node_hashes) - set(current_nodes)

    # ── Step 5: Diff edges ────────────────────────────────────────────────────
    current_edges_hash, sorted_edges = hash_edges(current_edges)
    edges_changed = current_edges_hash != stored_hashes.get("__edges__", "")

    # ── Step 6: Log summary ───────────────────────────────────────────────────
    logger.info(f"Manifest → {output_path}")
    logger.info(f"  Total  : {len(current_nodes)} nodes, {len(current_edges)} edges")

    if not stored_node_hashes:
        logger.info("  Status : first run — all nodes are new")
    elif not new_ids and not changed_ids and not deleted_ids and not edges_changed:
        logger.info("  Status : all nodes and edges unchanged — skipping upload.")
        save_hashes(hashes_path, {
            **current_node_hashes,
            "__file__": file_hash,
            "__edges__": current_edges_hash,
            "__edge_list__": sorted_edges,
        })
        return
    else:
        if new_ids:
            logger.info(f"  New     : {len(new_ids)} nodes")
        if changed_ids:
            logger.info(f"  Changed : {len(changed_ids)} nodes")
        if deleted_ids:
            logger.info(f"  Deleted : {len(deleted_ids)} nodes")
        if edges_changed:
            logger.info("  Edges   : changed")

    # ── Step 7: Compute what to purge and what to write ───────────────────────
    paths_to_purge: set[str] = {
        stored_node_hashes[nid]["path"]
        for nid in (changed_ids | deleted_ids)
        if isinstance(stored_node_hashes.get(nid), dict)
        and stored_node_hashes[nid].get("path")
    }
    if edges_changed:
        stored_edge_set = {
            (e.get("from_id"), e.get("to_id"), e.get("type"))
            for e in stored_hashes.get("__edge_list__", [])
        }
        current_edge_set = {
            (e.get("from_id"), e.get("to_id"), e.get("type"))
            for e in current_edges
        }
        for from_id, to_id, _ in stored_edge_set ^ current_edge_set:
            for nid in (from_id, to_id):
                if nid in current_node_hashes and current_node_hashes[nid].get("path"):
                    paths_to_purge.add(current_node_hashes[nid]["path"])

    write_ids = (
        new_ids
        | changed_ids
        | {nid for nid, n in current_nodes.items() if n.get("path") in paths_to_purge}
    )

    nodes_to_write = []
    for nid in write_ids:
        n = dict(current_nodes[nid])
        n.setdefault("project_name", project_name)
        n.setdefault("additional_properties", {})
        n["additional_properties"].setdefault("project_name", project_name)
        nodes_to_write.append(n)

    edges_to_write = [
        e for e in current_edges
        if e["from_id"] in write_ids or e["to_id"] in write_ids
    ]

    hashes_to_save = {
        **current_node_hashes,
        "__file__": file_hash,
        "__edges__": current_edges_hash,
        "__edge_list__": sorted_edges,
    }

    # ── Step 8: Upload to Neo4j ───────────────────────────────────────────────
    Neo4jUploader().upload(
        nodes_to_write=nodes_to_write,
        edges_to_write=edges_to_write,
        paths_to_purge=list(paths_to_purge),
        hashes_to_save=hashes_to_save,
        hashes_path=hashes_path,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Parse a Python repo and upload to Neo4j")
    ap.add_argument("--input",        required=True,                      help="Path to the repo directory")
    ap.add_argument("--output",       default="loader/output/graph.json", help="Output JSON path")
    ap.add_argument("--project-name", default="",                         help="Project label")
    args = ap.parse_args()

    parse_and_upload(args.input, args.project_name, args.output)
