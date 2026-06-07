def build_display_codes(nodes: list) -> dict[str, str]:
    """
    Return a map of node_id -> deduplicated code for parent nodes whose code
    contains child code verbatim. Each child's code is replaced with
    '{replacing code snippet for <child_id>}'. Only parents that change are included.

    Replacements are applied longest-first to avoid partial substitutions when
    one child's code could be a substring of another's.
    """
    children_by_parent: dict[str, list] = {}
    for n in nodes:
        if n.parent_id:
            children_by_parent.setdefault(n.parent_id, []).append(n)

    node_map = {n.id: n for n in nodes}
    display_codes: dict[str, str] = {}

    # for parent_id, children in children_by_parent.items():
    #     parent = node_map.get(parent_id)
    #     if not parent or not parent.code:
    #         continue
    #     code = parent.code
    #     for child in sorted(children, key=lambda c: len(c.code or ""), reverse=True):
    #         if child.code and child.code in code:
    #             code = code.replace(
    #                 child.code,
    #                 f"{{replacing code snippet for {child.id}}}",
    #                 1,
    #             )
    #     if code != parent.code:
    #         display_codes[parent_id] = code

    return display_codes
