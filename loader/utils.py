import hashlib
import json


def hash_node(node: dict) -> str:
    return hashlib.md5(
        json.dumps(node, sort_keys=True, default=str).encode()
    ).hexdigest()


def hash_edges(edges: list[dict]) -> tuple[str, list[dict]]:
    sorted_edges = sorted(
        edges, key=lambda e: (e.get("from_id", ""), e.get("to_id", ""), e.get("type", ""))
    )
    edge_hash = hashlib.md5(
        json.dumps(sorted_edges, sort_keys=True).encode()
    ).hexdigest()
    return edge_hash, sorted_edges


def batches(items: list, size: int) -> list:
    return [items[i: i + size] for i in range(0, len(items), size)]
