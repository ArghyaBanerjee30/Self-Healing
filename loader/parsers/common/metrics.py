import lizard


def loc(code: str) -> int:
    if not code:
        return 0
    return sum(1 for line in code.splitlines() if line.strip())


def cc(
    code: str,
    file_path: str,
    node_type: str,
    executable_types: frozenset[str],
    fallback_ext: str = "unknown",
) -> int:
    if not code or node_type not in executable_types:
        return 1
    try:
        analysis = lizard.analyze_file.analyze_source_code(
            file_path or f"unknown.{fallback_ext}", code
        )
        if analysis and analysis.function_list:
            return max(1, max(f.cyclomatic_complexity for f in analysis.function_list))
    except Exception:
        pass
    return 1
