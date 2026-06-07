# © 2025 Thoughtworks, Inc. | Thoughtworks Pre-Existing Intellectual Property, Thoughtworks Tools | Patent Pending | See License file for permissions.

import os
from typing import Any

from parsers.canonical.invariants import build_parse_result
from parsers.common.dedup import build_display_codes
from parsers.common.metrics import cc, loc
from parsers.python.python_models import PythonNode, PythonNodeType, PythonRelationship

# Top-level types that get MADE_OF edges from FILE nodes.
_TOP_LEVEL_TYPES = frozenset(
    {
        PythonNodeType.CLASS.value,
        PythonNodeType.FUNCTION.value,
    }
)

# Types where cyclomatic complexity is meaningful.
_EXECUTABLE_TYPES = frozenset({PythonNodeType.FUNCTION.value})

GENERATOR = "python-loader"


def convert(
    nodes: list[PythonNode],
    relationships: list[PythonRelationship],
    project_name: str = "",
) -> dict[str, Any]:
    """Convert PythonNode/PythonRelationship lists to a canonical parse result dict."""
    display_codes = build_display_codes(nodes)
    json_nodes = [_node_to_dict(n, project_name, display_codes) for n in nodes]
    json_nodes.extend(_build_filesystem_nodes(nodes))
    json_edges = [_rel_to_dict(r) for r in relationships]
    return build_parse_result(GENERATOR, json_nodes, json_edges)


def _node_to_dict(
    node: PythonNode, project_name: str, display_codes: dict[str, str]
) -> dict[str, Any]:
    code = display_codes.get(node.id, node.code) or ""
    is_file = node.type == PythonNodeType.FILE.value
    category = ["FILE_SYSTEM"] if is_file else ["CODE_CHUNK"]
    # FILE nodes use the dotted module name as display_name (e.g. "myapp.utils")
    # — that's what node.name holds. CODE_CHUNK nodes use the unqualified name.
    display_name = node.name

    additional: dict[str, Any] = {
        "name": node.name,
        "project_name": project_name,
    }
    if node.module_name:
        additional["module"] = node.module_name
    if node.class_name:
        additional["class"] = node.class_name
    if node.is_async:
        additional["async"] = True
    if node.decorators:
        additional["decorators"] = node.decorators

    return {
        "id": node.id,
        "display_name": display_name,
        "type": node.type,
        "code": code,
        "path": node.file_path or "",
        "language": "PYTHON",
        "generator": GENERATOR,
        "loc": loc(code),
        "cyclomatic_complexity": cc(
            code, node.file_path, node.type, _EXECUTABLE_TYPES, "py"
        ),
        "category": category,
        "additional_properties": additional,
    }


def _build_filesystem_nodes(nodes: list[PythonNode]) -> list[dict[str, Any]]:
    """Generate DIRECTORY nodes from unique parent directories of file_paths.

    FILE nodes are already created by the parser, so we only generate parent
    DIRECTORY nodes here (matches the Perl loader's approach).
    """
    fs_nodes: list[dict[str, Any]] = []
    seen_dirs: set[str] = set()

    for node in nodes:
        fp = node.file_path
        if not fp:
            continue
        parts = fp.replace("\\", "/").split("/")
        for i in range(1, len(parts)):
            dir_path = "/".join(parts[:i])
            if dir_path and dir_path not in seen_dirs:
                seen_dirs.add(dir_path)
                fs_nodes.append(
                    {
                        "id": dir_path,
                        "display_name": parts[i - 1],
                        "type": "DIRECTORY",
                        "path": dir_path,
                        "generator": GENERATOR,
                        "category": ["FILE_SYSTEM"],
                    }
                )
    return fs_nodes


def _rel_to_dict(rel: PythonRelationship) -> dict[str, Any]:
    return {
        "from_id": rel.from_node_id,
        "to_id": rel.to_node_id,
        "type": rel.type,
    }
