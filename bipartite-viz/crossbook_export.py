"""
================================================================================
       Bipartite Graph Pipeline for Eighteenth-Century Subscriber Lists
                            crossbook_export.py
================================================================================
RUN WITH: python3 crossbook_export.py ../bipartite-graphs/outputs/graph.graphml
          python3 crossbook_export.py graph.graphml --output outputs/overlap-namelist.csv

DESCRIPTION:
    Writes the list of subscribers who appear in more than one work,
    sorted by number of works descending. This is a data export, not a
    figure: it is the audience-overlap evidence behind the overlap
    visualizations, in a form you can read and cite directly.

    Columns: person_id, normalized_name, num_works, works.

--------------------------------------------------------------------------------
LICENSE:
    MIT License
    Copyright (c) 2026 Lawrence Evalyn
================================================================================
"""

import argparse
import csv
import sys
from pathlib import Path

import _common


def cross_work_rows(G):
    rows = []
    for sub in _common.subscriber_nodes(G):
        works = sorted({
            G.nodes[w].get("book", "")
            for w in G.neighbors(sub)
            if G.nodes[w]["bipartite"] == 0
        })
        if len(works) >= 2:
            rows.append({
                "person_id": sub,
                "normalized_name": G.nodes[sub].get("normalized_name", ""),
                "num_works": len(works),
                "works": "; ".join(works),
            })
    rows.sort(key=lambda r: (-r["num_works"], r["person_id"]))
    return rows


def write_csv(rows, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["person_id", "normalized_name", "num_works", "works"]
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Saved {output_path} ({len(rows)} cross-work subscribers)")


def main():
    parser = argparse.ArgumentParser(
        description="Export subscribers appearing in more than one work."
    )
    parser.add_argument("input_graphml",
                        help="Path to the GraphML file (from build_graph.py).")
    parser.add_argument("--output", default="outputs/overlap-namelist.csv",
                        help="Output CSV path (default: outputs/overlap-namelist.csv).")
    args = parser.parse_args()

    input_path = Path(args.input_graphml)
    if not input_path.is_file():
        print(f"ERROR: {input_path} is not a file.")
        sys.exit(1)

    G = _common.load_graph(input_path)
    print(f"Loaded graph: {len(_common.work_nodes(G))} works, "
          f"{len(_common.subscriber_nodes(G))} subscribers")
    rows = cross_work_rows(G)
    write_csv(rows, args.output)
    print("Done.")


if __name__ == "__main__":
    main()
