"""
================================================================================
       Bipartite Graph Pipeline for Eighteenth-Century Subscriber Lists
                            bipartite-viz/pipeline.py
================================================================================
RUN WITH: python3 pipeline.py [--input GRAPHML]

DESCRIPTION:
    Renders the cross-work overlap outputs from a GraphML graph built by
    ../bipartite-graphs/build_graph.py:

        1. overlap_network_viz.py  — chord diagram of cross-work overlap
        2. crossbook_export.py     — CSV of subscribers shared across works

    Paths (and the optional highlighted work) come from pipeline.toml.
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


def run_step(description, cmd):
    print(f"\n{'─' * 60}")
    print(f"  {description}")
    print(f"{'─' * 60}")
    result = subprocess.run(cmd, shell=False, cwd=HERE)
    if result.returncode != 0:
        print(f"\nERROR: Step failed with exit code {result.returncode}")
        sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(
        description="Render bipartite subscriber-work visualizations from GraphML."
    )
    parser.add_argument("--input", metavar="FILE",
                        help="Override the GraphML input path.")
    args = parser.parse_args()

    config = load_config()
    graph = args.input or config["paths"]["graph"]
    highlight = config.get("overlap", {}).get("highlight", "")

    # The chord shows raw shared-subscriber counts (chord width); it can
    # optionally point a manicule at one work via [overlap] highlight.
    network_cmd = ["python3", "overlap_network_viz.py", graph]
    if highlight:
        network_cmd += ["--highlight", highlight]
    run_step("Overlap network", network_cmd)
    run_step("Cross-work subscriber list",
             ["python3", "crossbook_export.py", graph])

    print(f"\nDone. Outputs in: {HERE / 'outputs'}")


if __name__ == "__main__":
    main()
