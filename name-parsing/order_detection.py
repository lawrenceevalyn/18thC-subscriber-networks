"""
================================================================================
       Bipartite Graph Pipeline for Eighteenth-Century Subscriber Lists
                            order_detection.py
================================================================================
DESCRIPTION:
    Per-list name-order detection. Subscriber lists are internally
    consistent: a whole list is either "Firstname Lastname" or
    "Lastname Firstname" (surname-first), but different lists differ, and
    the comma is not a reliable signal (some surname-first lists use no
    comma). This module decides which order a list uses by voting across
    its own entries, using two independent signals:

        1. Given-name position. After stripping titles and postnominals,
           we find the first token that is a known given name. If it sits
           at index 0 the entry votes "first-last"; at index >= 1 it votes
           "last-first". A leading/trailing bare initial is a weaker vote
           in the same directions.

        2. Alphabetization. Lists are conventionally sorted by surname. If
           the leading core tokens are (mostly) in alphabetical order the
           surname leads -> "last-first"; if the trailing core tokens are
           sorted the surname trails -> "first-last".

    The decision and its vote tallies are returned so callers can emit an
    audit column and log low-confidence lists. A per-list manual override
    (resources/list-overrides.csv) takes precedence over detection.

USAGE (as a library):
    from order_detection import load_given_names, detect_order
    gn = load_given_names()
    result = detect_order(list_of_normalized_names, gn)
    result["order"]  # "first-last" | "last-first"

LICENSE:
    MIT License
    Copyright (c) 2026 Lawrence Evalyn
================================================================================
"""

import csv
import re
from pathlib import Path

FIRST_LAST = "first-last"
LAST_FIRST = "last-first"

_RESOURCES_DIR = Path(__file__).parent / "resources"

# Title / postnominal tokens stripped (from ANYWHERE in the token list,
# because in surname-first lists the title sits after the surname, e.g.
# "Adam Mr. Henry"). Kept deliberately in sync with 04_parse_names.py.
_TITLE_TOKENS = {
    "mr.", "mrs.", "ms.", "miss", "rev.", "dr.", "capt.", "col.",
    "lt.", "adm.", "sgt.", "prof.", "hon.", "sir", "dame", "mme.",
    "messrs.", "gen.", "alderman", "major", "maj.", "right", "the",
}
_POSTNOMINAL_TOKENS = {
    "esq.", "esq", "bart.", "bart", "bt.", "jun.", "jun", "sen.", "sen",
    "m.d.", "m.p.", "d.d.", "f.r.s.", "ll.d.", "w.s.", "d.f.",
}

_RE_INITIAL = re.compile(r'^[A-Z]\.?$')

# A token that is nothing but dash characters. In several lists a leading
# dash repeats ("dittoes") the title from the line above, e.g.
# "— William Green" = "[Mr.] William Green". Left in place it shoves the
# given name to index 1 and flips the vote to last-first, so we drop it for
# detection. (The normalizer only collapses runs of 2+ dashes to "----",
# so a lone em-dash survives as its own token and must be caught here too.)
_RE_DASH_ONLY = re.compile(r'^[-–—]+$')


def load_given_names(resources_dir=_RESOURCES_DIR):
    """Load the given-name lexicon as a lowercase set."""
    path = Path(resources_dir) / "given-names.csv"
    names = set()
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            n = row["given_name"].strip().lower()
            if n:
                names.add(n)
    return names


def load_overrides(resources_dir=_RESOURCES_DIR):
    """Load per-list order overrides, keyed by list_key. Optional file.

    Expected columns: list_key, order  (order in {first-last, last-first}).
    Returns {} if the file is absent.
    """
    path = Path(resources_dir) / "list-overrides.csv"
    overrides = {}
    if not path.exists():
        return overrides
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row.get("list_key") or "").strip()
            order = (row.get("order") or "").strip().lower()
            if key and order in (FIRST_LAST, LAST_FIRST):
                overrides[key] = order
    return overrides


def _norm_token(tok):
    return tok.lower().strip(".,;:")


def core_tokens(normalized_name):
    """Strip title and postnominal tokens (from anywhere) -> name tokens."""
    toks = normalized_name.split()
    out = []
    for t in toks:
        low = t.lower()
        if low in _TITLE_TOKENS or low in _POSTNOMINAL_TOKENS:
            continue
        if _RE_DASH_ONLY.match(t):  # dittoed-title dash placeholder
            continue
        out.append(t)
    return out


def _vote_entry(normalized_name, given_names):
    """Return (FIRST_LAST | LAST_FIRST | None, strong: bool)."""
    toks = core_tokens(normalized_name)
    if len(toks) < 2:
        return None, False

    # Primary signal: position of the first known given name.
    for i, t in enumerate(toks):
        if _norm_token(t) in given_names:
            return (FIRST_LAST if i == 0 else LAST_FIRST), True

    # Weak signal: a bare initial at one end and not the other.
    first_init = bool(_RE_INITIAL.match(toks[0]))
    last_init = bool(_RE_INITIAL.match(toks[-1]))
    if first_init and not last_init:
        return FIRST_LAST, False
    if last_init and not first_init:
        return LAST_FIRST, False

    return None, False


def _sorted_fraction(seq):
    """Fraction of adjacent pairs that are non-decreasing (alphabetical)."""
    pairs = [(a, b) for a, b in zip(seq, seq[1:]) if a and b]
    if not pairs:
        return 0.0
    ok = sum(1 for a, b in pairs if a <= b)
    return ok / len(pairs)


def detect_order(normalized_names, given_names, list_key=None, overrides=None):
    """Decide the name order for one list.

    Returns a dict: order, confidence (high|low), source (override|votes|
    alphabetization|default), and the raw tallies for auditing/logging.
    """
    overrides = overrides or {}
    if list_key is not None and list_key in overrides:
        return {
            "order": overrides[list_key], "confidence": "high",
            "source": "override", "n_votes": 0, "fl": 0, "lf": 0,
            "alpha_lead": 0.0, "alpha_trail": 0.0,
        }

    fl = lf = 0
    lead_tokens, trail_tokens = [], []
    for name in normalized_names:
        toks = core_tokens(name)
        if len(toks) >= 2:
            lead_tokens.append(_norm_token(toks[0]))
            trail_tokens.append(_norm_token(toks[-1]))
        vote, strong = _vote_entry(name, given_names)
        weight = 2 if strong else 1
        if vote == FIRST_LAST:
            fl += weight
        elif vote == LAST_FIRST:
            lf += weight

    n = fl + lf
    alpha_lead = _sorted_fraction(lead_tokens)
    alpha_trail = _sorted_fraction(trail_tokens)

    order, confidence, source = FIRST_LAST, "low", "default"

    if n >= 5:
        frac_lf = lf / n
        if frac_lf >= 0.6:
            order, confidence, source = LAST_FIRST, "high", "votes"
        elif frac_lf <= 0.4:
            order, confidence, source = FIRST_LAST, "high", "votes"
        else:
            # Vote split: break the tie with alphabetization.
            if alpha_lead - alpha_trail >= 0.15:
                order, source = LAST_FIRST, "alphabetization"
            elif alpha_trail - alpha_lead >= 0.15:
                order, source = FIRST_LAST, "alphabetization"
    else:
        # Too few given-name votes: lean on alphabetization alone.
        if alpha_lead >= 0.9 and alpha_lead - alpha_trail >= 0.15:
            order, confidence, source = LAST_FIRST, "low", "alphabetization"
        elif alpha_trail >= 0.9 and alpha_trail - alpha_lead >= 0.15:
            order, confidence, source = FIRST_LAST, "low", "alphabetization"

    return {
        "order": order, "confidence": confidence, "source": source,
        "n_votes": n, "fl": fl, "lf": lf,
        "alpha_lead": round(alpha_lead, 3), "alpha_trail": round(alpha_trail, 3),
    }
