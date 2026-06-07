# © 2025 Thoughtworks, Inc. | Thoughtworks Pre-Existing Intellectual Property, Thoughtworks Tools | Patent Pending | See License file for permissions.

from dataclasses import dataclass, field
from enum import Enum


class PythonNodeType(Enum):
    FILE = "FILE"
    CLASS = "CLASS"
    FUNCTION = "FUNCTION"


class PythonRelationshipType(Enum):
    MADE_OF = "MADE_OF"
    EXTENDS = "EXTENDS"
    IMPORTS = "IMPORTS"
    DEPENDS_ON = "DEPENDS_ON"
    CALLS = "CALLS"


@dataclass
class PythonNode:
    id: str
    name: str
    type: str  # PythonNodeType value
    code: str  # verbatim source text for this construct
    pipeline_id: str
    file_path: str
    start_line: int
    end_line: int
    parent_id: str | None = None  # id of the enclosing elevated node
    module_name: str | None = None  # dotted module path this node belongs to
    class_name: str | None = None  # enclosing class name (for FUNCTION nodes)
    bases: list[str] = field(default_factory=list)  # parent class names for CLASS nodes
    imports: list[str] = field(default_factory=list)  # imported module dotted names for FILE nodes
    type_dependencies: list[str] = field(default_factory=list)  # class names referenced via type hints
    is_async: bool = False  # True for `async def` FUNCTION nodes
    decorators: list[str] = field(default_factory=list)  # decorator names for CLASS / FUNCTION

    def __hash__(self):
        return hash((self.id, self.name, self.type, self.file_path))

    def __eq__(self, other):
        if not isinstance(other, PythonNode):
            return NotImplemented
        return (
            self.id == other.id
            and self.name == other.name
            and self.type == other.type
            and self.file_path == other.file_path
        )


@dataclass
class PythonRelationship:
    from_node_id: str
    to_node_id: str
    type: str  # PythonRelationshipType value
