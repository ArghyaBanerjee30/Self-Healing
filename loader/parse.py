import argparse
import json
from pathlib import Path

from loader.parsers.python.python_parser import PythonParser
from loader.parsers.python.python_to_json import convert


class _NoOpObserver:
    def file_accessed(self, path: str) -> None:
        pass


def parse(input_path: str, project_name: str, output_path: str) -> None:
    file_paths = {str(p) for p in Path(input_path).rglob("*.py")}
    if not file_paths:
        print(f"No .py files found in {input_path}")
        return

    parser = PythonParser(observer=_NoOpObserver())
    nodes, relationships = parser.traverse_directory_tree(
        file_paths, pipeline_id="loader", base_path=input_path
    )
    result = convert(nodes, relationships, project_name=project_name)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(f"Parsed {len(file_paths)} files → {len(result['nodes'])} nodes, {len(result['edges'])} edges")
    print(f"Written to {output_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Parse a Python repo into nodes/edges JSON")
    ap.add_argument("--input", required=True, help="Path to the repo directory")
    ap.add_argument("--output", default="loader/output/graph.json", help="Output JSON path")
    ap.add_argument("--project-name", default="", help="Project label")
    args = ap.parse_args()

    parse(args.input, args.project_name, args.output)
