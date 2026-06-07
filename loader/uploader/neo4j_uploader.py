import json
import logging
import os
from collections import defaultdict
from typing import Any, LiteralString

from dotenv import load_dotenv
from neo4j import GraphDatabase

from loader.utils import batches

load_dotenv()

logger = logging.getLogger(__name__)

NODE_BATCH_SIZE = 10
EDGE_BATCH_SIZE = 500

MANIFEST_ID = "self_healing_manifest"
VECTOR_INDEX_NAME = "function_embeddings"
VECTOR_DIMENSIONS = 384

# ── Static Cypher queries ─────────────────────────────────────────────────────

_DELETE_BY_PATH: LiteralString = """
UNWIND $paths AS p
MATCH (n) WHERE n.path = p
OPTIONAL MATCH (n)-[:MADE_OF*]->(child)
WITH collect(n) + collect(child) AS to_delete
UNWIND to_delete AS nd
DETACH DELETE nd
"""

# Per-type template — label is a literal interpolated in Python, not a Cypher parameter
_UPSERT_NODE_TYPED = """
UNWIND $batch AS node
MERGE (n:{label} {{id: node.id, type: node.type}})
SET n += node
RETURN count(n)
"""

_SAVE_MANIFEST: LiteralString = """MERGE (m:Manifest {id: $id})
SET m.node_hashes = $node_hashes,
    m.edge_hash   = $edge_hash,
    m.edge_list   = $edge_list,
    m.updated_at  = timestamp()
"""

_LOAD_MANIFEST: LiteralString = """
MATCH (m:Manifest {id: $id})
RETURN m.node_hashes AS node_hashes,
       m.edge_hash   AS edge_hash,
       m.edge_list   AS edge_list
"""

# Edge query template — dynamic rel type, routed through _run_dynamic
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
        """For queries with runtime-interpolated rel types."""
        with GraphDatabase.driver(self.uri, auth=self.auth) as driver:
            with driver.session(database=self.database) as session:
                session.run(cypher, params or {})  # type: ignore[arg-type]

    def _query(self, cypher: LiteralString, params: dict[str, Any] | None = None) -> list:
        with GraphDatabase.driver(self.uri, auth=self.auth) as driver:
            with driver.session(database=self.database) as session:
                return list(session.run(cypher, params or {}))

    # ── Manifest node ─────────────────────────────────────────────────────────

    def load_manifest(self) -> dict:
        """Read stored hashes from the Manifest node. Returns {} if not found."""
        records = self._query(_LOAD_MANIFEST, {"id": MANIFEST_ID})
        if not records:
            return {}
        row = records[0]
        try:
            return {
                "node_hashes": json.loads(row["node_hashes"] or "{}"),
                "edge_hash":   row["edge_hash"] or "",
                "edge_list":   json.loads(row["edge_list"] or "[]"),
            }
        except (json.JSONDecodeError, TypeError):
            return {}

    def save_manifest(
        self,
        node_hashes: dict,
        edge_hash: str,
        edge_list: list[dict],
    ) -> None:
        """Persist hashes into the Manifest node in Neo4j."""
        self._run(
            _SAVE_MANIFEST,
            {
                "id":          MANIFEST_ID,
                "node_hashes": json.dumps(node_hashes),
                "edge_hash":   edge_hash,
                "edge_list":   json.dumps(edge_list),
            },
        )
        logger.info("Manifest node updated in Neo4j.")

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

        # Group by type so the label can be a literal in the MERGE clause
        by_type: dict[str, list] = defaultdict(list)
        for n in flat_nodes:
            by_type[n.get("type", "Node")].append(n)

        total = len(flat_nodes)
        written = 0
        for label, group in by_type.items():
            cypher = _UPSERT_NODE_TYPED.format(label=label)
            for batch in batches(group, NODE_BATCH_SIZE):
                self._run_dynamic(cypher, {"batch": batch})
                written += len(batch)
                logger.info(f"  Nodes: {written}/{total}")

    # ── Edges ─────────────────────────────────────────────────────────────────

    def upsert_edges(self, edges: list[dict]) -> None:
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

    # ── Vector index ─────────────────────────────────────────────────────────

    def ensure_vector_index(self) -> None:
        """Create the vector index on FUNCTION.embedding if it doesn't exist."""
        cypher = (
            f"CREATE VECTOR INDEX {VECTOR_INDEX_NAME} IF NOT EXISTS "
            f"FOR (n:FUNCTION) ON n.embedding "
            f"OPTIONS {{indexConfig: {{"
            f"`vector.dimensions`: {VECTOR_DIMENSIONS}, "
            f"`vector.similarity_function`: 'cosine'"
            f"}}}}"
        )
        self._run_dynamic(cypher)
        logger.info(f"Vector index '{VECTOR_INDEX_NAME}' ensured.")

    def upsert_embeddings(self, embeddings: list[dict]) -> None:
        """
        embeddings: list of {"id": <node_id>, "embedding": [float, ...]}
        Stores embedding on the matching FUNCTION node.
        """
        if not embeddings:
            return
        cypher = """
        UNWIND $batch AS row
        MATCH (n:FUNCTION {id: row.id})
        SET n.embedding = row.embedding
        """
        for batch in batches(embeddings, NODE_BATCH_SIZE):
            self._run_dynamic(cypher, {"batch": batch})
        logger.info(f"  Embeddings: {len(embeddings)} stored.")

    # ── Main entry ────────────────────────────────────────────────────────────

    def upload(
        self,
        nodes_to_write: list[dict],
        edges_to_write: list[dict],
        paths_to_purge: list[str],
        node_hashes: dict,
        edge_hash: str,
        edge_list: list[dict],
        embeddings: list[dict] | None = None,
    ) -> None:
        self.delete_by_paths(paths_to_purge)

        logger.info(f"Writing {len(nodes_to_write)} nodes ...")
        self.upsert_nodes(nodes_to_write)

        logger.info(f"Writing {len(edges_to_write)} edges ...")
        self.upsert_edges(edges_to_write)

        if embeddings:
            self.ensure_vector_index()
            logger.info(f"Storing {len(embeddings)} embeddings ...")
            self.upsert_embeddings(embeddings)

        self.save_manifest(node_hashes, edge_hash, edge_list)

        logger.info(
            f"Upload complete — {len(nodes_to_write)} nodes, "
            f"{len(edges_to_write)} edges written."
        )
