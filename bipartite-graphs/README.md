# Bipartite Graph Construction

Builds a bipartite graph of **subscribers ↔ works** from a deduplicated subscriber CSV. Rendering lives in the sibling [bipartite-viz/](../bipartite-viz/); this directory is the graph-construction stage only.

Upstream concerns (parsing, deduplication) live in sibling directories — see the [root README](../README.md) for the full topology.

## The graph model

The second mode of the bipartite graph is the **work** (book), not the individual edition. All editions of a book collapse into a single work node, and each subscriber–work pair is a single, attribute-free edge regardless of how many editions it came from.

This keeps the graph focused on one question — *which works shared a readership*. For a corpus where every book has one edition, the collapse is a no-op; for a multi-edition work like Equiano's *Interesting Narrative* (9 editions), the editions fold into one node.

## Input / output

- **Input:** a deduplicated CSV with collapsed `person_id` values, produced by [entity-resolution/](../entity-resolution/). Required columns: `person_id`, `normalized_name`, `book`, `author`, `year`.
- **Output:** `outputs/graph.graphml`.

| Script | Outputs | Description |
|--------|---------|-------------|
| `build_graph.py` | `graph.graphml` | Bipartite NetworkX graph: work nodes (attrs `book`, `author`, `first_year`, `last_year`) + subscriber nodes, connected by attribute-free subscription edges. |

## Running it

```bash
python3 pipeline.py                                # build graph + render all viz
python3 pipeline.py --input path/to/dedup.csv      # override input
python3 pipeline.py --output path/to/graph.graphml # override graph output
```

`pipeline.py` builds the graph, then hands off to `../bipartite-viz/pipeline.py` for rendering.

Or via the root orchestrator: `python3 ../pipeline.py graph`.

To build the graph alone:

```bash
python3 build_graph.py ../entity-resolution/outputs/deduplicated.csv --output outputs/graph.graphml
```

## Configuration

`pipeline.toml` holds the deduplicated input path and the graph output path.

## Dependencies

- Python 3.10+
- `networkx`
- `tomli` only on Python < 3.11

(Visualization dependencies — `matplotlib`, `numpy` — live with [bipartite-viz/](../bipartite-viz/).)

## Citation

See the [top-level README](../README.md#citation) for how to cite this software.

## License

MIT License. Copyright (c) 2026 Lawrence Evalyn. Full text in [../LICENSE](../LICENSE).
