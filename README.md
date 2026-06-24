# 18thC-subscriber-networks

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20825872.svg)](https://doi.org/10.5281/zenodo.20825872)

Turn transcribed eighteenth-century book-subscriber lists into a bimodal network of books and persons! Find out which books shared a readership, and exactly who those shared subscribers were! Maybe even generalize to *other* kinds of lists of eighteenth-century names? All driven by exhaustingly rules-based logic, with several opportunities for manual review and adjustment!

## What this does

Given a folder of subscriber-list CSVs (the kind of output you get from OCR'ing a book's subscriber pages), the pipeline cleans, normalizes, and parses the names, resolves the same person across different books and editions, and produces two things:

- **`overlap-network.png` / `.svg`** — a chord diagram of the works, with an arc between any
  two books that share subscribers, the arc's width set by how many they share.
- **`overlap-namelist.csv`** — every subscriber who appears in more than one work, with the
  list of works for each.

## How the pipeline fits together

```
data/input-lists/*.csv            one row per subscriber (the "listed as" schema)
        │
        ▼  parse      name-parsing/         ingest → split compounds → normalize → parse
   parsed CSV                               into title / first / last / occupation /
        │                                   affiliation / location / notes
        ▼  dedupe     entity-resolution/    match by title → match by components →
 deduplicated CSV                           collapse matched rows to one person_id
        │
        ▼  graph      bipartite-graphs/  +  bipartite-viz/
        │             build the subscriber↔work graph, then render:
        ├──  overlap-network.png / .svg     chord diagram of shared subscribers
        └──  overlap-namelist.csv           every subscriber shared across ≥ 2 works
```

Each stage is a self-contained directory with its own README and runner, and can be used on
its own. The top-level [`pipeline.py`](pipeline.py) just chains them.

## Quickstart

```bash
git clone https://github.com/lawrenceevalyn/18thC-subscriber-networks.git
cd 18thC-subscriber-networks

python3 -m venv .venv && source .venv/bin/activate   # Python 3.10+
pip install -r requirements.txt

python3 pipeline.py all --strict
```

That runs the whole chain on the bundled demo corpus in
[`data/input-lists/`](data/input-lists/) (subscriber lists from three eighteenth-century
books by Black British authors — Equiano, Sancho, and Cugoano). When it finishes, the
outputs are in **`bipartite-viz/outputs/`**:

- `overlap-network.png` and `overlap-network.svg`
- `overlap-namelist.csv`

`--strict` uses conservative cross-book matching (it requires a location or postnominal —
not just a shared first name — before linking two common-titled entries across books). Drop
it for more, looser cross-book links.

### Running individual stages

```bash
python3 pipeline.py parse      # name-parsing  → name-parsing/outputs/04-parsed.csv
python3 pipeline.py dedupe     # entity-res    → entity-resolution/outputs/deduplicated.csv
python3 pipeline.py graph      # graph + chord → bipartite-viz/outputs/
```

Each stage also runs directly from its own directory — see the per-stage READMEs.

## Using your own data

The pipeline's input is a directory of CSVs, one per book/edition, with six columns:

| Column | Meaning |
|---|---|
| `no.` | Sequence number in the original printed list. |
| `listed as` | The subscriber name exactly as printed/OCR'd — the raw string that gets parsed. |
| `book` | Short work title. Editions of one work must share this exact value (they collapse into one node). |
| `author` | Author, written `Last, First`. |
| `edition` | Edition identifier (e.g. `1`, `2`, … or `Am`). |
| `year` | Publication year of that edition. |

Replace the files in `data/input-lists/` with your own, then run `python3 pipeline.py all`.
(Producing these CSVs from page images — OCR/transcription — is upstream of this repo.) See
[`data/README.md`](data/README.md) for the full schema.

## Repository layout

| Directory | What it does |
|---|---|
| [`name-parsing/`](name-parsing/) | Ingest the CSVs and decompose each `listed as` string into structured fields (order-aware: handles both "First Last" and surname-first lists). |
| [`entity-resolution/`](entity-resolution/) | Match entries that refer to the same person across editions and books, and collapse them to a shared `person_id`. Supports automatic matching and an optional interactive review. |
| [`bipartite-graphs/`](bipartite-graphs/) | Build the bipartite subscriber↔work graph (editions of a book collapse into one work node). |
| [`bipartite-viz/`](bipartite-viz/) | Render the chord overlap network and export the shared-subscriber CSV. |
| [`data/`](data/) | The bundled demo corpus and the input schema. |

## Requirements

Python 3.10+ and four packages (`networkx`, `matplotlib`, `numpy`, `rapidfuzz`); see
[`requirements.txt`](requirements.txt). No OCR/ML dependencies — the heavy lifting is plain
Python over CSVs. The chord diagram will use the *Playfair Display* and *Roboto* fonts if
they are installed, and falls back to matplotlib's defaults otherwise.

## Citation

If you use this software, please cite it. GitHub's **"Cite this repository"** button reads
[`CITATION.cff`](CITATION.cff); or use:

```bibtex
@software{evalyn2026subscribernetworks,
  author  = {Evalyn, Lawrence},
  title   = {{18thC-subscriber-networks}: Subscriber-Overlap Networks for
             Eighteenth-Century Books},
  version = {1.0.0},
  year    = {2026},
  url     = {https://github.com/lawrenceevalyn/18thC-subscriber-networks}
  doi     = {10.5281/zenodo.20825871}
}
```

You may also be interested in:
* "[Bimodal Network Graphs of Crowdfunded Literary Patronage: Two Views of Black Britons Publishing in the Eighteenth Century](https://lawrenceevalyn.com/ACH-2026-poster.html)", *Association for Computers and the Humanities 2026*, a virtual poster introducting this pipeline.

## License

MIT License. Copyright (c) 2026 Lawrence Evalyn. Full text in [LICENSE](LICENSE).

## Development notes

This software was developed through collaborative AI-assisted programming between Lawrence Evalyn and Anthropic's Claude. Its results have been meticulously reviewed for accuracy, within the specific domain of eighteenth-century namelists..