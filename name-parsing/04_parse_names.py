"""
================================================================================
       Bipartite Graph Pipeline for Eighteenth-Century Subscriber Lists
                            04_parse_names.py
================================================================================
RUN WITH: python3 04_parse_names.py outputs/03-normalized.csv
          python3 04_parse_names.py outputs/03-normalized.csv --output outputs/04-parsed.csv

DESCRIPTION:
    Decomposes each normalized subscriber name into structured fields.
    Reads the normalized CSV from 03_normalize.py and adds parsed
    component columns.

    Each name is classified into one of three tracks:

    Track A (titled): Names containing a positional title with "of"
        (e.g. "Duke of Bedford", "Bishop of London"). The entire title
        phrase becomes parsed_title; other personal-name fields are
        empty. A title_key is extracted for title-based matching.

    Track B (personal with title): Names with generic titles like
        "Mr.", "Rev.", "Capt." followed by personal names. Leading
        titles are consumed into parsed_title, trailing postnominals
        into parsed_postnominals, and the remainder is split into
        parsed_first and parsed_last.

    Track C (bare): Names without any recognized title. Parsed
        directly into first and last name.

    Location is recovered from the pre-normalization "normalization
    input" column, since 03_normalize.py strips geographic "of".

    New columns added:
        name_type          - "titled", "personal", or "bare"
        title_key          - lowercased title key for titled names
        parsed_title       - honorific/rank prefix
        parsed_first       - first name or initials
        parsed_last        - last name / surname
        parsed_postnominals - trailing qualifiers (Esq., M.D., etc.)
        parsed_location    - geographic qualifier
        parsed_notes       - annotations, copy counts, other notes

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

import importlib.util as _importlib_util

import order_detection

# 03_normalize.py can't be imported by name (leading digit), so load it by
# path. Used to re-normalize the isolated name core in surname-first parsing.
_norm_spec = _importlib_util.spec_from_file_location(
    "_normalize_for_parse", Path(__file__).parent / "03_normalize.py")
_normalize_mod = _importlib_util.module_from_spec(_norm_spec)
_norm_spec.loader.exec_module(_normalize_mod)
normalize_name = _normalize_mod.normalize_name


REQUIRED_COLUMNS = {"entry_id", "person_id", "normalization input", "normalized_name"}

PARSED_COLUMNS = [
    "name_type", "title_key",
    "parsed_title", "parsed_first", "parsed_last",
    "parsed_postnominals", "parsed_occupation", "parsed_affiliation",
    "parsed_location", "parsed_notes",
]


# ---------------------------------------------------------------------------
# Positional title detection (Track A).
#
# These are titles of office that identify a person by their position
# rather than their personal name. A positional title + "of" + place
# is treated as a single identity (e.g. "Duke of Bedford").
# ---------------------------------------------------------------------------

_POSITIONAL_RANKS = [
    "Dowager Duchess", "Dowager Marchioness", "Dowager Countess",
    "Dowager Viscountess", "Dowager Baroness",
    "Duchess", "Duke",
    "Marquess", "Marquis", "Marchioness",
    "Earl", "Countess",
    "Viscountess", "Visc\\.",
    "Baroness", "Baron",
    "Lord Bishop",
    "Archbishop", "Bishop",
    "Dean",
    "Lord Mayor",
    "Prince", "Princess",
]

_POSITIONAL_RE = re.compile(
    r'^(' + '|'.join(_POSITIONAL_RANKS) + r')\s+of\s+(.+)$',
    re.IGNORECASE,
)

# Unanchored version for detecting positional titles embedded within a
# personal name (e.g. "Pickett Lord Mayor of London").
_EMBEDDED_POSITIONAL_RE = re.compile(
    r'(' + '|'.join(_POSITIONAL_RANKS) + r')\s+of\s+(.+)$',
    re.IGNORECASE,
)

_BARE_LORD_RE = re.compile(
    r'^(Lord|Lady)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)$'
)

# First-word triggers for classification as a titled entry. Any name
# whose first token (case-insensitive, with any trailing period stripped)
# matches one of these is treated as Track A with the full normalized
# name as the title.
_FIRST_WORD_TITLE_TRIGGERS = {
    "duke", "duchess", "marquess", "marquis", "marchioness",
    "earl", "countess", "viscount", "viscountess", "visc",
    "baron", "baroness", "archbishop", "bishop", "dean",
    "prince", "princess", "lord", "lady", "dowager",
}


# Anonymous placeholder names ("A Young Gentleman" etc.) are treated as
# unmatchable: they receive name_type "anonymous" with no parsed fields,
# and the matchers skip them entirely.
_ANONYMOUS_RE = re.compile(
    r'^a\s+(?:young\s+)?(?:gentleman|lady)$',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Leading title tokens (Track B).
# ---------------------------------------------------------------------------

LEADING_TITLES = {
    "mr.", "mrs.", "ms.", "miss", "rev.", "dr.", "capt.", "col.",
    "lt.", "adm.", "sgt.", "prof.", "hon.", "sir", "dame", "mme.",
    "messrs.", "gen.", "alderman", "major", "maj.",
}

LEADING_TITLE_COMBOS = {
    "lt. gen.", "lt. col.", "right hon.", "right rev.",
}


# ---------------------------------------------------------------------------
# Postnominal tokens.
# ---------------------------------------------------------------------------

POSTNOMINALS = {
    "esq.", "bart.", "bt.", "jun.", "sen.",
    "m.d.", "m.p.", "d.d.", "f.r.s.", "ll.d.",
    "w.s.", "d.f.",
}

_POSTNOMINAL_RE = re.compile(
    r'\b(' + '|'.join(re.escape(p) for p in sorted(POSTNOMINALS, key=len, reverse=True)) + r')\b',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Annotation patterns (copy counts, regiment info, etc.).
# ---------------------------------------------------------------------------

# Load spelling corrections so we can normalise location tokens that were
# corrected by the normalizer (e.g. raw "Ashburne" → normalized "Ashbourne").
def _load_spelling_pairs():
    csv_path = Path(__file__).parent / "resources" / "spelling-corrections.csv"
    pairs = {}
    if csv_path.exists():
        with open(csv_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # key is lowercase for case-insensitive lookup; value preserves original case
                pairs[row['misspelling'].lower()] = row['correction']
    return pairs

_SPELLING_PAIRS = _load_spelling_pairs()


def _apply_spelling_to_location(location):
    """Apply word-level spelling corrections to an extracted location string."""
    if not location or not _SPELLING_PAIRS:
        return location
    return ' '.join(_SPELLING_PAIRS.get(w.lower(), w) for w in location.split())


# ---------------------------------------------------------------------------
# Occupation and affiliation lexicons (typed trailing attributes).
#
# Trailing segments after a name core can be a location, an occupation
# ("advocate", "bookseller"), an institutional affiliation ("Inner Temple",
# "T.C.D"), a postnominal, or a non-identifying note (copies, ditto). These
# lexicons let the residual classifier sort them into typed columns.
# ---------------------------------------------------------------------------

def _load_occupations():
    path = Path(__file__).parent / "resources" / "occupations.csv"
    occ = set()
    if path.exists():
        with open(path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                w = row['occupation'].strip().lower()
                if w:
                    occ.add(w)
    return occ

_OCCUPATIONS = _load_occupations()

# Institutional affiliations. Matched case-insensitively against a residual
# segment; the matched text becomes parsed_affiliation.
_AFFILIATION_RE = re.compile(
    r'\b('
    r'(?:Inner|Middle) Temple|Lincoln\'?s Inn|Gray\'?s Inn'
    r'|Royal Navy|Royal Artillery|Royal Society'
    r'|Trinity Coll(?:ege|\.)?|Queen\'?s Coll(?:ege|\.)?|King\'?s Coll(?:ege|\.)?'
    r'|\w+ Coll(?:ege|\.)|T\.?\s?C\.?\s?D\.?'
    r'|\d+\w*\s+regiment'
    r')\b',
    re.IGNORECASE,
)


def _classify_residual_segment(seg):
    """Classify one trailing segment -> (type, value).

    type in {affiliation, occupation, postnominal, ditto, note, location, ""}.
    Returns ("", "") when the segment is empty after cleaning.
    """
    seg = seg.strip().rstrip(".,;: ")
    if not seg:
        return "", ""

    # Bare ditto -> sentinel (resolved from the line above by a later pass).
    if re.fullmatch(r'(?:\d+\s+)?(?:ditto|do\.?)', seg, re.IGNORECASE):
        return "ditto", "ditto"

    # Quantity / copy counts -> non-identifying note.
    if _RE_COPY_COUNT.search(seg):
        return "note", seg

    aff = _AFFILIATION_RE.search(seg)
    if aff:
        return "affiliation", aff.group(0)

    words = seg.split()
    bare = [w.lower().rstrip(".") for w in words]

    # Pure postnominal segment ("esq", "Bart.").
    if all(w in _KNOWN_NON_LOCATIONS for w in bare):
        if any(w in {"esq", "bart", "jun", "sen"} for w in bare):
            return "postnominal", seg
        return "note", seg

    # Degree / lettered postnominal ("M. D.", "A. B.", "LL. D.", "F. R. S.").
    # Every word is one or two capital letters; caught before the location
    # rule so capitalised degrees don't masquerade as place names. The
    # parsed_postnominals column is populated separately by the whole-name
    # scan, so these are dropped here.
    if all(re.fullmatch(r'[A-Za-z]{1,2}', w.rstrip(".")) and w.rstrip(".").isupper()
           for w in words):
        return "postnominal", seg

    # Occupation: any word matches the lexicon (handles "Surveyor & agent").
    if any(w in _OCCUPATIONS for w in bare):
        return "occupation", seg

    # Location: every word is capitalised (place names, street names).
    if all(w and w[0].isupper() for w in words):
        return "location", _apply_spelling_to_location(seg)

    return "note", seg


_RE_COPY_COUNT = re.compile(
    r'\b(\d+\s+(?:cop(?:y|ies|\.)|copes?|books?|sets?|do\.?))\b',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Location extraction from raw (pre-normalization) input.
#
# The normalizer strips geographic "of" but preserves title "of".
# We parse the raw input to recover the location that was stripped.
# ---------------------------------------------------------------------------

_TITLES_BEFORE_OF = {
    "duke", "duchess", "marquess", "marquis", "marchioness",
    "earl", "countess", "visc.", "viscountess", "visc",
    "baron", "baroness", "bishop", "archbishop", "dean",
    "mayor", "dowager", "prince", "princess", "son",
}

_RE_ANNOTATIONS_STRIP = re.compile(
    r'\b\d+\s+(?:cop(?:y|ies|\.)|copes?|books?|sets?|do\.?)\b.*$',
    re.IGNORECASE,
)

_KNOWN_NON_LOCATIONS = {
    "esq", "esq.", "bart", "bart.", "jun", "jun.", "sen", "sen.",
    "ditto", "do", "do.",
}

def _extract_location_from_raw(raw_input):
    # Method 1: look for geographic "of PLACE" in the raw input.
    cleaned = raw_input.replace(",", " ").replace(";", " ")
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    parts = re.split(r'\bof\b', cleaned, flags=re.IGNORECASE)
    if len(parts) >= 2:
        for i in range(1, len(parts)):
            before = parts[i - 1].strip()
            after = parts[i].strip()
            if not before or not after:
                continue

            last_word = before.rsplit(None, 1)[-1].lower().rstrip(".")
            if last_word in _TITLES_BEFORE_OF:
                continue

            if after.lower().startswith("the ") or after.lower().startswith("ditto"):
                continue

            location = _RE_ANNOTATIONS_STRIP.sub('', after).strip()
            location = location.rstrip(".,;: ")

            if location:
                return _apply_spelling_to_location(location)

    # Method 2: look for a comma-separated location that follows a
    # postnominal. Handles "Wm. Shore, Esq. Sheffield, 12 copies"
    # where no "of" is used. Only triggers when a segment contains
    # a postnominal followed by a single capitalized word.
    _POSTNOMINAL_WORDS = {"esq", "esq.", "bart", "bart.", "jun", "jun.", "sen", "sen.", "m.p.", "m.d."}
    _POSTNOMINAL_BARE = {"esq", "bart", "jun", "sen"}
    segments = re.split(r'[,;]', raw_input)
    for k, seg in enumerate(segments):
        seg = seg.strip()
        if not seg:
            continue
        seg_clean = _RE_ANNOTATIONS_STRIP.sub('', seg).strip().rstrip(".,;: ")
        words = seg_clean.split()
        # Within-segment: POSTNOMINAL + PLACE_NAME at end of segment
        for j in range(len(words) - 1):
            if words[j].lower().rstrip(".") in _POSTNOMINAL_BARE or words[j].lower() in _POSTNOMINAL_WORDS:
                trailing = words[j + 1:]
                if trailing and all(w[0].isupper() and w.isalpha() for w in trailing):
                    candidate = " ".join(trailing)
                    if candidate.lower() not in _KNOWN_NON_LOCATIONS:
                        return _apply_spelling_to_location(candidate)

        # Cross-segment: this segment is purely a postnominal (e.g. "Esq" alone
        # after a semicolon), so look at the next non-empty segment for a place name.
        # Handles "William Penrose, Esq; Waterford" where ";" separates "Esq" from
        # "Waterford".
        if words and words[-1].lower().rstrip(".") in _POSTNOMINAL_BARE and len(words) == 1:
            for next_seg in segments[k + 1:]:
                next_clean = next_seg.strip().rstrip(".,;: ")
                if not next_clean:
                    continue
                next_words = next_clean.split()
                if next_words and all(w[0].isupper() and w.isalpha() for w in next_words):
                    candidate = " ".join(next_words)
                    if candidate.lower() not in _KNOWN_NON_LOCATIONS:
                        return _apply_spelling_to_location(candidate)
                break

    return ""


# ---------------------------------------------------------------------------
# Annotation extraction from raw input.
# ---------------------------------------------------------------------------

def _extract_notes_from_raw(raw_input):
    notes = []

    copy_match = _RE_COPY_COUNT.search(raw_input)
    if copy_match:
        notes.append(copy_match.group(1).strip())

    if re.search(r'\bditto\b', raw_input, re.IGNORECASE):
        notes.append("ditto")

    if re.search(r'\bregiment\b', raw_input, re.IGNORECASE):
        regiment_match = re.search(r'(\d+\w*\s+regiment\b)', raw_input, re.IGNORECASE)
        if regiment_match:
            notes.append(regiment_match.group(1))

    if "the son of" in raw_input.lower():
        son_match = re.search(r'the\s+son\s+of\s+(.+?)(?:,|$)', raw_input, re.IGNORECASE)
        if son_match:
            notes.append(f"son of {son_match.group(1).strip().rstrip('.,;')}")

    of_the_match = re.search(r'\bof the (Royal Navy|Inner Temple|Middle Temple)\b', raw_input, re.IGNORECASE)
    if of_the_match:
        notes.append(of_the_match.group(0).strip())

    return "; ".join(notes)


# ---------------------------------------------------------------------------
# Name parsing.
# ---------------------------------------------------------------------------

def _is_initial(token):
    return bool(re.match(r'^[A-Z]\.$', token))


def _consume_leading_titles(tokens):
    titles = []
    i = 0

    while i < len(tokens):
        if i + 1 < len(tokens):
            combo = f"{tokens[i].lower()} {tokens[i+1].lower()}"
            if combo in LEADING_TITLE_COMBOS:
                titles.append(f"{tokens[i]} {tokens[i+1]}")
                i += 2
                continue

        if tokens[i].lower() in LEADING_TITLES:
            titles.append(tokens[i])
            i += 1
        else:
            break

    return " ".join(titles), tokens[i:]


_SPACED_POSTNOMINALS = {"m. d.", "m. p.", "d. d.", "l. l. d.", "w. s.", "d. f.", "r. a."}

def _consume_trailing_postnominals(tokens):
    postnominals = []
    while tokens:
        if tokens[-1].lower() in POSTNOMINALS:
            postnominals.insert(0, tokens[-1])
            tokens = tokens[:-1]
        elif len(tokens) >= 2 and f"{tokens[-2].lower()} {tokens[-1].lower()}" in _SPACED_POSTNOMINALS:
            postnominals.insert(0, f"{tokens[-2]} {tokens[-1]}")
            tokens = tokens[:-2]
        else:
            break
    return " ".join(postnominals), tokens


def _extract_postnominals_anywhere(tokens):
    """Extract postnominals from anywhere in the token list.

    In the normalized name, postnominals can appear mid-name when
    followed by a location or other qualifier (e.g. "Cooper Esq.
    Manchester"). This scans for known postnominal tokens and extracts
    them regardless of position, returning (postnominals, remaining).
    """
    postnominals = []
    remaining = []

    i = 0
    while i < len(tokens):
        if i + 1 < len(tokens) and f"{tokens[i].lower()} {tokens[i+1].lower()}" in _SPACED_POSTNOMINALS:
            postnominals.append(f"{tokens[i]} {tokens[i+1]}")
            i += 2
        elif tokens[i].lower() in POSTNOMINALS:
            postnominals.append(tokens[i])
            i += 1
        else:
            remaining.append(tokens[i])
            i += 1

    return " ".join(postnominals), remaining


def _split_personal_name(tokens):
    if not tokens:
        return "", ""

    if len(tokens) == 1:
        tok = tokens[0]
        if _is_initial(tok) or tok == "----":
            return tok, ""
        return "", tok

    first_parts = []
    i = 0
    while i < len(tokens) and (_is_initial(tokens[i]) or tokens[i] == "----"):
        first_parts.append(tokens[i])
        i += 1

    if first_parts and i < len(tokens):
        return " ".join(first_parts), " ".join(tokens[i:])

    if not first_parts and len(tokens) >= 2:
        return tokens[0], " ".join(tokens[1:])

    if first_parts and i == len(tokens):
        return " ".join(first_parts), ""

    return "", " ".join(tokens)


def _strip_location_from_end(tokens, location):
    """Remove location tokens from the end of a token list.

    The normalizer replaces ' of PLACE' with ' PLACE', so the location
    appears as trailing tokens in the normalized name. This function
    strips those tokens. Handles spelling-correction mismatches by
    comparing lowercased forms and allowing for the normalizer's
    corrections (e.g. raw "Ashburne" → normalized "Ashbourne").
    """
    if not location or not tokens:
        return tokens

    loc_tokens = location.lower().split()
    name_end = [t.lower() for t in tokens[-len(loc_tokens):]]

    if name_end == loc_tokens:
        return tokens[:-len(loc_tokens)]

    if len(loc_tokens) == 1 and tokens:
        if tokens[-1].lower() == loc_tokens[0]:
            return tokens[:-1]
        for spelling_src, spelling_dst in _SPELLING_PAIRS.items():
            adjusted = loc_tokens[0].replace(spelling_src, spelling_dst)
            if tokens[-1].lower() == adjusted:
                return tokens[:-1]

    return tokens


def parse_name(normalized_name, raw_input, order=order_detection.FIRST_LAST):
    """Dispatch to the order-appropriate core parser.

    The shared scaffold (anonymous names, positional/peerage titles) is
    order-invariant and runs first. Only the personal-name core — title /
    first / last and where the trailing attributes begin — depends on
    whether the list is "Firstname Lastname" or surname-first.
    """
    result = {col: "" for col in PARSED_COLUMNS}

    if not normalized_name or not normalized_name.strip():
        result["name_type"] = "bare"
        return result

    name = normalized_name.strip()

    # --- Anonymous placeholder names (shared) ---
    # "A Gentleman", "A Young Gentleman", "A Lady", "A Young Lady" are
    # not real names and must never match anything else.
    if _ANONYMOUS_RE.match(name):
        result["name_type"] = "anonymous"
        result["parsed_notes"] = _extract_notes_from_raw(raw_input)
        return result

    # --- Track A: positional titles (shared) ---
    m = _POSITIONAL_RE.match(name)
    if m:
        result["name_type"] = "titled"
        full_title = f"{m.group(1)} of {m.group(2)}"
        result["parsed_title"] = full_title
        result["title_key"] = full_title.lower()
        result["parsed_notes"] = _extract_notes_from_raw(raw_input)
        return result

    # Check for bare "Lord/Lady Surname" (barons listed without "of")
    m = _BARE_LORD_RE.match(name)
    if m:
        title_word = m.group(1)
        place_or_name = m.group(2)
        result["name_type"] = "titled"
        result["parsed_title"] = f"{title_word} {place_or_name}"
        result["title_key"] = f"{title_word} {place_or_name}".lower()
        result["parsed_notes"] = _extract_notes_from_raw(raw_input)
        return result

    # --- Track B/C: personal names (order-dependent) ---
    if order == order_detection.LAST_FIRST:
        return _parse_personal_surname_first(name, normalized_name, raw_input)
    return _parse_personal_first_last(name, normalized_name, raw_input)


def _parse_personal_surname_first(name, normalized_name, raw_input):
    """Parse a personal name from a surname-first list.

    The raw input's first comma/semicolon marks the end of the name core,
    so locations and other trailing attributes never get absorbed into the
    given name. Within the core: surname = first token, an optional title
    follows it, and the remainder is the given name(s).
    """
    result = {col: "" for col in PARSED_COLUMNS}

    segments = [s.strip() for s in re.split(r"[,;]", raw_input) if s.strip()]
    core_raw = segments[0] if segments else raw_input
    core_tokens = normalize_name(core_raw).split()

    # Degenerate core (e.g. comma-led junk): fall back to first-last.
    if not core_tokens:
        return _parse_personal_first_last(name, normalized_name, raw_input)

    surname = core_tokens[0]
    after = core_tokens[1:]
    title, givens = _consume_leading_titles(after)
    # A postnominal can sit inside the core ("Bell Edward Esq.").
    _core_postnoms, givens = _consume_trailing_postnominals(givens)

    residual_segments = segments[1:]

    # Format (b): "Surname, Title First, ..." — the comma falls right after the
    # surname, so the title and given name sit in the next segment. When the
    # core was the bare surname and that segment begins with a title, fold the
    # title + given name into the core. Given-name consumption stops at the
    # first occupation/postnominal, so "mr. surgeon" yields title=Mr. with the
    # occupation pushed back for classification rather than mistaken for a name.
    if not title and not givens and len(core_tokens) == 1 and residual_segments:
        cont_title, cont_rest = _consume_leading_titles(
            normalize_name(residual_segments[0]).split())
        if cont_title:
            # Title present: the token(s) after it are the given name, up to
            # the first occupation/postnominal ("mr. John" / "mr. surgeon").
            title = cont_title
            k = 0
            while k < len(cont_rest):
                low = cont_rest[k].lower().rstrip(".")
                if low in _OCCUPATIONS or low in {"esq", "bart", "jun", "sen"}:
                    break
                k += 1
            givens = cont_rest[:k]
            leftover = " ".join(cont_rest[k:])
            residual_segments = residual_segments[1:]
            if leftover:
                residual_segments = [leftover] + residual_segments
            elif not givens and residual_segments:
                # Title-only segment ("..., Mr, W. printer"): a leading initial
                # in the following segment is the given name. Only initials are
                # peeled here — a bare word could be a place, so it is left for
                # attribute classification.
                nxt = residual_segments[0].split()
                p = 0
                while p < len(nxt) and _is_initial(nxt[p]):
                    p += 1
                if p:
                    givens = nxt[:p]
                    rest_seg = " ".join(nxt[p:])
                    residual_segments = (
                        ([rest_seg] if rest_seg else []) + residual_segments[1:])
        elif cont_rest and _is_initial(cont_rest[0]):
            # No title, but a leading initial ("Freer, W. Surgeon"): the
            # initial(s) are the given name; the rest is an attribute.
            p = 0
            while p < len(cont_rest) and _is_initial(cont_rest[p]):
                p += 1
            givens = cont_rest[:p]
            leftover = " ".join(cont_rest[p:])
            residual_segments = (
                ([leftover] if leftover else []) + residual_segments[1:])

    # Type the trailing comma-segments into occupation / affiliation /
    # location / note. A bare ditto is kept as a sentinel in the location
    # slot (the field it most often stands in for) so a later ditto-
    # resolution pass can fill it from the line above.
    location_parts, occupation, affiliation, other_notes = [], "", "", []
    for seg in residual_segments:
        typ, val = _classify_residual_segment(seg)
        if typ == "location":
            location_parts.append(val)
        elif typ == "ditto":
            location_parts.append("ditto")
        elif typ == "occupation" and not occupation:
            occupation = val
        elif typ == "affiliation" and not affiliation:
            affiliation = val
        elif typ == "note":
            other_notes.append(val)

    location = ", ".join(location_parts)
    if not location:  # fall back to "of PLACE" hiding in the core
        location = _extract_location_from_raw(raw_input)

    postnominals, _ = _extract_postnominals_anywhere(normalized_name.split())

    notes = "; ".join(other_notes)
    son = re.search(r'the\s+son\s+of\s+(.+?)(?:,|$)', raw_input, re.IGNORECASE)
    if son:
        rel = "son of " + son.group(1).strip().rstrip(".,;")
        notes = f"{notes}; {rel}" if notes else rel

    result["name_type"] = "personal" if title else "bare"
    result["parsed_title"] = title
    result["parsed_first"] = " ".join(givens)
    result["parsed_last"] = surname
    result["parsed_postnominals"] = postnominals
    result["parsed_occupation"] = occupation
    result["parsed_affiliation"] = affiliation
    result["parsed_location"] = location
    result["parsed_notes"] = notes
    return result


def _parse_personal_first_last(name, normalized_name, raw_input):
    result = {col: "" for col in PARSED_COLUMNS}

    # The raw input's first comma/semicolon ends the name core; the trailing
    # segments are typed attributes (occupation, location, …) rather than part
    # of the surname. Parsing title/first/last from the core (seg0) keeps those
    # out of the last name. With no comma the core is the whole entry, so
    # comma-free entries parse exactly as before.
    segments = [s.strip() for s in re.split(r"[,;]", raw_input) if s.strip()]
    if len(segments) > 1 and normalize_name(segments[0]).strip():
        core_raw = segments[0]
        core_norm = normalize_name(core_raw)
        residual_segments = segments[1:]
    else:
        core_raw, core_norm, residual_segments = raw_input, name, []

    # --- Track B/C: personal names ---
    tokens = core_norm.split()

    title, remaining = _consume_leading_titles(tokens)

    # After consuming leading titles like "Right Hon.", the remainder
    # may be a positional title (e.g. "the Earl of Ailesbury"). Strip
    # a leading "the" and re-check for Track A.
    rest_str = " ".join(remaining)
    rest_stripped = re.sub(r'^the\s+', '', rest_str, flags=re.IGNORECASE)
    m = _POSITIONAL_RE.match(rest_stripped)
    if not m:
        m = _BARE_LORD_RE.match(rest_stripped)
    if m:
        result["name_type"] = "titled"
        full_title = rest_stripped
        if title:
            full_title = f"{title} {rest_stripped}"
        result["parsed_title"] = full_title
        result["title_key"] = rest_stripped.lower()
        result["parsed_notes"] = _extract_notes_from_raw(raw_input)
        return result

    # First-word title trigger: if the first remaining token is a
    # positional-rank keyword (Lord, Lady, Duke, Dowager, etc.), treat
    # the whole remainder as a title.
    if rest_stripped:
        first_word = rest_stripped.split()[0].lower().rstrip('.')
        if first_word in _FIRST_WORD_TITLE_TRIGGERS:
            result["name_type"] = "titled"
            full_title = rest_stripped
            if title:
                full_title = f"{title} {rest_stripped}"
            result["parsed_title"] = full_title
            result["title_key"] = rest_stripped.lower()
            result["parsed_notes"] = _extract_notes_from_raw(raw_input)
            return result

    # Strip location BEFORE postnominals, because the normalizer
    # places location tokens at the very end (after postnominals).
    # Scoped to the core so a comma-separated location is left for the
    # residual classifier instead of being stripped from the wrong tokens.
    location = _extract_location_from_raw(core_raw)
    if not location:
        location = _extract_location_from_raw(core_norm)
    remaining = _strip_location_from_end(remaining, location)
    # Strip geographic "of" from remaining tokens (previously done in
    # 03_normalize.py but moved here so location extraction sees it).
    remaining = [t for t in remaining if t.lower() != "of"]

    # Try consuming postnominals from the end first.
    postnominals, remaining = _consume_trailing_postnominals(remaining)

    # If that didn't find any, scan for postnominals anywhere in the
    # remaining tokens. This handles cases like "Cooper Esq. Manchester"
    # where Esq. appears mid-name because of a trailing location that
    # wasn't extracted via "of".
    if not postnominals:
        postnominals, remaining = _extract_postnominals_anywhere(remaining)

    # Check for an embedded positional title in the remaining tokens.
    # E.g. "Pickett Lord Mayor of London" → "Lord Mayor of London"
    # goes into parsed_notes, not parsed_last.
    remaining_str = " ".join(remaining)
    embedded_title_match = _EMBEDDED_POSITIONAL_RE.search(remaining_str)
    if embedded_title_match:
        before_title = remaining_str[:embedded_title_match.start()].strip()
        remaining = before_title.split() if before_title else []
        notes_extra = embedded_title_match.group(0)
    else:
        # Also handle bare positional titles without "of" (e.g. "Lord Mayor")
        bare_title_match = re.search(
            r'\b(Lord Mayor|Archdeacon|Lord Bishop)\b',
            remaining_str, re.IGNORECASE,
        )
        if bare_title_match:
            before_title = remaining_str[:bare_title_match.start()].strip()
            remaining = before_title.split() if before_title else []
            notes_extra = bare_title_match.group(0)
        else:
            notes_extra = ""

    first_name, last_name = _split_personal_name(remaining)

    # Type the trailing comma-segments (everything after the core) into
    # occupation / affiliation / location, mirroring the surname-first path.
    # Notes still come from the whole-entry scan below, so they are not
    # double-counted here.
    location_parts, occupation, affiliation, residual_postnoms = [], "", "", []
    for seg in residual_segments:
        typ, val = _classify_residual_segment(seg)
        if typ == "location":
            location_parts.append(val)
        elif typ == "ditto":
            location_parts.append("ditto")
        elif typ == "occupation" and not occupation:
            occupation = val
        elif typ == "affiliation" and not affiliation:
            affiliation = val
        elif typ == "postnominal":
            residual_postnoms.append(val)
    if not location and location_parts:
        location = ", ".join(location_parts)
    if not location:  # last resort: an "of PLACE" sitting after a comma
        location = _extract_location_from_raw(raw_input)
    if not postnominals and residual_postnoms:
        postnominals = " ".join(residual_postnoms)

    notes = _extract_notes_from_raw(raw_input)
    if notes_extra:
        notes = f"{notes_extra}; {notes}" if notes else notes_extra

    result["name_type"] = "personal" if title else "bare"
    result["parsed_title"] = title
    result["parsed_first"] = first_name
    result["parsed_last"] = last_name
    result["parsed_postnominals"] = postnominals
    result["parsed_occupation"] = occupation
    result["parsed_affiliation"] = affiliation
    result["parsed_location"] = location
    result["parsed_notes"] = notes

    return result


# ---------------------------------------------------------------------------
# CSV I/O and main.
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Parse normalized subscriber names into structured fields."
    )
    parser.add_argument(
        "input_csv",
        help="Path to the normalized CSV (from 03_normalize.py)."
    )
    parser.add_argument(
        "--output", default="outputs/04-parsed.csv",
        help="Path for the parsed CSV output (default: outputs/04-parsed.csv)"
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

    norm_index = fieldnames.index("normalized_name")
    output_fieldnames = (
        fieldnames[:norm_index + 1]
        + ["name_order"]
        + PARSED_COLUMNS
        + fieldnames[norm_index + 1:]
    )

    # --- Pass 1: detect name order per list ---------------------------------
    # A "list" is one (book, author, edition); each is internally consistent
    # in its name order. We detect the order once per list and record it as
    # an audit column. (Parsing still uses the legacy first-last split for
    # now; Phase 2 will branch on this value.)
    given_names = order_detection.load_given_names()
    overrides = order_detection.load_overrides()

    def list_key_of(row):
        return f"{row.get('author','')}|{row.get('book','')}|{row.get('edition','')}"

    lists = {}
    for row in rows:
        lists.setdefault(list_key_of(row), []).append(row)

    order_by_key = {}
    print(f"\nDetecting name order across {len(lists)} list(s):")
    for key, list_rows in lists.items():
        normed = [r["normalized_name"] for r in list_rows]
        res = order_detection.detect_order(
            normed, given_names, list_key=key, overrides=overrides,
        )
        order_by_key[key] = res["order"]
        flag = "" if res["confidence"] == "high" else "  <-- LOW CONFIDENCE, review"
        print(f"  {key}: {res['order']} "
              f"({res['source']}, fl={res['fl']} lf={res['lf']}, "
              f"alpha_lead={res['alpha_lead']}/{res['alpha_trail']}){flag}")

    # --- Pass 2: parse each name --------------------------------------------
    counts = {"titled": 0, "personal": 0, "bare": 0, "anonymous": 0}

    for row in rows:
        order = order_by_key[list_key_of(row)]
        row["name_order"] = order
        parsed = parse_name(
            row["normalized_name"],
            row["normalization input"],
            order=order,
        )
        for col in PARSED_COLUMNS:
            row[col] = parsed[col]
        counts[parsed["name_type"]] += 1

    print(f"Parsed: {counts['titled']} titled, "
          f"{counts['personal']} personal, {counts['bare']} bare, "
          f"{counts['anonymous']} anonymous")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=output_fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {output_path}")


if __name__ == "__main__":
    main()
