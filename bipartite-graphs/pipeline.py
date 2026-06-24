"""
================================================================================
       Bipartite Graph Pipeline for Eighteenth-Century Subscriber Lists
                              pipeline.py
================================================================================
RUN WITH: python3 pipeline.py [--input FILE]

DESCRIPTION:
    Takes a deduplicated subscriber CSV (from the entity-resolution
    pipeline), builds the bipartite subscriber-work graph, then hands
    off to ../bipartite-viz to render the visualizations:

        1. build_graph.py          — construct the GraphML file
        2. ../bipartite-viz        — chord overlap network + cross-work CSV

    Paths come from pipeline.toml.
--------------------------------------------------------------------------------
LICENSE:
    MIT License
    Copyright (c) 2026 Lawrence Evalyn
================================================================================
"""

import argparse
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


HERE = Path(__file__).parent


def load_config():
    config_path = HERE / "pipeline.toml"
    if not config_path.exists():
        print(f"ERROR: {config_path} not found.")
        sys.exit(1)
    with open(config_path, "rb") as f:
        return tomllib.load(f)


def run_step(description, cmd, cwd=HERE):
    print(f"\n{'─' * 60}")
    print(f"  {description}")
    print(f"{'─' * 60}")
    result = subprocess.run(cmd, shell=False, cwd=cwd)
    if result.returncode != 0:
        print(f"\nERROR: Step failed with exit code {result.returncode}")
        sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(
        description="Bipartite graph pipeline: deduplicated CSV → graph + viz."
    )
    parser.add_argument("--input", metavar="FILE",
                        help="Override the deduplicated CSV input path.")
    parser.add_argument("--output", metavar="FILE",
                        help="Override the GraphML output path.")
    args = parser.parse_args()

    config = load_config()
    paths = config["paths"]

    deduplicated = args.input or paths["deduplicated"]
    graph = args.output or paths["graph"]

    run_step(
        "Build graph",
        ["python3", "build_graph.py", deduplicated, "--output", graph],
        cwd=HERE,
    )

    # Hand off rendering to the sibling bipartite-viz pipeline, passing the
    # graph as an absolute path so it resolves regardless of cwd.
    viz_dir = HERE.parent / "bipartite-viz"
    graph_abs = (HERE / graph).resolve()
    run_step(
        "Render visualizations (bipartite-viz)",
        ["python3", "pipeline.py", "--input", str(graph_abs)],
        cwd=viz_dir,
    )

    print(f"\nDone. Graph at: {graph}")


if __name__ == "__main__":
    main()
