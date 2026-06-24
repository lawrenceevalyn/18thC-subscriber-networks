# Name-Parsing Pipeline

Decomposes raw subscriber-list entries into structured fields: title, first name, last name, postnominals, occupation, affiliation, location, and notes. Output feeds [entity-resolution/](../entity-resolution/) and, downstream, [bipartite-graphs/](../bipartite-graphs/).

## Input / output

- **Input:** a directory of CSVs, one per book/edition. Required columns: `listed as`, `book`, `author`, `edition`, `year`, `no.`. Optional: `refined listing` (used in preference to `listed as` when present). Any other columns are carried through untouched.
- **Output:** `outputs/04-parsed.csv` — one row per entry with `entry_id`, `person_id`, `parsed_title`, `parsed_first`, `parsed_last`, `parsed_postnominals`, `parsed_occupation`, `parsed_affiliation`, `parsed_location`, `parsed_notes`, `name_type`, `title_key`, `name_order`, `normalized_name`, plus the source columns.

### Trailing attributes

Information after the name core is split into typed, flat columns (no JSON) so each is readable and greppable. `parsed_occupation` (advocate, bookseller, surgeon…; lexicon in `resources/occupations.csv`) and `parsed_affiliation` (Inner Temple, T.C.D, regiments) are **identifying** for entity resolution; `parsed_location` likewise. `parsed_postnominals` is weakly identifying; `parsed_notes` (copy counts, "son of X", unclassified text) is **not** identifying. A bare "ditto" is kept as a sentinel in `parsed_location` for a later resolution pass to fill from the line above. Currently these typed attributes are populated for surname-first lists; first-last enrichment and ditto resolution are future work.

## Stages

| # | Script | Purpose |
|---|--------|---------|
| 1 | `01_ingest.py` | Consolidate all input CSVs; assign `entry_id` and initial `person_id`. |
| 2 | `02_split_compounds.py` | Split compound entries ("Lord and Lady Barnard") into separate rows. Operates in place on the consolidated CSV. |
| 3 | `03_normalize.py` | Standardize spelling, punctuation, whitespace, honorific forms. Replace commas/semicolons with spaces (preserving word boundaries), normalize `&` to `and`, strip `[?]` OCR markers, strip preambles ("His Grace") while preserving meaningful title distinctions ("Rev. Dr.", "Right Hon."). Spelling-correction pairs live in `resources/spelling-corrections.csv`. |
| 4 | `04_parse_names.py` | Decompose into structured fields. Classifies each entry into one of three tracks: titled (full string → `title_key`), personal with title (extract leading/trailing qualifiers), bare (split into first + last). Extracts locations from "of PLACE" patterns (falling back to the normalized form for fused OCR text) and strips geographic "of" after extraction. Detects each list's **name order** before parsing (see below) and applies the matching core strategy. |

### Name-order detection

Subscriber lists are internally consistent but differ from one another: some are "Firstname Lastname", others are surname-first ("Lastname Firstname"), with no reliable comma to tell them apart. `order_detection.py` decides each list's order (a list = one `author`/`book`/`edition`) by voting across its entries — primarily on the position of known given names (`resources/given-names.csv`), with list alphabetization as a tiebreak — and records it in the `name_order` column. Stage 4 then dispatches to a first-last or surname-first core parser accordingly. Surname-first parsing uses the raw entry's first comma as the name-core boundary so trailing locations/qualifiers don't leak into the given name.

Low-confidence lists are logged at run time for review. To force a list's order, add a row to `resources/list-overrides.csv` (`list_key` = `author|book|edition`, `order` = `first-last` or `last-first`); overrides take precedence over detection.

`04_parse_names.py` imports the normalizer from `03_normalize.py` to re-normalize the isolated name core when parsing surname-first entries.

## Running it

```bash
python3 pipeline.py                              # uses ../data/input-lists by default
python3 pipeline.py --input /path/to/your/csvs
python3 pipeline.py --output /tmp/parsed.csv
```

Or via the root orchestrator: `python3 ../pipeline.py parse`.

Individual stages run directly:

```bash
python3 01_ingest.py ../data/input-lists --output outputs/01-consolidated.csv
python3 02_split_compounds.py outputs/01-consolidated.csv
python3 03_normalize.py outputs/01-consolidated.csv --output outputs/03-normalized.csv
python3 04_parse_names.py outputs/03-normalized.csv --output outputs/04-parsed.csv
```

## Dependencies

Python 3.10+ — standard library only. `tomli` only on Python < 3.11.

## Citation

See the [top-level README](../README.md#citation) for how to cite this software.

## License

MIT License. Copyright (c) 2026 Lawrence Evalyn. Full text in [../LICENSE](../LICENSE).
