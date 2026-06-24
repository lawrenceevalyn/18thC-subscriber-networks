"""
================================================================================
       Bipartite Graph Pipeline for Eighteenth-Century Subscriber Lists
                              build_graph.py
================================================================================
RUN WITH: python3 build_graph.py outputs/04-parsed.csv
          python3 build_graph.py outputs/04-parsed.csv --output my_graph.graphml

DESCRIPTION:
    Reads the deduplicated subscriber CSV and constructs a bipartite
    NetworkX graph with two kinds of nodes:

        Work nodes: one per unique book. A work may have been published
            in several editions; for this analysis all editions of a
            book collapse into a single work node.
            Attributes: book, author, first_year, last_year.

        Subscriber nodes: one per unique person_id.
            Attributes: normalized_name, node_type.
            After entity resolution, multiple rows may share a
            person_id and collapse into a single node.

    Edges connect a subscriber to a work. Edges are attribute-free: a
    subscriber who appears in one edition or in nine editions of the
    same work has exactly one edge to that work. Edition-to-edition flow
    is out of scope; this graph answers cross-work readership-overlap
    questions only.

    The graph is written to GraphML format.

--------------------------------------------------------------------------------
LICENSE:
    MIT License
    Copyright (c) 2026 Lawrence Evalyn
================================================================================
"""

import csv
import argparse
import sys
from pathlib import Path
import networkx as nx


EXPECTED_COLUMNS = {"person_id", "normalized_name", "book", "author", "year"}


def _year_int(value):
    """Parse a year to int, or None if it isn't a plain year."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def load_csv(csv_path):
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = EXPECTED_COLUMNS - set(reader.fieldnames)
        if missing:
            print(f"ERROR: {csv_path} is missing columns: {missing}")
            sys.exit(1)
        for row in reader:
            rows.append(row)
    return rows


def build_graph(rows):
    """Build a bipartite subscriber-work graph.

    All editions of a book collapse into one work node, and each
    subscriber-work pair yields a single attribute-free edge regardless
    of how many editions it came from.
    """
    G = nx.Graph()

    for row in rows:
        work_id = row["book"]
        year = _year_int(row.get("year"))

        if work_id in G:
            node = G.nodes[work_id]
            if node["author"] != row["author"]:
                print(
                    f"WARNING: Conflicting author for work '{work_id}':\n"
                    f"  previously: author='{node['author']}'\n"
                    f"  this row:   author='{row['author']}'\n"
                    f"  (keeping the original value)"
                )
            # Widen the publication-year span as editions accumulate.
            if year is not None:
                if node["first_year"] == "" or year < int(node["first_year"]):
                    node["first_year"] = year
                if node["last_year"] == "" or year > int(node["last_year"]):
                    node["last_year"] = year
        else:
            G.add_node(
                work_id,
                bipartite=0,
                node_type="work",
                book=row["book"],
                author=row["author"],
                first_year=year if year is not None else "",
                last_year=year if year is not None else "",
                label=row["book"],
            )

        person_id = row["person_id"]
        G.add_node(
            person_id,
            bipartite=1,
            node_type="subscriber",
            normalized_name=row["normalized_name"],
            label=person_id,
        )

        # Idempotent: re-adding an existing subscriber-work edge is a no-op,
        # so multiple editions of one work yield a single edge.
        G.add_edge(person_id, work_id)

    return G


def main():
    parser = argparse.ArgumentParser(
        description="Build a bipartite subscriber-work graph from the "
                    "deduplicated subscriber CSV."
    )
    parser.add_argument(
        "input_csv",
        help="Path to the deduplicated CSV (from entity-resolution)."
    )
    parser.add_argument(
        "--output", default="outputs/graph.graphml",
        help="Path for the GraphML output (default: outputs/graph.graphml)"
    )
    args = parser.parse_args()

    input_path = Path(args.input_csv)
    if not input_path.is_file():
        print(f"ERROR: {input_path} is not a file.")
        sys.exit(1)

    rows = load_csv(input_path)
    print(f"Read {len(rows)} rows from {input_path}")

    G = build_graph(rows)

    work_nodes = [n for n, d in G.nodes(data=True) if d["bipartite"] == 0]
    subscriber_nodes = [n for n, d in G.nodes(data=True) if d["bipartite"] == 1]
    print(f"Graph: {len(work_nodes)} work nodes, "
          f"{len(subscriber_nodes)} subscriber nodes, "
          f"{G.number_of_edges()} edges")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(G, output_path)
    print(f"Wrote graph to {output_path}")


if __name__ == "__main__":
    main()
