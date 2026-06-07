import logging
import os
from collections import defaultdict
from typing import Any, LiteralString

from dotenv import load_dotenv
from neo4j import GraphDatabase

from loader.utils import batches, save_hashes

load_dotenv()

logger = logging.getLogger(__name__)

NODE_BATCH_SIZE = 10
EDGE_BATCH_SIZE = 500

# ── Static Cypher queries (LiteralString) ─────────────────────────────────────

_DELETE_BY_PATH: LiteralString = """
UNWIND $paths AS p
MATCH (n) WHERE n.path = p
OPTIONAL MATCH (n)-[:MADE_OF*]->(child)
WITH collect(n) + collect(child) AS to_delete
UNWIND to_delete AS nd
DETACH DELETE nd
"""

_UPSERT_NODE: LiteralString = """
UNWIND $batch AS node
MERGE (n {id: node.id, type: node.type})
SET n += node
RETURN count(n)
"""

# Edge queries are built per rel_type — handled separately in upsert_edges()
_EDGE_QUERY_TEMPLATE = """
UNWIND $batch AS edge
MATCH (a {{id: edge.from_id}})
MATCH (b {{id: edge.to_id}})
MERGE (a)-[r:{rel_type}]->(b)
RETURN count(r)
"""


class Neo4jUploader:
    def __init__(self, database: str = "neo4j"):
        self.uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.auth = (
            os.getenv("NEO4J_USERNAME", "neo4j"),
            os.getenv("NEO4J_PASSWORD", ""),
        )
        self.database = database

    def _run(self, cypher: LiteralString, params: dict[str, Any] | None = None) -> None:
        with GraphDatabase.driver(self.uri, auth=self.auth) as driver:
            with driver.session(database=self.database) as session:
                session.run(cypher, params or {})

    def _run_dynamic(self, cypher: str, params: dict[str, Any] | None = None) -> None:
        """For queries built at runtime (e.g. edge type interpolation)."""
        with GraphDatabase.driver(self.uri, auth=self.auth) as driver:
            with driver.session(database=self.database) as session:
                session.run(cypher, params or {})  # type: ignore[arg-type]

    # ── Delete ────────────────────────────────────────────────────────────────

    def delete_by_paths(self, paths: list[str]) -> None:
        if not paths:
            return
        for batch in batches(paths, EDGE_BATCH_SIZE):
            self._run(_DELETE_BY_PATH, {"paths": batch})
        logger.info(f"Deleted nodes for {len(paths)} paths")

    # ── Nodes ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _flatten(node: dict) -> dict:
        """Flatten additional_properties into top-level keys Neo4j can store."""
        flat = {k: v for k, v in node.items() if k != "additional_properties"}
        for k, v in (node.get("additional_properties") or {}).items():
            if not isinstance(v, dict):
                flat[f"ap_{k}"] = v
        return flat

    def upsert_nodes(self, nodes: list[dict]) -> None:
        if not nodes:
            return
        flat_nodes = [self._flatten(n) for n in nodes]
        for i, batch in enumerate(batches(flat_nodes, NODE_BATCH_SIZE), 1):
            self._run(_UPSERT_NODE, {"batch": batch})
            logger.info(f"  Nodes: {i * NODE_BATCH_SIZE}/{len(nodes)}")

    # ── Edges ─────────────────────────────────────────────────────────────────

    def upsert_edges(self, edges: list[dict]) -> None:
        """Groups by rel type — Cypher rel type cannot be parameterised."""
        if not edges:
            return
        by_type: dict[str, list] = defaultdict(list)
        for e in edges:
            by_type[e["type"]].append(e)

        for rel_type, group in by_type.items():
            cypher = _EDGE_QUERY_TEMPLATE.format(rel_type=rel_type)
            for batch in batches(group, EDGE_BATCH_SIZE):
                self._run_dynamic(cypher, {"batch": batch})

        logger.info(f"  Edges: {len(edges)}/{len(edges)}")

    # ── Main entry ────────────────────────────────────────────────────────────

    def upload(
        self,
        nodes_to_write: list[dict],
        edges_to_write: list[dict],
        paths_to_purge: list[str],
        hashes_to_save: dict,
        hashes_path: str,
    ) -> None:
        self.delete_by_paths(paths_to_purge)

        logger.info(f"Writing {len(nodes_to_write)} nodes ...")
        self.upsert_nodes(nodes_to_write)

        logger.info(f"Writing {len(edges_to_write)} edges ...")
        self.upsert_edges(edges_to_write)

        save_hashes(hashes_path, hashes_to_save)
        logger.info(
            f"Upload complete — {len(nodes_to_write)} nodes, "
            f"{len(edges_to_write)} edges written."
        )
