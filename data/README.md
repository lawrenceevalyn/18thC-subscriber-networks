# Data

The pipeline runs on a directory of subscriber-list CSVs. By default that
directory is [`input-lists/`](input-lists/), which ships with the demo corpus
below; point the pipeline elsewhere with `--input` (see the top-level README) or
just drop your own CSVs into `input-lists/`.

## Demo corpus (`input-lists/`)

Subscriber lists transcribed from three eighteenth-century books by Black British
authors. Editions of the same book share a `book` value and collapse into a single
"work" in the graph, so the corpus contributes three works:

| File | Work | Author | Editions | Rows |
|---|---|---|---|---|
| `equiano-9-eds.csv` | *The Interesting Narrative* | Olaudah Equiano | 9 (1789–1794) | 5,102 |
| `equiano-american.csv` | *The Interesting Narrative* | Olaudah Equiano | American (1791) | 122 |
| `sancho-1782.csv` | *Letters* | Ignatius Sancho | 1 (1782) | 1,181 |
| `cugoano-1791.csv` | *Thoughts and Sentiments* | Ottobah Cugoano | 1 (1791) | 165 |

These are public-domain printed sources; the lists were transcribed from the
subscriber pages of the named editions.

## Input schema

Each CSV is one subscriber per row, with these columns:

| Column | Meaning |
|---|---|
| `no.` | Sequence number in the original printed list (integer; blanks are auto-numbered). |
| `listed as` | The subscriber name exactly as printed/OCR'd — the raw string the pipeline parses. |
| `book` | Short work title. Editions of one work must share this exact value. |
| `author` | Author, written `Last, First`. |
| `edition` | Edition identifier (e.g. `1`–`9`, or `Am`). |
| `year` | Publication year of that edition. |

This is the shape of the pipeline's expected input — the output of an OCR/transcription
step. To analyze your own books, produce CSVs with these six columns and place them in
`input-lists/` (or pass `--input <dir>`).
