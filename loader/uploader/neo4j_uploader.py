import logging
import os
from collections import defaultdict

from dotenv import load_dotenv
from neo4j import GraphDatabase

from loader.utils import batches, save_hashes

load_dotenv()

logger = logging.getLogger(__name__)

NODE_BATCH_SIZE = 10
EDGE_BATCH_SIZE = 500


class Neo4jUploader:
    def __init__(self, database: str = "neo4j"):
        self.uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.auth = (
            os.getenv("NEO4J_USERNAME", "neo4j"),
            os.getenv("NEO4J_PASSWORD", ""),
        )
        self.database = database

    def _run(self, cypher: str, params: dict):
        with GraphDatabase.driver(self.uri, auth=self.auth) as driver:
            driver.execute_query(cypher, params or {}, database_=self.database)

    # ── Delete ────────────────────────────────────────────────────────────────

    def delete_by_paths(self, paths: list[str]) -> None:
        if not paths:
            return
        for batch in batches(paths, EDGE_BATCH_SIZE):
            self._run(
                """
                UNWIND $paths AS p
                MATCH (n) WHERE n.path = p
                OPTIONAL MATCH (n)-[:MADE_OF*]->(child)
                WITH collect(n) + collect(child) AS to_delete
                UNWIND to_delete AS nd
                DETACH DELETE nd
                """,
                {"paths": batch},
            )
        logger.info(f"Deleted nodes for {len(paths)} paths")

    # ── Nodes ─────────────────────────────────────────────────────────────────

    def upsert_nodes(self, nodes: list[dict]) -> None:
        if not nodes:
            return
        for i, batch in enumerate(batches(nodes, NODE_BATCH_SIZE), 1):
            self._run(
                """
                UNWIND $batch AS node
                MERGE (n {id: node.id, type: node.type})
                SET n.display_name          = node.display_name,
                    n.path                  = node.path,
                    n.language              = coalesce(node.language, ''),
                    n.code                  = coalesce(node.code, ''),
                    n.loc                   = coalesce(node.loc, 0),
                    n.cyclomatic_complexity = coalesce(node.cyclomatic_complexity, 1),
                    n.category              = node.category,
                    n.generator             = coalesce(node.generator, ''),
                    n.project_name          = coalesce(node.project_name, ''),
                    n.additional_properties = node.additional_properties
                RETURN count(n)
                """,
                {"batch": batch},
            )
            logger.info(f"  Nodes: {i * NODE_BATCH_SIZE}/{len(nodes)}")

    # ── Edges ─────────────────────────────────────────────────────────────────

    def upsert_edges(self, edges: list[dict]) -> None:
        """Groups edges by relationship type — Cypher rel type must be a literal."""
        if not edges:
            return
        by_type: dict[str, list] = defaultdict(list)
        for e in edges:
            by_type[e["type"]].append(e)

        for rel_type, group in by_type.items():
            for batch in batches(group, EDGE_BATCH_SIZE):
                self._run(
                    f"""
                    UNWIND $batch AS edge
                    MATCH (a {{id: edge.from_id}})
                    MATCH (b {{id: edge.to_id}})
                    MERGE (a)-[r:{rel_type}]->(b)
                    RETURN count(r)
                    """,
                    {"batch": batch},
                )
        logger.info(f"  Edges: {len(edges)}/{len(edges)}")

    # ── Main entry: accepts pre-computed diff from parse.py ───────────────────

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
