import argparse
import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from loader.embedder.code_embedder import CodeEmbedder
from loader.parsers.python.python_parser import PythonParser
from loader.parsers.python.python_to_json import convert
from loader.uploader.neo4j_uploader import Neo4jUploader
from loader.utils import hash_node, hash_edges

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

PROJECT_NAME = "my_project"


class _NoOpObserver:
    def file_accessed(self, path: str) -> None:
        pass


# ── Stats tracker ─────────────────────────────────────────────────────────────

@dataclass
class LoaderStats:
    # Timings (seconds)
    t_parse:     float = 0.0
    t_diff:      float = 0.0
    t_embed:     float = 0.0
    t_upload:    float = 0.0
    t_total:     float = 0.0

    # Counts
    files_parsed:       int = 0
    loc_total:          int = 0
    nodes_total:        int = 0
    edges_total:        int = 0
    nodes_new:          int = 0
    nodes_changed:      int = 0
    nodes_deleted:      int = 0
    nodes_written:      int = 0
    edges_written:      int = 0
    functions_embedded: int = 0
    tokens_consumed:    int = 0   # estimated: chars / 3

    def print(self) -> None:
        sep = "─" * 44
        logger.info("")
        logger.info(sep)
        logger.info("  Loader Stats")
        logger.info(sep)
        logger.info(f"  Files parsed       : {self.files_parsed}")
        logger.info(f"  Lines of code      : {self.loc_total:,}")
        logger.info(f"  Nodes (total)      : {self.nodes_total}")
        logger.info(f"  Edges (total)      : {self.edges_total}")
        logger.info(sep)
        logger.info(f"  Nodes written      : {self.nodes_written}")
        logger.info(f"    new              : {self.nodes_new}")
        logger.info(f"    changed          : {self.nodes_changed}")
        logger.info(f"    deleted          : {self.nodes_deleted}")
        logger.info(f"  Edges written      : {self.edges_written}")
        logger.info(sep)
        logger.info(f"  Functions embedded : {self.functions_embedded}")
        logger.info(f"  Tokens consumed    : ~{self.tokens_consumed:,}  (estimated)")
        logger.info(sep)
        logger.info(f"  Parse time         : {self.t_parse:.2f}s")
        logger.info(f"  Diff time          : {self.t_diff:.2f}s")
        logger.info(f"  Embed time         : {self.t_embed:.2f}s")
        logger.info(f"  Upload time        : {self.t_upload:.2f}s")
        logger.info(f"  Total time         : {self.t_total:.2f}s")
        logger.info(sep)


def _count_loc(input_path: str) -> int:
    """
    Count lines of code using cloc if available, otherwise fall back to
    counting non-blank, non-comment lines in .py files ourselves.
    Matches cloc's 'code' column for Python.
    """
    if shutil.which("cloc"):
        try:
            result = subprocess.run(
                ["cloc", "--include-lang=Python", "--csv", "--quiet", input_path],
                capture_output=True, text=True, timeout=30,
            )
            for line in result.stdout.splitlines():
                parts = line.split(",")
                # cloc CSV format: language,files,blank,comment,code
                if len(parts) == 5 and parts[0].strip() == "Python":
                    return int(parts[4].strip())
        except Exception:
            pass

    # Fallback: count non-blank, non-comment lines ourselves
    total = 0
    for path in Path(input_path).rglob("*.py"):
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        total += 1
        except OSError:
            pass
    return total


def parse_and_upload(input_path: str, output_path: str) -> None:
    stats = LoaderStats()
    t_start = time.perf_counter()

    # ── Step 1: Parse source files ────────────────────────────────────────────
    t0 = time.perf_counter()
    file_paths = {str(p) for p in Path(input_path).rglob("*.py")}
    if not file_paths:
        logger.warning(f"No .py files found in {input_path}")
        return

    logger.info(f"Parsing {len(file_paths)} .py files from {input_path} ...")
    parser = PythonParser(observer=_NoOpObserver())
    nodes, relationships = parser.traverse_directory_tree(
        file_paths, pipeline_id="loader", base_path=input_path
    )
    result = convert(nodes, relationships, project_name=PROJECT_NAME)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        json.dump(result, f, indent=2, default=str)

    stats.t_parse      = time.perf_counter() - t0
    stats.files_parsed = len(file_paths)
    stats.nodes_total  = len(result.get("nodes", []))
    stats.edges_total  = len(result.get("edges", []))
    stats.loc_total    = _count_loc(input_path)

    # ── Step 2: Load previous state from Neo4j Manifest node ─────────────────
    t0 = time.perf_counter()
    uploader = Neo4jUploader()
    stored = uploader.load_manifest()

    stored_node_hashes: dict = stored.get("node_hashes", {})
    stored_edge_hash: str    = stored.get("edge_hash", "")
    stored_edge_list: list   = stored.get("edge_list", [])

    # ── Step 3: Diff nodes ────────────────────────────────────────────────────
    current_nodes: dict[str, dict] = {n["id"]: n for n in result.get("nodes", [])}
    current_edges: list[dict]      = result.get("edges", [])

    current_node_hashes = {
        nid: {"hash": hash_node(n), "path": n.get("path", "")}
        for nid, n in current_nodes.items()
    }

    new_ids     = set(current_nodes) - set(stored_node_hashes)
    changed_ids = {
        nid
        for nid in set(current_nodes) & set(stored_node_hashes)
        if isinstance(stored_node_hashes.get(nid), dict)
        and current_node_hashes[nid]["hash"] != stored_node_hashes[nid].get("hash", "")
    }
    deleted_ids = set(stored_node_hashes) - set(current_nodes)

    # ── Step 4: Diff edges ────────────────────────────────────────────────────
    current_edge_hash, sorted_edges = hash_edges(current_edges)
    edges_changed = current_edge_hash != stored_edge_hash

    stats.t_diff       = time.perf_counter() - t0
    stats.nodes_new     = len(new_ids)
    stats.nodes_changed = len(changed_ids)
    stats.nodes_deleted = len(deleted_ids)

    # ── Step 5: Log diff summary ──────────────────────────────────────────────
    logger.info(f"Manifest → {output_path}")
    logger.info(f"  Total  : {len(current_nodes)} nodes, {len(current_edges)} edges")

    if not stored_node_hashes:
        logger.info("  Status : first run — all nodes are new")
    elif not new_ids and not changed_ids and not deleted_ids and not edges_changed:
        logger.info("  Status : all nodes and edges unchanged — skipping upload.")
        stats.t_total = time.perf_counter() - t_start
        stats.print()
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

    # ── Step 6: Compute what to purge and write ───────────────────────────────
    paths_to_purge: set[str] = {
        stored_node_hashes[nid]["path"]
        for nid in (changed_ids | deleted_ids)
        if isinstance(stored_node_hashes.get(nid), dict)
        and isinstance(stored_node_hashes[nid].get("path"), str)
        and stored_node_hashes[nid]["path"]
    }
    if edges_changed:
        stored_edge_set = {
            (e.get("from_id"), e.get("to_id"), e.get("type"))
            for e in stored_edge_list
        }
        current_edge_set = {
            (e.get("from_id"), e.get("to_id"), e.get("type"))
            for e in current_edges
        }
        for from_id, to_id, _ in stored_edge_set ^ current_edge_set:
            for nid in (from_id, to_id):
                if nid in current_node_hashes:
                    path = current_node_hashes[nid].get("path")
                    if isinstance(path, str) and path:
                        paths_to_purge.add(path)

    write_ids = (
        new_ids
        | changed_ids
        | {nid for nid, n in current_nodes.items() if n.get("path") in paths_to_purge}
    )

    nodes_to_write = []
    for nid in write_ids:
        n = dict(current_nodes[nid])
        n.setdefault("project_name", PROJECT_NAME)
        n.setdefault("additional_properties", {})
        n["additional_properties"].setdefault("project_name", PROJECT_NAME)
        nodes_to_write.append(n)

    edges_to_write = [
        e for e in current_edges
        if e["from_id"] in write_ids or e["to_id"] in write_ids
    ]

    stats.nodes_written = len(nodes_to_write)
    stats.edges_written = len(edges_to_write)

    # ── Step 7: Generate embeddings for FUNCTION nodes ────────────────────────
    t0 = time.perf_counter()
    function_nodes = [
        n for n in nodes_to_write
        if n.get("type") == "FUNCTION" and n.get("code", "").strip()
    ]
    embeddings: list[dict] = []
    if function_nodes:
        logger.info(f"Generating embeddings for {len(function_nodes)} functions ...")
        embedder = CodeEmbedder()
        codes = [n["code"] for n in function_nodes]
        vectors = embedder.embed_batch(codes)
        embeddings = [
            {"id": n["id"], "embedding": v}
            for n, v in zip(function_nodes, vectors)
        ]
        total_chars = sum(len(c) for c in codes)
        stats.functions_embedded = len(function_nodes)
        stats.tokens_consumed    = total_chars // 3  # ~3 chars per token for Python

    stats.t_embed = time.perf_counter() - t0

    # ── Step 8: Upload to Neo4j ───────────────────────────────────────────────
    t0 = time.perf_counter()
    uploader.upload(
        nodes_to_write=nodes_to_write,
        edges_to_write=edges_to_write,
        paths_to_purge=list(paths_to_purge),
        node_hashes=current_node_hashes,
        edge_hash=current_edge_hash,
        edge_list=sorted_edges,
        embeddings=embeddings,
    )
    stats.t_upload = time.perf_counter() - t0

    stats.t_total = time.perf_counter() - t_start
    stats.print()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Parse a Python repo and upload to Neo4j")
    ap.add_argument("--input",  required=True,                      help="Path to the repo directory")
    ap.add_argument("--output", default="loader/output/graph.json", help="Output JSON path")
    args = ap.parse_args()

    parse_and_upload(args.input, args.output)
