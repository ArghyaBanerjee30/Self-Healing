import hashlib
import json
from pathlib import Path

HASHES_SUFFIX = ".hashes.json"


def hash_file(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def hash_node(node: dict) -> str:
    return hashlib.md5(
        json.dumps(node, sort_keys=True, default=str).encode()
    ).hexdigest()


def hash_edges(edges: list[dict]) -> str:
    sorted_edges = sorted(
        edges, key=lambda e: (e.get("from_id", ""), e.get("to_id", ""), e.get("type", ""))
    )
    return (
        hashlib.md5(json.dumps(sorted_edges, sort_keys=True).encode()).hexdigest(),
        sorted_edges,
    )


def load_hashes(path: str) -> dict:
    if Path(path).exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_hashes(path: str, hashes: dict) -> None:
    with open(path, "w") as f:
        json.dump(hashes, f, indent=2)


def batches(items: list, size: int) -> list:
    return [items[i: i + size] for i in range(0, len(items), size)]
