# Entity-Resolution Pipeline

Matches subscriber entries across editions and books, then collapses matched entries to share a single `person_id`. Output is a deduplicated CSV consumed by [bipartite-graphs/](../bipartite-graphs/).

## Input / output

- **Input:** parsed CSV from [name-parsing/](../name-parsing/) (`outputs/04-parsed.csv`).
- **Output:** `outputs/deduplicated.csv` — same rows as the input but with collapsed `person_id` values. Match decisions live in four side files: `05-title-matches.csv`, `05-title-candidates.csv`, `06-auto-resolved.csv`, `06-candidates.csv`.

## Running it

```bash
python3 pipeline.py --force            # match + apply, no human review
python3 pipeline.py --match            # produce candidate files for review (restores prior verdicts from the ledger)
python3 pipeline.py --review           # interactive review of 06-candidates.csv (harvests verdicts into the ledger on exit)
python3 pipeline.py --review outputs/05-title-candidates.csv
python3 pipeline.py --harvest          # save spreadsheet-edited verdicts into the ledger (no interactive review)
python3 pipeline.py --apply            # apply reviewed matches → deduplicated.csv
python3 pipeline.py --force --strict   # require location or postnominal (not just a first name) for non-distinctive titles
```

Or via the root orchestrator: `python3 ../pipeline.py dedupe [--strict]`.

### Interactive review keybindings (`cli_review.py`)

| Key | Action |
|-----|--------|
| `y` | Accept the group |
| `n` | Reject the group |
| `x #` | Exclude entry # from the group |
| `s` | Skip (decide later) |
| `q` | Quit and save progress |

Progress saves after each decision; rerunning `--review` resumes where you left off. As an alternative, open the candidate CSV in a spreadsheet and set the `match` column directly (`y`/`n`/`x`), then run `python3 pipeline.py --harvest` to record those verdicts in the ledger so they survive the next re-match.

### Typical workflows

**Quick:** `pipeline.py --force` → inspect `outputs/06-candidates.csv` afterward to see what got flagged.

**Careful:** `--match` → `--review` (component candidates) → `--review outputs/05-title-candidates.csv` (title candidates) → `--apply`. Verdicts are harvested into `resources/decisions.csv` automatically, so a later `--match` restores them rather than discarding them.

**Maximizing cross-book matches** (closely related corpora): the default behaviour already allows entries with a first name to match cross-book without a location or postnominal. Add `--strict` only when you want to enforce the stricter location/postnominal requirement.

## The `--strict` flag

By default, cross-book matching allows entries with non-distinctive titles (Mr., Mrs., Miss, Esq., bare) to participate as long as they have a first name, a location, or a postnominal. "Mr. Smith" is excluded; "Mr. John Smith" is allowed.

`--strict` tightens this: a first name alone is not sufficient, and a location or postnominal is required.

## Stages

| # | Script | Purpose |
|---|--------|---------|
| 5 | `05_match_titles.py` | Group entries sharing the same positional title (e.g., all "Duke of Bedford" appearances). By default same title = same person. When `resources/title-holders.csv` records that a title changed hands between editions (e.g., 4th Duke → 5th Duke), the group is split by holder using year ranges. |
| 6 | `06_match_components.py` | Match non-titled entries using rules over five fields: title, first, last, location, postnominals. Mr., Esq., and bare are treated as equivalent titles. Cross-book matching requires non-distinctive titles to carry a matching location or postnominal. Coexistence blocks treat name patterns that coexist in any edition as different people everywhere. Includes fuzzy linkage (linking singletons to established clusters and merging clusters with similar last names), fuzzy first-name matching (with corroboration requirements), surname prefix normalization (De/La/Le/Van/Von), and hyphen-normalized location comparison. |
| 7 | `07_deduplicate.py` | Read all four match files and write `deduplicated.csv` with collapsed `person_id` values. Processing order: title auto → title candidates → component auto → component candidates (highest precedence). |
| — | `decisions.py` | Durable, pair-level record of human review verdicts, so manual work survives re-running the matcher. See [Persisting review decisions](#persisting-review-decisions). |
| — | `edition_diff.py` | Diagnostic tool: compares departures vs arrivals between consecutive editions to surface likely missed matches with a multi-factor scoring rubric. |

Auto-resolved matches are accepted automatically; ambiguous cases go to candidate files for review.

## Persisting review decisions

`06_match_components.py` regenerates `06-candidates.csv` from scratch every run, with the `match` column blank and `group_id`s (`cm_0001`, …) reassigned by a sequential counter. So review verdicts stored in that file would be wiped on every re-match — and could not be re-attached by `group_id` even if they survived.

To prevent that, every verdict is recorded **pair by pair** — keyed on the two `entry_id`s, the only identifier stable across re-runs — in a durable ledger at `resources/decisions.csv`. Two operations (in `decisions.py`) move data between the ledger and the disposable candidates file:

- **`harvest`** — reads reviewed verdicts out of `06-candidates.csv` and writes them to the ledger as pairwise decisions. A group accepted with an excluded entry becomes the relevant `y` pairs plus `n` pairs for the exclusion; a rejected group becomes all-`n`.
- **`apply`** — reads the ledger and pre-fills the `match` column of a freshly generated `06-candidates.csv`, so previously decided groups come back already marked and only genuinely new groups need review.

The pipeline runs these automatically: `--match` ends with an `apply`, and `--review` ends with a `harvest`. `cli_review.py` and `07_deduplicate.py` are unchanged — the ledger flows through the existing `match` column. `resources/decisions.csv` is the artifact to commit to version control; it doubles as an auditable, citable record of every manual matching choice.

**Stability caveat:** the ledger survives re-running *matching* (same parsed input → stable `entry_id`s). A full upstream re-parse that renumbers entries would orphan it; the ledger stores each pair's names and book/edition context to support a future content-based re-link if that becomes necessary.

**Representable decisions.** Because `07_deduplicate.py` anchors a merge on a group's first row, `apply` can fully restore a group when the first entry is part of the accepted cluster (the common case). A decided group whose match cluster excludes its first row can't be expressed in the group `match` column, so it returns to review — but the pairwise verdicts remain in the ledger and are never lost.

## Matching logic (06\_match\_components.py)

Component matching evaluates five parsed fields to decide whether two entries represent the same person. Each field can block a match, support it, or be neutral. A few thresholds differ by scope (within-book vs cross-book) — but title compatibility is the same in both.


### Exact last name matching (within-book)

When last names match exactly (after surname-prefix normalization: De, La, Le, Van, Von are stripped), matching depends on first-name strength and title equivalence.

**Exact or initial first name + equivalent title** — auto-resolved.

- `Mr. John Low Jun. Manchester` (ed 5) / `Mr. John Low Jun. Manchester` (ed 6) — auto
- `Mr. J. Benjafield` (ed 1) / `Mr. J. Benjafield` (ed 2) — auto

**Missing first name + identical title** — auto-resolved, but requires titles to be *identical*, not just equivalent. This prevents `Mr. Buxton` from matching `Buxton` (a different person might have the bare form).

- `Mr. Buxton` (ed 1) / `Mr. Buxton` (ed 2) — auto (both Mr.)
- `Mr. Buxton` / `Buxton` — **not matched** (Mr. is not identical to bare)

**Fuzzy first name + equivalent title** — allowed when two full names share the same first letter and are within a scaled edit distance (1 for short names, 2 for medium, 3 for long). Auto-resolved only with at least one corroborating signal (distinctive title, matching location, or matching postnominal); otherwise routed to candidates.

- `Miss Ann Harvey Catton` / `Miss An Harvey Catton` — auto (Miss is corroboration)
- `Mr. Elphinston Balfour` / `Mr. Elphington Balfour` — candidate (Mr. is not corroboration, no location/postnominal)

### Fuzzy last name matching

When last names differ, a match requires at least one "strong signal" beyond the last name, and the edit distance must be within a threshold scaled by name length and first-name strength.

**Strong signals** (cumulative):

| Signal | Weight |
|--------|--------|
| Distinctive title match (not Mr./Esq./bare) | +1 |
| Exact first name | +1 |
| Initial match | +0.5 |
| Location match | +1 |
| Postnominal match | +0.5 |

Total must reach at least 1.0. Fuzzy first names do not contribute here (fuzzy first + fuzzy last together is never allowed).

**Edit distance thresholds** (last name length vs first-name strength):

| Last name length | Exact first | Initial or missing first |
|------------------|-------------|--------------------------|
| 1-4 chars | distance 1 | exact only (distance 0) |
| 5-7 chars | distance 2 | distance 1 |
| 8+ chars | distance 3 | distance 2 |

Surname prefixes (De, La, Le, etc.) are stripped before computing distance, so "De Coetlogon" vs "Coetlogon" has distance 0.

Examples:

- `Mr. Joseph Howorth` / `Mr. Joseph Howarth` — signals: 1.0 (exact first); distance 2, length 7 with exact first allows 2 — **match**
- `Rev. Mr. Boog (Paisley)` / `Rev. Mr. Bogg (Paisley)` — signals: 2.0 (Rev. + location); distance 1, length 4 with missing first allows 0 — **blocked** (distance exceeds threshold despite strong signals)
- `Rev. C. E. De Coetlogon` / `Rev. C. E. Coetlogon` — stripped distance 0; matched as exact last via linkage

### Signals that support but never block

**Postnominals.** Matching postnominals (e.g., both have "Jun.") add 0.5 to strong signals. Differing postnominals (e.g., "Jun." vs "Sen.") do not block (unless the coexistence rule applies). Missing postnominals are neutral.

**Location.** A matching location adds 1.0 to strong signals. A missing location is neutral.

### Fuzzy linkage and cluster merging

After exact clustering, spelling variants can remain unlinked. The fuzzy linkage step (which runs before speculative fuzzy grouping) addresses this in two phases:

**Phase 1 — Singleton linkage.** Entries not yet matched are compared against the canonical entry of each existing auto-resolved group with a fuzzy-similar last name. If the edit distance is at most 2 and first names match exactly, the entry is auto-resolved into the group.

- `Carr` (1 entry, eds 1) links to the `Karr` cluster (8 entries, eds 2-9)

**Phase 2 — Cluster merging.** Pairs of auto-resolved groups with fuzzy-similar last names are compared via their canonical entries. If compatible (distance at most 2, exact first name), the smaller group is absorbed into the larger.

- `Lowe` cluster (2 entries, eds 3-4) merges into the `Low` cluster (5 entries, eds 5-9)

### Cross-book restrictions

By default, entries with non-distinctive titles (Mr., Mrs., Miss, Esq., bare) are eligible for cross-book matching if they have a first name, a location, or a postnominal. This prevents bare surname entries like "Mr. Smith" from creating false matches across unrelated lists.

- `Mr. Smith` — **not eligible** (no first name, location, or postnominal)
- `Mr. John Smith` — eligible (first name present)
- `Mr. John Smith (Leeds)` — eligible (first name + location)
- `John Smith Esq.` — eligible (Esq. is a postnominal)

The `--strict` flag tightens this requirement: a first name alone is no longer sufficient; a location or postnominal is required.

### Hard blockers

These conditions always prevent a match, regardless of how strong other signals are.

**Same edition.** Two entries from the same book and edition never match each other.

**Title incompatibility.** Titles must be compatible under the equivalence rules, which apply the same way whether the two entries come from the same book or different books.

- Mr., Esq., and bare (no title) are all equivalent.
  - `Mr. Richard Purcell` / `Richard Purcell` — compatible (Mr. = bare)
  - `Mr. Richard Purcell` / `Richard Purcell, Esq.` — compatible (Mr. = Esq.)
  - `Rev. Mr. Boog` / `Rev. Boog` — compatible (Rev. Mr. = Rev.)
- Distinctive titles (Rev., Capt., Dr., Sir, etc.) must match exactly.
  - `Rev. Mr. Housman` / `Mr. Houseman` — **blocked** (Rev. =/= Mr.)

(A separate eligibility rule still treats Esq. and the other common titles as *non-distinctive* when deciding whether an entry may match across books — see [Cross-book restrictions](#cross-book-restrictions) — but that governs whether an entry participates, not whether two titles are compatible.)
  - `Right Hon. H. S. Conway` / `Hon. H. S. Conway` — **blocked**

**First-name conflict.** Two different full first names always block a match.

- `William Stewart` / `David Stewart` — **blocked**
- `Mr. James Forbes` / `Mr. Samuel Forbes` — **blocked**

**Location conflict.** Two different locations always block.
- `Mr. John Smith (Leeds)` / `Mr. John Smith (Hull)` — **blocked**
- `Mr. John Smith (Leeds)` / `Mr. John Smith` — neutral (not a conflict)

**Coexistence blocks.** If two name patterns coexist in any single edition (same title + last name, but differing in first-name specificity or postnominals), they are treated as different people *everywhere*, not just in that edition.

- If ed 5 lists both `Mr. Smith` and `Mr. John Smith`, those patterns are blocked from ever merging.
- If ed 6 lists both `Joseph Howorth Jun.` and `Joseph Howorth Sen.`, Jun. and Sen. entries are blocked from ever merging.

## Resources

- `resources/title-holders.csv` — positional-title holders with year ranges; used by step 5 to split groups when a title changed hands.

## Dependencies

Python 3.10+, `rapidfuzz` (optional; falls back to a pure-Python Levenshtein). `tomli` only on Python < 3.11.

## Citation

See the [top-level README](../README.md#citation) for how to cite this software.

## License

MIT License. Copyright (c) 2026 Lawrence Evalyn. Full text in [../LICENSE](../LICENSE).
