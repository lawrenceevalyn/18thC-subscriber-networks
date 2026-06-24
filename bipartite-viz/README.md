# Overlap Visualization

Renders the cross-work overlap outputs from the **subscriber ↔ work** bipartite graph built by [bipartite-graphs/](../bipartite-graphs/). Each program is a small standalone script that reads the GraphML graph; shared plumbing (graph IO, book colors/labels, figure saving, and the overlap measures) lives in `_common.py`.

## Programs

| Program | Outputs | Description |
|---------|---------|-------------|
| `overlap_network_viz.py` | `overlap-network.png/svg` | Cross-work overlap as a **chord diagram**: works ordered around the circle by community (so clusters sit together, separated by gaps), joined by arced chords whose **width = number of shared subscribers**. Node color = community, size & inner number = subscriber count, radial label = `Surname, Short Title`. `--highlight` points a manicule (pointing hand) at one motivating work. |
| `crossbook_export.py` | `overlap-namelist.csv` | Data export: every subscriber appearing in more than one work, sorted by number of works. This is the readable, citable evidence behind the chord. |

## Labels and the short-title resource

On-figure labels use a short form of each book title. `resources/short-titles.csv` is a curated `book,short_title` map — fill in the `short_title` column for any book to control its label; rows left blank fall back to an automatic heuristic (drop a leading article, cut at the first comma, then trim to length). Labels combine this with the author surname as `Surname, Short Title`.

## Running it

```bash
python3 pipeline.py                                # chord + CSV, using pipeline.toml defaults
python3 pipeline.py --input path/to/graph.graphml  # override the GraphML input
```

Or via the root orchestrator: `python3 ../pipeline.py graph` (which builds the graph first, then renders).

Or run either program directly:

```bash
python3 overlap_network_viz.py ../bipartite-graphs/outputs/graph.graphml
python3 overlap_network_viz.py ../bipartite-graphs/outputs/graph.graphml --highlight Equiano
python3 crossbook_export.py    ../bipartite-graphs/outputs/graph.graphml
```

Both PNG and SVG are written for the figure regardless of the `--output` extension, with **transparent backgrounds** so they drop cleanly onto slides or pages of any color.

## What the chord shows

The chord encodes the **raw count** of shared subscribers as each arc's width. To weigh an overlap against what chance would predict — the *representation factor*, `observed / (|A|·|B| / N)`, where `>1` means two works share more readers than their sizes alone explain — `_common.overlap(G, "repr")` computes it for any pair (`"jaccard"`, `|A ∩ B| / |A ∪ B|`, is available too). These measures also drive the community ordering that keeps the chord legible.

## Configuration

`pipeline.toml` holds the GraphML input path and `highlight` — an optional author surname or book title for the chord to flag with a manicule. Leave it `""` (the default) for a neutral figure.

## Dependencies

- Python 3.10+
- `networkx`, `matplotlib`, `numpy`
- `tomli` only on Python < 3.11

The chord uses the **Playfair Display** and **Roboto** fonts when they are installed on the system; otherwise matplotlib falls back to its default families.

## License

MIT License. Copyright (c) 2026 Lawrence Evalyn. Full text in [../LICENSE](../LICENSE).
