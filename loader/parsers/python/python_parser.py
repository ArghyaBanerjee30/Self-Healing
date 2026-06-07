# © 2025 Thoughtworks, Inc. | Thoughtworks Pre-Existing Intellectual Property, Thoughtworks Tools | Patent Pending | See License file for permissions.

import logging
import os
import warnings
from pathlib import Path
from typing import Protocol

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from loader.parsers.python.python_models import (
    PythonNode,
    PythonNodeType,
    PythonRelationship,
    PythonRelationshipType,
)

logger = logging.getLogger(__name__)

UTF_8 = "utf-8"
FILE_EXTENSIONS = (".py",)

# Type names that should NOT become DEPENDS_ON edges (built-ins / typing aliases).
_NON_USER_TYPE_NAMES = frozenset(
    {
        # Primitive builtins
        "int", "str", "float", "bool", "bytes", "bytearray", "complex",
        "None", "object", "Self", "type", "memoryview",
        # Generic builtins (PEP 585)
        "list", "dict", "tuple", "set", "frozenset",
        # typing module surface
        "Any", "Optional", "Union", "List", "Dict", "Tuple", "Set", "FrozenSet",
        "Callable", "Iterable", "Iterator", "Generator", "AsyncIterable",
        "AsyncIterator", "AsyncGenerator", "Awaitable", "Coroutine",
        "Type", "ClassVar", "Final", "Literal", "Annotated", "Protocol",
        "TypeVar", "Generic", "NewType", "Mapping", "MutableMapping",
        "Sequence", "MutableSequence", "MappingView", "KeysView", "ItemsView",
        "ValuesView", "TypedDict", "NamedTuple", "Hashable", "Sized",
        "Container", "Collection", "Reversible", "AbstractSet", "MutableSet",
        # Module names that commonly prefix a type expression
        "typing", "typing_extensions", "collections", "abc",
    }
)


class StageObserver(Protocol):
    def file_accessed(self, path: str) -> None: ...


# ── Grammar loader ──────────────────────────────────────────────────────────


def _load_python_language() -> Language:
    """Load the Python tree-sitter grammar from the PyPI package."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return Language(tree_sitter_python.language())


# ── Module-name resolution ──────────────────────────────────────────────────


def _module_name_for(file_path: str, base_path: str | None) -> str:
    """Compute the dotted module name for a Python source file.

    Algorithm:
      1. If base_path is given, take the file path relative to base_path.
      2. Strip the `.py` extension.
      3. If the basename is `__init__`, drop it (so the module name is the
         containing package's dotted path).
      4. Replace `/` with `.`.

    If base_path is not given, fall back to the file's basename without
    extension — useful for standalone tests that don't establish a root.
    """
    abs_file = os.path.abspath(file_path)
    if base_path:
        abs_base = os.path.abspath(base_path)
        try:
            rel = os.path.relpath(abs_file, abs_base)
        except ValueError:
            rel = os.path.basename(abs_file)
    else:
        rel = os.path.basename(abs_file)

    rel = rel.replace(os.sep, "/")
    if rel.endswith(".py"):
        rel = rel[:-3]
    parts = [p for p in rel.split("/") if p and p != "."]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_relative_import(
    current_module: str,
    level: int,
    suffix: str | None,
) -> str | None:
    """Resolve `from . import x` / `from .pkg import x` to an absolute dotted name.

    `current_module` is the importing file's dotted name.
    `level` is the number of leading dots (1 = same package, 2 = parent, ...).
    `suffix` is the dotted path after the leading dots, or None.
    """
    parts = current_module.split(".") if current_module else []
    # `level` dots means "go up `level - 1` packages from the current package".
    # The current module's own name is part[-1]; its package is parts[:-1].
    # `from . import x` (level=1) → package = parts[:-1]; resolved = "<package>.x"
    # `from ..pkg import y` (level=2) → package = parts[:-2]; resolved = "<package>.pkg.y"
    if level > len(parts):
        return None
    package_parts = parts[: len(parts) - level]
    if suffix:
        package_parts = package_parts + suffix.split(".")
    return ".".join(package_parts) if package_parts else None


# ── Public parser class ─────────────────────────────────────────────────────


class PythonParser:
    def __init__(self, observer: StageObserver):
        self.observer = observer

    def traverse_directory_tree(
        self,
        file_paths: set[str],
        pipeline_id: str,
        base_path: str | None = None,
    ) -> tuple[list[PythonNode], list[PythonRelationship]]:
        """
        Parse all Python files and return intermediate nodes and relationships.

        Args:
            file_paths: Set of absolute file paths to parse.
            pipeline_id: Unique identifier for this ingestion batch.
            base_path: Source root used to compute dotted module names.
                       If omitted, module names fall back to the file basename.

        Returns:
            Tuple of (nodes, relationships).
        """
        nodes: list[PythonNode] = []
        relationships: list[PythonRelationship] = []

        for file_path in sorted(file_paths):
            if not file_path.endswith(FILE_EXTENSIONS):
                continue
            try:
                self.observer.file_accessed(file_path)
                file_nodes, file_rels = self._parse_file(
                    file_path, pipeline_id, base_path
                )
                nodes.extend(file_nodes)
                relationships.extend(file_rels)
            except Exception as e:
                logger.warning(f"Failed to parse {file_path}: {e}")

        relationships = _resolve_cross_file_refs(nodes, relationships)
        return nodes, relationships

    def _parse_file(
        self,
        file_path: str,
        pipeline_id: str,
        base_path: str | None,
    ) -> tuple[list[PythonNode], list[PythonRelationship]]:
        source = Path(file_path).read_bytes()

        language = _load_python_language()
        parser = Parser(language)
        tree = parser.parse(source)

        # Two-tier error logging.
        structural_errors = sum(
            1 for c in tree.root_node.children if c.type == "ERROR"
        )
        if structural_errors > 0:
            logger.warning(
                f"Structural parse errors in {file_path} — "
                f"{structural_errors} top-level error node(s), extraction may be incomplete"
            )
        elif tree.root_node.has_error:
            logger.debug(
                f"Internal parse errors in {file_path} — structural nodes extracted OK"
            )

        module_name = _module_name_for(file_path, base_path)
        visitor = PythonVisitor(source, file_path, pipeline_id, module_name)
        visitor.visit_module(tree.root_node)
        return visitor.nodes, visitor.relationships


# ── Visitor implementation ──────────────────────────────────────────────────


class PythonVisitor:
    def __init__(
        self, source: bytes, file_path: str, pipeline_id: str, module_name: str
    ):
        self.source = source
        self.file_path = file_path
        self.pipeline_id = pipeline_id
        self.module_name = module_name
        self.nodes: list[PythonNode] = []
        self.relationships: list[PythonRelationship] = []

        # Scope tracking: parent_id determination uses _scope_stack.
        # _in_function flips True when we enter a function body; further
        # function/class definitions are then NOT elevated.
        self._scope_stack: list[PythonNode] = []
        self._in_function: bool = False
        # Active class context for `self.foo()` call resolution.
        self._class_stack: list[PythonNode] = []
        # Module aliases — `import x` / `import x as y` / `import x.y as z`:
        # the local name binds to a *module*. We index methods/functions by
        # module_name, so `alias.method()` resolves with owner = module name.
        self._module_aliases: dict[str, str] = {}
        # `from m import n` — `n` is a *name* (class or function) inside m.
        # Records alias → owning module so `n()` can resolve as either:
        #   - module-level function:   fn_by_owner[(m, n)]
        #   - constructor:             classes_by_name[n].__init__
        # And `n.method()` resolves with owner = n (treated as class).
        self._from_imports: dict[str, str] = {}

        # Create FILE node.
        self.file_node = PythonNode(
            id=f"{file_path}::FILE",
            name=module_name,
            type=PythonNodeType.FILE.value,
            code="",  # populated at end of visit_module
            pipeline_id=pipeline_id,
            file_path=file_path,
            start_line=1,
            end_line=1,
            module_name=module_name,
        )
        self.nodes.append(self.file_node)
        self._scope_stack.append(self.file_node)

    # ── Entry point ────────────────────────────────────────────────────────

    def visit_module(self, node: Node):
        """Root visit. Records the full module text as FILE.code."""
        self.file_node.code = self._extract_text(node)
        self.file_node.end_line = node.end_point[0] + 1
        for child in node.named_children:
            self._visit(child)

    # ── Dispatch ───────────────────────────────────────────────────────────

    def _visit(self, node: Node):
        t = node.type
        if t == "class_definition":
            self._visit_class(node, decorators=[])
        elif t == "function_definition":
            self._visit_function(node, decorators=[])
        elif t == "decorated_definition":
            self._visit_decorated(node)
        elif t == "import_statement":
            self._visit_import_statement(node)
        elif t == "import_from_statement":
            self._visit_import_from_statement(node)
        elif t == "expression_statement":
            self._visit_expression_statement(node)
        elif t in (
            "if_statement",
            "for_statement",
            "while_statement",
            "with_statement",
            "try_statement",
            "match_statement",
        ):
            # Module-level control flow — recurse so we find nested defs/imports.
            for child in node.named_children:
                self._visit(child)
        # Everything else at module scope is text already captured in the
        # FILE.code; no further action.

    # ── Class / function ───────────────────────────────────────────────────

    def _visit_decorated(self, node: Node):
        """Handle `@decorator def foo(): ...` and `@decorator class Foo: ...`.

        The decorated_definition wraps the inner def/class. We harvest the
        decorator names and pass them through, but the captured `code` for
        the inner node starts at the decorated_definition's start_byte so
        the decorators are included.
        """
        decorators: list[str] = []
        inner: Node | None = None
        for child in node.children:
            if child.type == "decorator":
                # `@name(args)` or `@name`
                decorators.append(self._decorator_name(child))
            elif child.type in ("function_definition", "class_definition"):
                inner = child
        if inner is None:
            return
        if inner.type == "class_definition":
            self._visit_class(inner, decorators=decorators, outer_node=node)
        else:
            self._visit_function(inner, decorators=decorators, outer_node=node)

    def _visit_class(
        self,
        node: Node,
        decorators: list[str],
        outer_node: Node | None = None,
    ):
        if self._in_function:
            # Don't elevate classes defined inside function bodies — their
            # text is captured in the enclosing FUNCTION's code.
            return

        text_node = outer_node or node
        name = self._first_named_child_text(node, "identifier")
        if not name:
            logger.debug(f"Could not extract class name in {self.file_path}")
            return

        bases = self._extract_bases(node)
        parent_id = self._current_scope_id()
        class_node = PythonNode(
            id=self._make_class_id(name),
            name=name,
            type=PythonNodeType.CLASS.value,
            code=self._extract_text(text_node),
            pipeline_id=self.pipeline_id,
            file_path=self.file_path,
            start_line=text_node.start_point[0] + 1,
            end_line=text_node.end_point[0] + 1,
            parent_id=parent_id,
            module_name=self.module_name,
            bases=bases,
            decorators=decorators,
        )
        self.nodes.append(class_node)

        # MADE_OF edge from enclosing scope.
        if parent_id:
            self.relationships.append(
                PythonRelationship(
                    from_node_id=parent_id,
                    to_node_id=class_node.id,
                    type=PythonRelationshipType.MADE_OF.value,
                )
            )

        # EXTENDS edges for each base class.
        for base in bases:
            self.relationships.append(
                PythonRelationship(
                    from_node_id=class_node.id,
                    to_node_id=f"UNRESOLVED:CLASS:{base}",
                    type=PythonRelationshipType.EXTENDS.value,
                )
            )

        # Class-body field annotations → DEPENDS_ON edges from CLASS.
        block = self._find_child(node, "block")
        if block is not None:
            self._collect_class_field_dependencies(block, class_node)

        # Recurse into the class body with this class on the scope stack.
        self._scope_stack.append(class_node)
        self._class_stack.append(class_node)
        if block is not None:
            for child in block.named_children:
                self._visit(child)
        self._class_stack.pop()
        self._scope_stack.pop()

    def _visit_function(
        self,
        node: Node,
        decorators: list[str],
        outer_node: Node | None = None,
    ):
        if self._in_function:
            # Nested defs are NOT elevated — captured in outer FUNCTION's code.
            return

        text_node = outer_node or node
        name = self._first_named_child_text(node, "identifier")
        if not name:
            logger.debug(f"Could not extract function name in {self.file_path}")
            return

        is_async = self._is_async_def(node)
        parent_id = self._current_scope_id()
        class_context = self._class_stack[-1].name if self._class_stack else None

        func_node = PythonNode(
            id=self._make_function_id(name, class_context),
            name=name,
            type=PythonNodeType.FUNCTION.value,
            code=self._extract_text(text_node),
            pipeline_id=self.pipeline_id,
            file_path=self.file_path,
            start_line=text_node.start_point[0] + 1,
            end_line=text_node.end_point[0] + 1,
            parent_id=parent_id,
            module_name=self.module_name,
            class_name=class_context,
            is_async=is_async,
            decorators=decorators,
        )
        self.nodes.append(func_node)

        # MADE_OF from enclosing scope (file or class).
        if parent_id:
            self.relationships.append(
                PythonRelationship(
                    from_node_id=parent_id,
                    to_node_id=func_node.id,
                    type=PythonRelationshipType.MADE_OF.value,
                )
            )

        # Type-hint DEPENDS_ON edges from parameters and return annotation.
        self._collect_function_signature_dependencies(node, func_node)

        # Walk the body for calls. `_in_function = True` prevents inner def/class
        # elevation.
        body = self._find_child(node, "block")
        if body is not None:
            prev = self._in_function
            self._in_function = True
            self._scope_stack.append(func_node)
            self._collect_calls(body, func_node)
            self._scope_stack.pop()
            self._in_function = prev

    # ── Imports ────────────────────────────────────────────────────────────

    def _visit_import_statement(self, node: Node):
        """`import x`, `import x.y`, `import x as y`, `import x.y as z`."""
        for child in node.named_children:
            if child.type == "dotted_name":
                module = self._extract_text(child).strip()
                self._record_import(module)
                # `import a.b.c` binds the *top-level* name `a` to module `a`.
                # Attribute access `a.b.c.method` would need deeper handling,
                # but the common case `import a` (no dots) is straightforward.
                self._module_aliases[module.split(".")[0]] = module.split(".")[0]
            elif child.type == "aliased_import":
                inner = child.named_children
                module: str | None = None
                alias: str | None = None
                for sub in inner:
                    if sub.type == "dotted_name":
                        module = self._extract_text(sub).strip()
                    elif sub.type == "identifier":
                        alias = self._extract_text(sub).strip()
                if module and alias:
                    self._record_import(module)
                    self._module_aliases[alias] = module

    def _visit_import_from_statement(self, node: Node):
        """`from x import a, b as c` and `from . import a`."""
        module: str | None = None
        relative_level = 0
        relative_suffix: str | None = None
        names: list[tuple[str, str]] = []  # (imported_name, alias)
        seen_module = False  # The first dotted_name/relative_import is the module

        for child in node.named_children:
            if not seen_module:
                if child.type == "dotted_name":
                    module = self._extract_text(child).strip()
                    seen_module = True
                    continue
                if child.type == "relative_import":
                    # Parse: import_prefix (dots) + optional dotted_name
                    level, suffix = self._parse_relative_import(child)
                    relative_level = level
                    relative_suffix = suffix
                    seen_module = True
                    continue
            # After the module, every dotted_name / aliased_import is an
            # imported name.
            if child.type == "dotted_name":
                name = self._extract_text(child).strip()
                names.append((name, name))
            elif child.type == "aliased_import":
                src_name = None
                alias = None
                for sub in child.named_children:
                    if sub.type == "dotted_name" and src_name is None:
                        src_name = self._extract_text(sub).strip()
                    elif sub.type == "identifier":
                        alias = self._extract_text(sub).strip()
                if src_name and alias:
                    names.append((src_name, alias))

        # Resolve module target.
        if relative_level > 0:
            module = _resolve_relative_import(
                self.module_name, relative_level, relative_suffix
            )
        if not module:
            return

        self._record_import(module)
        for imported, alias in names:
            # The alias is a *name* (class or function) inside `module`.
            # Also stash it as a module alias under the assumption that the
            # imported name might be a *submodule* of `module` (e.g.
            # `from pkg import helpers` where helpers is a submodule).
            self._from_imports[alias] = module
            self._module_aliases[alias] = f"{module}.{imported}"
            # Additionally emit a candidate IMPORTS edge to `module.imported`.
            # If that's a real submodule, the resolver keeps the edge; if it's
            # just a name (class/function) in `module`, the edge drops since
            # no FILE node will match.
            submodule_candidate = f"{module}.{imported}"
            if submodule_candidate not in self.file_node.imports:
                self.file_node.imports.append(submodule_candidate)
            self.relationships.append(
                PythonRelationship(
                    from_node_id=self.file_node.id,
                    to_node_id=f"UNRESOLVED:FILE:{submodule_candidate}",
                    type=PythonRelationshipType.IMPORTS.value,
                )
            )

    def _record_import(self, module: str):
        """Emit an IMPORTS edge from the current FILE to the given module."""
        if not module:
            return
        if module not in self.file_node.imports:
            self.file_node.imports.append(module)
        self.relationships.append(
            PythonRelationship(
                from_node_id=self.file_node.id,
                to_node_id=f"UNRESOLVED:FILE:{module}",
                type=PythonRelationshipType.IMPORTS.value,
            )
        )

    def _parse_relative_import(self, node: Node) -> tuple[int, str | None]:
        """Return (level, suffix) for a `relative_import` node.

        `relative_import` looks like:
          relative_import
            import_prefix     # ".", "..", "..."
            dotted_name?      # optional package path after the dots

        We count dots from the import_prefix text.
        """
        level = 0
        suffix: str | None = None
        for child in node.children:
            if child.type == "import_prefix":
                level = len(self._extract_text(child))
            elif child.type == "dotted_name":
                suffix = self._extract_text(child).strip()
        return level, suffix

    # ── Top-level expressions / annotated assignments ──────────────────────

    def _visit_expression_statement(self, node: Node):
        """At module scope, an expression_statement may contain an annotated
        assignment with a type hint we want for DEPENDS_ON (but only when the
        enclosing scope is a class — module-level globals don't emit edges).
        """
        # No edges from module-level expression statements in standard core.
        # We still recurse so any nested calls inside complex expressions
        # are NOT lost — but calls outside functions aren't emitted as edges.
        return

    # ── Calls (inside a function body) ─────────────────────────────────────

    def _collect_calls(self, node: Node, caller: PythonNode):
        """Recursively walk a function body, emitting CALLS edges.

        Lambdas and nested defs are captured textually in the outer function's
        code; we don't recurse into nested function bodies to avoid emitting
        calls from the wrong caller.
        """
        for child in node.children:
            if child.type == "call":
                self._handle_call(child, caller)
            elif child.type in ("function_definition", "decorated_definition"):
                # Nested def — its body's calls belong to it, not to `caller`.
                # But since nested defs are NOT elevated as nodes, the calls
                # inside them would have nowhere to attach. Conservative
                # decision: skip — calls in nested defs are not extracted.
                continue
            elif child.type == "lambda":
                # Same reasoning as nested def.
                continue
            else:
                self._collect_calls(child, caller)

    def _handle_call(self, node: Node, caller: PythonNode):
        """Emit a CALLS edge for a `call` AST node."""
        # The function being called is the first non-arglist child.
        callee = None
        for child in node.children:
            if child.type != "argument_list":
                callee = child
                break
        if callee is None:
            return
        target = self._resolve_call_target(callee)
        if target is None:
            return
        self.relationships.append(
            PythonRelationship(
                from_node_id=caller.id,
                to_node_id=target,
                type=PythonRelationshipType.CALLS.value,
            )
        )

    def _resolve_call_target(self, callee: Node) -> str | None:
        """Map a callee AST sub-tree to an UNRESOLVED placeholder string."""
        t = callee.type

        if t == "identifier":
            name = self._extract_text(callee)
            # `from x import y` then `y(...)`: y could be a function in module
            # x OR a class imported into the current scope. Emit CALLABLE so
            # the resolver tries function first, then constructor.
            if name in self._from_imports:
                owner = self._from_imports[name]
                return f"UNRESOLVED:CALLABLE:{owner}::{name}"
            # Plain bare name. Could be a function in this module OR a class
            # being constructed. CALLABLE lets the resolver try both.
            return f"UNRESOLVED:CALLABLE:{self.module_name}::{name}"

        if t == "attribute":
            # `a.b.c(...)`. Walk the attribute chain to a base identifier.
            chain = self._collect_attribute_chain(callee)
            if not chain:
                return None
            head, *rest = chain
            if not rest:
                return None
            method = rest[-1]
            # self.method(...) — resolve against current class.
            if head == "self":
                if not self._class_stack:
                    return f"UNRESOLVED:FUNCTION:{method}"
                cls_name = self._class_stack[-1].name
                return f"UNRESOLVED:FUNCTION:{cls_name}::{method}"
            # `from m import n; n.method()` — n is a class/function name.
            if head in self._from_imports:
                return f"UNRESOLVED:FUNCTION:{head}::{method}"
            # `import m; m.func()` — head is a module alias.
            if head in self._module_aliases:
                owner = self._module_aliases[head]
                return f"UNRESOLVED:FUNCTION:{owner}::{method}"
            # Unknown receiver. Capitalized heuristic → likely class.
            if len(rest) == 1 and head[:1].isupper():
                return f"UNRESOLVED:FUNCTION:{head}::{method}"
            # Fall back to a bare method-name lookup (won't resolve unless we
            # add explicit support, mirroring Perl's "unresolved" behavior).
            return f"UNRESOLVED:FUNCTION:{method}"

        # Subscript like `xs[0].method()` calls — handled via attribute path.
        # Anything else (lambda call, parenthesized expression, etc.) is left
        # unresolved.
        return None

    def _collect_attribute_chain(self, node: Node) -> list[str]:
        """Flatten `a.b.c` into ["a", "b", "c"]."""
        # The attribute node has children: object . attribute
        # The object can itself be an attribute, identifier, or other.
        if node.type == "identifier":
            return [self._extract_text(node)]
        if node.type == "attribute":
            obj = node.child_by_field_name("object")
            attr = node.child_by_field_name("attribute")
            if obj is None or attr is None:
                # Fall back to positional: first named is object, last is attribute name
                kids = node.named_children
                if len(kids) >= 2:
                    obj = kids[0]
                    attr = kids[-1]
            if obj is None or attr is None:
                return []
            base = self._collect_attribute_chain(obj)
            if not base:
                return []
            return base + [self._extract_text(attr)]
        # Not a chain we can flatten (call result, subscript, etc.).
        return []

    # ── Type-hint DEPENDS_ON collection ────────────────────────────────────

    def _collect_function_signature_dependencies(
        self, fn_node: Node, func: PythonNode
    ):
        """Emit DEPENDS_ON edges for parameter and return type annotations."""
        params = self._find_child(fn_node, "parameters")
        if params is not None:
            for p in params.named_children:
                if p.type in ("typed_parameter", "typed_default_parameter"):
                    type_child = self._find_child(p, "type")
                    if type_child is not None:
                        self._emit_dependencies_from_type(type_child, func)
        # Return type annotation lives as a `type` child of function_definition.
        ret = self._find_child(fn_node, "type")
        if ret is not None:
            self._emit_dependencies_from_type(ret, func)

    def _collect_class_field_dependencies(
        self, block: Node, klass: PythonNode
    ):
        """Class-body field annotations: `name: User` and `name: User = ...`."""
        for stmt in block.named_children:
            if stmt.type != "expression_statement":
                continue
            for child in stmt.named_children:
                if child.type == "assignment":
                    # Form: left : type [= value]
                    type_child = child.child_by_field_name("type")
                    if type_child is None:
                        # Fall back to scanning for a `type` child.
                        type_child = self._find_child(child, "type")
                    if type_child is not None:
                        self._emit_dependencies_from_type(type_child, klass)

    def _emit_dependencies_from_type(self, type_node: Node, source: PythonNode):
        """Walk a `type` annotation tree and emit DEPENDS_ON edges for each
        user-named class reference, deduplicating per source."""
        names = self._extract_type_names(type_node)
        already = set(source.type_dependencies)
        for n in names:
            if n in already:
                continue
            already.add(n)
            source.type_dependencies.append(n)
            self.relationships.append(
                PythonRelationship(
                    from_node_id=source.id,
                    to_node_id=f"UNRESOLVED:CLASS:{n}",
                    type=PythonRelationshipType.DEPENDS_ON.value,
                )
            )

    def _extract_type_names(self, node: Node) -> list[str]:
        """Walk an annotation node and collect user-defined class names.

        Handles: identifiers, attribute access (uses the rightmost segment),
        subscripts (recurses into args), strings (forward references), and
        binary `|` unions. Skips primitive / typing-module names.
        """
        names: list[str] = []

        def walk(n: Node):
            t = n.type
            if t == "identifier":
                name = self._extract_text(n)
                if name not in _NON_USER_TYPE_NAMES:
                    names.append(name)
                return
            if t == "string":
                # Forward reference: "User" — strip quotes & whitespace.
                raw = self._extract_text(n).strip()
                if raw[:1] in ("'", '"') and raw[-1:] in ("'", '"'):
                    raw = raw[1:-1].strip()
                if raw and raw not in _NON_USER_TYPE_NAMES:
                    names.append(raw)
                return
            if t == "attribute":
                # typing.Optional, foo.User, etc. — use rightmost identifier.
                attr = n.child_by_field_name("attribute")
                if attr is None:
                    kids = n.named_children
                    attr = kids[-1] if kids else None
                if attr is not None:
                    walk(attr)
                return
            if t == "subscript":
                # value[args] — walk value (likely typing alias, gets filtered)
                # and walk the slice / generic arguments.
                for c in n.named_children:
                    walk(c)
                return
            # Recurse into anything else (binary_operator for X | None, tuple, etc.)
            for c in n.named_children:
                walk(c)

        walk(node)
        # Preserve order, deduplicate.
        seen = set()
        out = []
        for n in names:
            if n in seen:
                continue
            seen.add(n)
            out.append(n)
        return out

    # ── Helpers ────────────────────────────────────────────────────────────

    def _extract_text(self, node: Node) -> str:
        return self.source[node.start_byte : node.end_byte].decode(
            UTF_8, errors="replace"
        )

    def _first_named_child_text(self, node: Node, kind: str) -> str | None:
        for c in node.named_children:
            if c.type == kind:
                return self._extract_text(c)
        return None

    def _find_child(self, node: Node, kind: str) -> Node | None:
        for c in node.children:
            if c.type == kind:
                return c
        return None

    def _is_async_def(self, fn_node: Node) -> bool:
        # async def: first unnamed child is the `async` keyword.
        for c in fn_node.children:
            if c.type == "async":
                return True
            if c.type == "def":
                return False
        return False

    def _extract_bases(self, class_node: Node) -> list[str]:
        """Get the names of base classes from `class Foo(A, B, kw=...):`."""
        bases: list[str] = []
        arglist = self._find_child(class_node, "argument_list")
        if arglist is None:
            return bases
        for child in arglist.named_children:
            t = child.type
            if t == "identifier":
                bases.append(self._extract_text(child))
            elif t == "attribute":
                # e.g. `module.Class` — take the rightmost name.
                attr = child.child_by_field_name("attribute")
                if attr is None:
                    kids = child.named_children
                    attr = kids[-1] if kids else None
                if attr is not None:
                    bases.append(self._extract_text(attr))
            elif t in ("keyword_argument",):
                # `metaclass=ABCMeta`, `total=False` — skip.
                continue
            elif t == "subscript":
                # e.g. `Generic[T]` — take leftmost identifier (skip generic args).
                kids = child.named_children
                if kids and kids[0].type == "identifier":
                    nm = self._extract_text(kids[0])
                    if nm not in _NON_USER_TYPE_NAMES:
                        bases.append(nm)
        return bases

    def _decorator_name(self, decorator_node: Node) -> str:
        """Extract a friendly name from an `@decorator` node."""
        # decorator: @ expression
        for c in decorator_node.named_children:
            if c.type == "identifier":
                return self._extract_text(c)
            if c.type == "attribute":
                return self._extract_text(c)
            if c.type == "call":
                # @app.route(...) — take the callee text.
                fn = None
                for cc in c.children:
                    if cc.type != "argument_list":
                        fn = cc
                        break
                if fn is not None:
                    return self._extract_text(fn)
        return self._extract_text(decorator_node).lstrip("@").strip()

    def _current_scope_id(self) -> str | None:
        return self._scope_stack[-1].id if self._scope_stack else None

    def _make_class_id(self, name: str) -> str:
        parent = "::".join(c.name for c in self._class_stack) if self._class_stack else ""
        suffix = f"{parent}::{name}" if parent else name
        return f"{self.file_path}::CLASS::{suffix}"

    def _make_function_id(self, name: str, class_context: str | None) -> str:
        owner = class_context or self.module_name or "<module>"
        return f"{self.file_path}::FUNCTION::{owner}::{name}"


# ── Cross-file reference resolution ─────────────────────────────────────────


def _resolve_cross_file_refs(
    nodes: list[PythonNode],
    relationships: list[PythonRelationship],
) -> list[PythonRelationship]:
    """Resolve UNRESOLVED placeholders against the full batch of nodes.

    Placeholder formats this resolver handles:
      UNRESOLVED:FILE:<dotted_module_name>
      UNRESOLVED:CLASS:<class_name>
      UNRESOLVED:FUNCTION:<func_name>
      UNRESOLVED:FUNCTION:<owner>::<func_name>
          where <owner> is either a class name or a dotted module name.
      UNRESOLVED:CALLABLE:<owner>::<name>
          where <owner> is the calling module and <name> can be a function
          or a class; resolves to the function if one exists, otherwise to
          the class's __init__, otherwise to the class node itself.
    """
    # Index nodes by (type, name) — names are case-sensitive for Python.
    by_type_name: dict[tuple[str, str], PythonNode] = {}
    # Functions indexed by (owner, name): owner = class name or module name.
    fn_by_owner: dict[tuple[str, str], PythonNode] = {}
    # Classes indexed by name.
    classes_by_name: dict[str, PythonNode] = {}
    # Files indexed by dotted module name.
    files_by_module: dict[str, PythonNode] = {}

    for n in nodes:
        by_type_name[(n.type, n.name)] = n
        if n.type == PythonNodeType.FUNCTION.value:
            owner = n.class_name or n.module_name
            if owner:
                fn_by_owner[(owner, n.name)] = n
        elif n.type == PythonNodeType.CLASS.value:
            classes_by_name[n.name] = n
        elif n.type == PythonNodeType.FILE.value:
            files_by_module[n.name] = n

    resolved: list[PythonRelationship] = []
    for rel in relationships:
        if not rel.to_node_id.startswith("UNRESOLVED:"):
            resolved.append(rel)
            continue
        body = rel.to_node_id[len("UNRESOLVED:"):]
        # type and rest are separated by the first single colon (not ::).
        # Find the first ":" that is not part of "::".
        idx = _first_single_colon(body)
        if idx < 0:
            continue
        node_type = body[:idx]
        rest = body[idx + 1 :]
        target = _resolve_one(
            node_type, rest, files_by_module, classes_by_name, fn_by_owner
        )
        if target is not None:
            resolved.append(
                PythonRelationship(
                    from_node_id=rel.from_node_id,
                    to_node_id=target.id,
                    type=rel.type,
                )
            )
        # else: drop unresolved edge.

    return resolved


def _first_single_colon(s: str) -> int:
    """Find the index of the first ':' that is NOT followed by another ':'."""
    i = 0
    n = len(s)
    while i < n:
        if s[i] == ":":
            if i + 1 < n and s[i + 1] == ":":
                # Part of "::" — skip both characters.
                i += 2
                continue
            return i
        i += 1
    return -1


def _resolve_one(
    node_type: str,
    rest: str,
    files_by_module: dict[str, PythonNode],
    classes_by_name: dict[str, PythonNode],
    fn_by_owner: dict[tuple[str, str], PythonNode],
) -> PythonNode | None:
    if node_type == "FILE":
        return files_by_module.get(rest)
    if node_type == "CLASS":
        return classes_by_name.get(rest)
    if node_type == "FUNCTION":
        if "::" in rest:
            owner, name = rest.rsplit("::", 1)
            # Try exact (class or module).
            t = fn_by_owner.get((owner, name))
            if t is not None:
                return t
            # Try bare name.
            return None  # bare-name fallback only when the placeholder asked for it
        # Bare function name lookup — search any owner with this name.
        # Match Perl's "unresolved bare-method" semantics: prefer no resolution
        # to avoid linking to an arbitrary same-name function in the batch.
        # We still try classes_by_name as a last resort (in case someone calls
        # a class as a constructor with no owner).
        return None
    if node_type == "CALLABLE":
        # Module-qualified callable: try function first, then class __init__,
        # then class itself.
        if "::" not in rest:
            return None
        owner, name = rest.rsplit("::", 1)
        t = fn_by_owner.get((owner, name))
        if t is not None:
            return t
        # Constructor fallback: look up class by short name.
        cls = classes_by_name.get(name)
        if cls is not None:
            init = fn_by_owner.get((name, "__init__"))
            return init or cls
        return None
    return None
