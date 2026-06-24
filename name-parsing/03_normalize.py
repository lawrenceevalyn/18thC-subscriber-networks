"""
================================================================================
       Bipartite Graph Pipeline for Eighteenth-Century Subscriber Lists
                            03_normalize.py
================================================================================
RUN WITH: python3 03_normalize.py outputs/01-consolidated.csv
          python3 03_normalize.py outputs/01-consolidated.csv --output outputs/03-normalized.csv

DESCRIPTION:
    Pure string normalization for subscriber names. Reads the consolidated
    CSV and adds a normalized_name column. The original "normalization
    input" column is preserved unchanged.


    Normalization rules (applied in order):
        0. Strip all commas and semicolons.
        1. Repair missing whitespace.
        2. Collapse multiple spaces; trim.
        3. Apply spelling corrections from resources/spelling-corrections.csv.
        4. Abbreviate titles (Reverend -> Rev.).
        4b. Ensure abbreviated titles have periods; normalize case.
        4c. Expand abbreviated first names (Tho. -> Thomas).
        4d. Strip redundant preambles (His Grace, His Royal Highness, etc.).
        4e. Insert "of" after peerage titles when missing.
        4f. Strip geographic "of" not part of a positional title.
        5. Strip leading "The ".
        6. Strip non-geographic annotations (2 copies, etc.).
        6b. Strip trailing ditto markers.
        7. Normalize dash placeholders to "----".
        8. Standardize initials to "J. C." format.
        9. Strip trailing punctuation.
        9b. Clean spurious periods.
       10. Final whitespace cleanup.

--------------------------------------------------------------------------------
LICENSE:
    MIT License
    Copyright (c) 2026 Lawrence Evalyn
================================================================================
"""

import csv
import re
import argparse
import sys
from pathlib import Path


REQUIRED_COLUMNS = {"entry_id", "person_id", "normalization input"}


# ---------------------------------------------------------------------------
# Spelling corrections.
# ---------------------------------------------------------------------------
_RESOURCES_DIR = Path(__file__).parent / "resources"

def _load_spelling_corrections():
    csv_path = _RESOURCES_DIR / "spelling-corrections.csv"
    corrections = {}
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            corrections[row['misspelling']] = row['correction']
    return corrections

SPELLING_CORRECTIONS = _load_spelling_corrections()


# ---------------------------------------------------------------------------
# Abbreviation table.
# ---------------------------------------------------------------------------
ABBREVIATION_TABLE = {
    "Reverend": "Rev.", "Captain": "Capt.", "Admiral": "Adm.",
    "Honourable": "Hon.", "Honorable": "Hon.", "Colonel": "Col.",
    "Lieutenant": "Lt.", "General": "Gen.", "Sergeant": "Sgt.",
    "Esquire": "Esq.", "Doctor": "Dr.", "Professor": "Prof.",
    "Mister": "Mr.", "Mistress": "Mrs.", "Madam": "Mme.",
    "Junior": "Jun.", "Senior": "Sen.", "Viscount": "Visc.",
    "Lieut": "Lt.", "Mess": "Messrs.", "Rt": "Right",
    "Ld": "Lord", "Saint": "St.",
}


# ---------------------------------------------------------------------------
# Abbreviated first names.
# ---------------------------------------------------------------------------
NAME_ABBREVIATIONS = {
    "Tho.": "Thomas", "Thos.": "Thomas", "Geo.": "George",
    "Wm.": "William", "Willm.": "William", "Jno.": "John",
    "Jos.": "Joseph", "Jas.": "James", "Chas.": "Charles",
    "Chs.": "Charles", "Edw.": "Edward", "Edwd.": "Edward",
    "Richd.": "Richard", "Rich.": "Richard", "Robt.": "Robert",
    "Rob.": "Robert", "Saml.": "Samuel", "Sam.": "Samuel",
    "Danl.": "Daniel", "Nathl.": "Nathaniel", "Nath.": "Nathaniel",
    "Benj.": "Benjamin", "Benjn.": "Benjamin", "Hy.": "Henry",
    "Hen.": "Henry", "Humph.": "Humphrey", "Abr.": "Abraham",
    "Abra.": "Abraham", "Alexr.": "Alexander", "Andw.": "Andrew",
    "Andr.": "Andrew", "Arth.": "Arthur", "Barth.": "Bartholomew",
    "Christo.": "Christopher", "Corns.": "Cornelius",
    "Edmd.": "Edmund", "Eliz.": "Elizabeth", "Fredk.": "Frederick",
    "Gilb.": "Gilbert", "Jonath.": "Jonathan", "Josh.": "Joshua",
    "Mattw.": "Matthew", "Matt.": "Matthew", "Michl.": "Michael",
    "Mich.": "Michael", "Nichs.": "Nicholas", "Nich.": "Nicholas",
    "Patk.": "Patrick", "Steph.": "Stephen", "Timoy.": "Timothy",
    "Walt.": "Walter", "Will.": "William", "Alex.": "Alexander",
    "Dan.": "Daniel", "Ewd.": "Edward", "Fred.": "Frederick",
    "Cath.": "Catherine", "Christ.": "Christopher",
    "Phila.": "Philadelphia", "Connect.": "Connecticut",
}

_MASCULINE_SIGNALS = {
    "mr", "esq", "sir", "rev", "capt", "col", "dr",
    "lt", "adm", "sgt", "prof", "hon",
}
_FEMININE_SIGNALS = {"mrs", "miss", "ms", "dame", "lady"}


# ---------------------------------------------------------------------------
# Annotations.
# ---------------------------------------------------------------------------
ANNOTATION_PATTERNS = [
    r"\s*\d+\s+cop(?:y|ies)", r"\s*\d+\s+sets?",
    r"\s*\d+\s+cop\.", r"\s*\d+\s+copes?", r"\s*\d+\s+books?",
    r"\s*\d+\s+do\.?",
]


# ---------------------------------------------------------------------------
# Known abbreviations.
# ---------------------------------------------------------------------------
KNOWN_ABBREVIATIONS = {
    "Mr", "Mrs", "Ms", "Rev", "Dr", "Capt", "Adm", "Col",
    "Lt", "Sgt", "Hon", "Prof", "Esq", "Jun", "Sen", "St",
    "Bart", "Bt", "Visc", "Messrs", "Gen", "Mme",
}

_NON_ABBREVIATION_WORDS = {
    "Brown", "Dale", "Lord", "Robert", "John", "Right", "Sir",
    "Ewen", "William", "James", "Samuel",
}


# ---------------------------------------------------------------------------
# Precompiled patterns.
# ---------------------------------------------------------------------------

def _build_alternation(mapping_keys):
    sorted_keys = sorted(mapping_keys, key=len, reverse=True)
    pattern = r'\b(' + '|'.join(re.escape(k) for k in sorted_keys) + r')\b'
    return re.compile(pattern, re.IGNORECASE)


_SPELLING_RE = _build_alternation(SPELLING_CORRECTIONS.keys())
_SPELLING_LOOKUP = {k.lower(): v for k, v in SPELLING_CORRECTIONS.items()}

_TITLE_RE = _build_alternation(ABBREVIATION_TABLE.keys())
_TITLE_LOOKUP = {k.lower(): v for k, v in ABBREVIATION_TABLE.items()}

_ABBREV_ALTS = sorted(list(KNOWN_ABBREVIATIONS) + ["Miss"], key=len, reverse=True)
_ABBREV_RE = re.compile(
    r'\b(' + '|'.join(re.escape(a) for a in _ABBREV_ALTS) + r')\b\.?',
    re.IGNORECASE,
)
_ABBREV_LOOKUP = {a.lower(): a + '.' for a in KNOWN_ABBREVIATIONS}
_ABBREV_LOOKUP["miss"] = "Miss"

_NAME_ABBREV_LOOKUP = {}
for _abbrev, _full in NAME_ABBREVIATIONS.items():
    _NAME_ABBREV_LOOKUP[_abbrev.lower()] = _full
    if _abbrev.endswith('.') and len(_abbrev) > 2:
        _NAME_ABBREV_LOOKUP[_abbrev[:-1].lower()] = _full

_ANNOTATION_RE = re.compile(
    '|'.join('(?:' + p + ')' for p in ANNOTATION_PATTERNS),
    re.IGNORECASE,
)

_RE_TRAILING_DITTO = re.compile(
    r'\s+(?:\d+\s+)?(?:of\s+)?(?:ditto|do\.?)\s*$', re.IGNORECASE,
)

_MID_PERIOD_RE = re.compile(
    r'\b(' + '|'.join(re.escape(w) for w in _NON_ABBREVIATION_WORDS)
    + r')\.\s', re.IGNORECASE,
)

_RE_PERIOD_LETTER = re.compile(r'\.([A-Za-z])')
_RE_LOWER_UPPER = re.compile(r'([a-z])([A-Z])')
_RE_MC_SPLIT = re.compile(r'\bMc ([A-Z])')
_RE_MAC_SPLIT = re.compile(r'\bMac ([A-Z])')
_RE_STUCK_OF = re.compile(r'([a-z])(of)(?=\s|[A-Z])')
_RE_DETACHED_INITIAL = re.compile(r'\b([A-Z]) \.')
_RE_ABBREV_HYPHEN = re.compile(r'\.-((?:[A-Z][a-z]))')
_RE_MULTI_SPACE = re.compile(r'\s+')
_RE_LEADING_THE = re.compile(r'^The\s+', re.IGNORECASE)
_RE_LONG_DASH = re.compile(r'[-–—]{2,}')
_RE_DASH_LETTER = re.compile(r'(----)([A-Za-z])')
_RE_INITIALS_NO_SPACE = re.compile(r'\b([A-Z])\.\s*([A-Z])\.')
_RE_BARE_INITIALS = re.compile(r'\b([A-Z])\s(?=[A-Z][\.\s])')
_RE_BARE_INITIAL_AFTER_PERIOD = re.compile(r'(?<=\. )([A-Z]) (?=[A-Z])')
_RE_DOUBLE_PERIOD = re.compile(r'\.\s*\.')
_RE_SHORT_ABBREV = re.compile(r'[A-Za-z]\.')

_RE_REDUNDANT_RIGHT_REV = re.compile(r'Right\.?\s*(?=Rev\.)', re.IGNORECASE)
_RE_REDUNDANT_REV_BISHOP = re.compile(r'Rev\.\s+(?:the\s+)?(?=Lord Bishop)', re.IGNORECASE)
_RE_REDUNDANT_REV_COURTESY = re.compile(r'(Rev\.)\s+(?:Mr\.|Dr\.)\s+', re.IGNORECASE)
_RE_REDUNDANT_MR_MD = re.compile(r'\bMr\.\s+(?=.*\bM\.\s*D\.\s*$)')
_RE_REDUNDANT_MR_INITIALS = re.compile(r'^Mr\.\s+(?=[A-Z]\.\s+[A-Z]\.)')
_RE_REDUNDANT_GRACE = re.compile(r'(?:His|Her) Grace the\s+', re.IGNORECASE)
_RE_REDUNDANT_HIGHNESS = re.compile(r'(?:His|Her) (?:Royal )?Highness the\s+', re.IGNORECASE)
_RE_REDUNDANT_EXCELLENCE = re.compile(
    r'His\s+Excellen(?:ce|cy)\s+(?:the\s+)?', re.IGNORECASE,
)
_RE_REDUNDANT_RIGHT_HON = re.compile(r'Right\.?\s*(?=Hon\.)', re.IGNORECASE)
_RE_REDUNDANT_HON_PEERAGE = re.compile(
    r'Hon\.\s+(?:the\s+)?(?=(?:Dowager )?(?:Duke|Duchess|Marquess|Marchioness'
    r'|Earl|Countess|Visc\.|Viscountess|Baron|Baroness|Lord(?!\s+Mayor)\b))',
    re.IGNORECASE,
)

_RE_INSERT_PEERAGE_OF = re.compile(
    r'\b((?:Dowager )?(?:Duke|Duchess|Marquess|Marchioness|Earl|Countess'
    r'|Visc\.|Viscountess|Baron|Baroness))\s+(?!of\b|and\b|the\b|Dowager\b)([A-Z])',
)

_TITLES_THAT_TAKE_OF = {
    "duke", "duchess", "marquess", "marquis", "marchioness",
    "earl", "countess", "visc", "viscountess", "baron", "baroness",
    "bishop", "archbishop", "dean", "mayor", "dowager",
    "prince", "princess",
}


# ---------------------------------------------------------------------------
# Normalization functions.
# ---------------------------------------------------------------------------

def strip_commas_and_semicolons(name):
    return name.replace(",", " ").replace(";", " ")

def repair_whitespace(name):
    name = _RE_ABBREV_HYPHEN.sub(r'. \1', name)
    name = _RE_PERIOD_LETTER.sub(r'. \1', name)
    name = _RE_LOWER_UPPER.sub(r'\1 \2', name)
    name = _RE_MC_SPLIT.sub(r'Mc\1', name)
    name = _RE_MAC_SPLIT.sub(r'Mac\1', name)
    name = _RE_STUCK_OF.sub(r'\1 \2', name)
    name = _RE_DETACHED_INITIAL.sub(r'\1.', name)
    return name

def collapse_whitespace(name):
    return _RE_MULTI_SPACE.sub(' ', name).strip()

def apply_spelling_corrections(name):
    return _SPELLING_RE.sub(
        lambda m: _SPELLING_LOOKUP[m.group().lower()], name
    )

def abbreviate_titles(name):
    return _TITLE_RE.sub(
        lambda m: _TITLE_LOOKUP[m.group().lower()], name
    )

def ensure_abbreviation_periods(name):
    return _ABBREV_RE.sub(
        lambda m: _ABBREV_LOOKUP[m.group(1).lower()], name
    )

def strip_redundant_honorifics(name):
    name = _RE_REDUNDANT_GRACE.sub('', name)
    name = _RE_REDUNDANT_HIGHNESS.sub('', name)
    name = _RE_REDUNDANT_EXCELLENCE.sub('', name)
    return name

def insert_peerage_of(name):
    return _RE_INSERT_PEERAGE_OF.sub(r'\1 of \2', name)

def strip_geographic_of(name):
    def _replace_of(match):
        preceding_text = name[:match.start()]
        preceding_words = preceding_text.rsplit(None, 1)
        if len(preceding_words) >= 1:
            last_word = preceding_words[-1].lower().rstrip(".")
            if last_word in _TITLES_THAT_TAKE_OF:
                return match.group(0)
        return " "
    return re.sub(r' of ', _replace_of, name)

def expand_name_abbreviations(name):
    tokens = name.split()
    expanded = []
    token_keys = {t.lower().rstrip(".") for t in tokens}
    has_masculine = bool(token_keys & _MASCULINE_SIGNALS)
    has_feminine = bool(token_keys & _FEMININE_SIGNALS)
    for i, token in enumerate(tokens):
        replacement = None
        if token.lower() in ("jn.", "jn"):
            replacement = "John"
        if replacement is None and token.lower() in ("fran.", "fran"):
            if has_masculine and not has_feminine:
                replacement = "Francis"
            elif has_feminine and not has_masculine:
                replacement = "Frances"
        if replacement is None:
            replacement = _NAME_ABBREV_LOOKUP.get(token.lower())
        expanded.append(replacement if replacement else token)
    return ' '.join(expanded)

def strip_leading_the(name):
    return _RE_LEADING_THE.sub('', name)

def strip_annotations(name):
    return _ANNOTATION_RE.sub('', name)

def strip_ditto_marks(name):
    return _RE_TRAILING_DITTO.sub('', name)

def normalize_dashes(name):
    name = _RE_LONG_DASH.sub('----', name)
    name = _RE_DASH_LETTER.sub(r'\1 \2', name)
    return name

def standardize_initials(name):
    name = _RE_INITIALS_NO_SPACE.sub(r'\1. \2.', name)
    name = _RE_BARE_INITIALS.sub(r'\1. ', name)
    name = _RE_BARE_INITIAL_AFTER_PERIOD.sub(r'\1. ', name)
    return name

def strip_trailing_punctuation(name):
    name = name.rstrip(':')
    if name.endswith('.'):
        last_token = name.rsplit(None, 1)[-1] if ' ' in name else name
        token_without_period = last_token.rstrip('.')
        is_known = token_without_period in KNOWN_ABBREVIATIONS
        is_short_abbrev = (
            len(last_token) <= 4 and _RE_SHORT_ABBREV.search(last_token)
        )
        if not is_known and not is_short_abbrev:
            name = name[:-1]
    return name

def clean_spurious_periods(name):
    name = _RE_DOUBLE_PERIOD.sub('.', name)
    name = _MID_PERIOD_RE.sub(r'\1 ', name)
    return name

def final_cleanup(name):
    return collapse_whitespace(name)


# ---------------------------------------------------------------------------
# Master normalization function.
# ---------------------------------------------------------------------------

def normalize_name(name):
    name = strip_commas_and_semicolons(name)
    name = name.replace("[?]", "")
    name = name.replace(" & ", " and ")
    name = repair_whitespace(name)
    name = collapse_whitespace(name)
    name = apply_spelling_corrections(name)
    name = abbreviate_titles(name)
    name = ensure_abbreviation_periods(name)
    name = strip_redundant_honorifics(name)
    name = insert_peerage_of(name)
    # Geographic "of" is now stripped in 04_parse_names.py, after location
    # extraction, so that both raw and normalized forms can be used to
    # detect locations like "Priestman of Malton".
    name = expand_name_abbreviations(name)
    name = strip_leading_the(name)
    name = strip_annotations(name)
    name = strip_ditto_marks(name)
    name = normalize_dashes(name)
    name = standardize_initials(name)
    name = strip_trailing_punctuation(name)
    name = clean_spurious_periods(name)
    name = final_cleanup(name)
    return name


# ---------------------------------------------------------------------------
# CSV I/O and main.
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Normalize subscriber names in the consolidated CSV."
    )
    parser.add_argument(
        "input_csv",
        help="Path to the consolidated CSV (from 01_ingest.py / 02_split_compounds.py)."
    )
    parser.add_argument(
        "--output", default="outputs/03-normalized.csv",
        help="Path for the normalized CSV output (default: outputs/03-normalized.csv)"
    )
    args = parser.parse_args()

    input_path = Path(args.input_csv)
    if not input_path.is_file():
        print(f"ERROR: {input_path} is not a file.")
        sys.exit(1)

    rows = []
    with open(input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            print(f"ERROR: {input_path} is missing columns: {missing}")
            sys.exit(1)
        fieldnames = list(reader.fieldnames)
        for row in reader:
            rows.append(row)

    print(f"Read {len(rows)} rows from {input_path}")

    norm_input_index = fieldnames.index("normalization input")
    output_fieldnames = (
        fieldnames[:norm_input_index + 1]
        + ["normalized_name"]
        + fieldnames[norm_input_index + 1:]
    )

    changed_count = 0
    for row in rows:
        original = row["normalization input"]
        normalized = normalize_name(original)
        row["normalized_name"] = normalized
        if original != normalized:
            changed_count += 1

    print(f"Normalized {changed_count} of {len(rows)} names "
          f"({len(rows) - changed_count} unchanged)")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=output_fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {output_path}")


if __name__ == "__main__":
    main()
