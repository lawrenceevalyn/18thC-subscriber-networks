"""
================================================================================
       Bipartite Graph Pipeline for Eighteenth-Century Subscriber Lists
                        06_match_components.py
================================================================================
RUN WITH: python3 06_match_components.py outputs/04-parsed.csv

DESCRIPTION:
    Matches non-titled subscriber entries using hardcoded rules designed
    around the structure of eighteenth-century subscriber names.

    Title compatibility:
        Mr., Esq., and bare (no title) are always equivalent, in both
        within-book and cross-book matching.
        Rev. and Rev. Mr. are always equivalent.
        Esq. is treated as an effective title (promoted from
        postnominals) for distinctiveness checks.
        All other title mismatches block matching.

    First name:
        Two full names must match exactly (after prior normalization).
        A bare initial is compatible with a full name starting with that
        letter; conflicting initials block matching.
        Missing first names need strong signals elsewhere.

    Last name:
        Fuzzy threshold scales with name length and is higher when other
        fields are strong (exact title + exact first).

    Location:
        A strong signal equivalent in weight to title.  Conflicting
        locations block matching.

    Postnominals:
        Supporting signal when present; never blocks a match.

    Cross-book matching:
        Names with non-distinctive titles (Mr., Mrs., Miss, Esq., bare)
        require a matching location or postnominal.

    Coexistence blocks:
        If two name patterns coexist in the same edition (sharing a
        last name and effective title, but differing in first-name
        specificity or postnominals), they are treated as different
        people everywhere, not just in that edition.

    Same-edition entries can never match each other.

    Entries already matched by 05_match_titles.py are excluded.

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
from collections import defaultdict

try:
    from rapidfuzz.distance import Levenshtein
    def levenshtein_distance(a, b):
        return Levenshtein.distance(a, b)
except ImportError:
    def levenshtein_distance(a, b):
        if len(a) < len(b):
            return levenshtein_distance(b, a)
        if len(b) == 0:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a):
            curr = [i + 1]
            for j, cb in enumerate(b):
                cost = 0 if ca == cb else 1
                curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
            prev = curr
        return prev[-1]


REQUIRED_COLUMNS = {
    "entry_id", "person_id", "name_type",
    "parsed_title", "parsed_first", "parsed_last",
    "parsed_postnominals", "parsed_location",
    "normalized_name", "book", "edition", "year",
}

MATCH_COLUMNS = [
    "group_id", "match", "entry_id", "person_id",
    "normalized_name", "listed as",
    "parsed_title", "parsed_first", "parsed_last",
    "parsed_postnominals", "parsed_occupation", "parsed_affiliation",
    "parsed_location",
    "book", "edition", "year", "match_rule", "match_tier",
]

_SURNAME_PREFIXES = ("de la ", "de ", "du ", "la ", "le ", "van ", "von ")

def _strip_surname_prefix(name):
    for prefix in _SURNAME_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


NON_DISTINCTIVE_TITLES = {"mr.", "mrs.", "miss", "esq.", ""}

# Titles treated as interchangeable when deciding whether two entries refer to
# the same person: Mr., Esq., and bare (no title) are always equivalent, the
# same way whether the entries come from the same book or different books.
# (Esq. is promoted from postnominals to an effective title before comparison;
# see _effective_title.)
EQUIV_TITLES = {"mr.", "esq.", ""}


def _normalize_title(raw_title):
    """Lowercase and strip whitespace for comparison."""
    return raw_title.strip().lower()


def _strip_mr(title):
    """Remove 'Mr.' from a compound title for Rev. Mr. equivalence."""
    return " ".join(t for t in title.split() if t != "mr.").strip()


def _effective_title(entry):
    """Return the effective title, promoting Esq. from postnominals."""
    title = entry.get("parsed_title", "").strip()
    if not title and "esq" in entry.get("parsed_postnominals", "").lower():
        return "Esq."
    return title


def titles_compatible(title_a, title_b):
    """Check whether two titles are compatible per the matching rules.

    Mr., Esq., and bare (no title) are equivalent; Rev. and Rev. Mr. are
    equivalent; every other title mismatch is a definite non-match. This
    holds the same way whether the two entries come from the same book or
    from different books.

    Returns True if compatible, False if a definite non-match.
    """
    a = _normalize_title(title_a)
    b = _normalize_title(title_b)

    if a == b:
        return True

    if a in EQUIV_TITLES and b in EQUIV_TITLES:
        return True

    if _strip_mr(a) == _strip_mr(b):
        return True

    return False


def _max_first_name_distance(name):
    length = len(name)
    if length <= 3:
        return 1
    elif length <= 6:
        return 2
    else:
        return 3


def first_names_compatible(first_a, first_b):
    """Check whether two first names are compatible.

    Returns one of:
        "exact"      - two full names that match exactly
        "fuzzy"      - two full names within scaled edit distance
        "initial"    - bare initial compatible with a full name or matching initial
        "missing"    - one or both first names are empty
        "conflict"   - definite non-match
    """
    a = first_a.strip().lower()
    b = first_b.strip().lower()

    if not a or not b:
        return "missing"

    a_is_initial = _is_bare_initial(a)
    b_is_initial = _is_bare_initial(b)

    if not a_is_initial and not b_is_initial:
        if a == b:
            return "exact"
        if a[0] == b[0]:
            dist = levenshtein_distance(a, b)
            allowed = _max_first_name_distance(min(a, b, key=len))
            if dist <= allowed:
                return "fuzzy"
        return "conflict"

    if a_is_initial and b_is_initial:
        if a[0] == b[0]:
            return "initial"
        return "conflict"

    # One initial, one full name.
    initial = a if a_is_initial else b
    full = b if a_is_initial else a
    if full.startswith(initial[0]):
        return "initial"
    return "conflict"


def _is_bare_initial(name):
    """Check if a name is a bare initial like 'J' or 'J.'"""
    cleaned = name.replace(".", "").strip()
    return len(cleaned) == 1


def _is_multi_initial(name, min_count=3):
    """Check if a name is multiple initials like 'R. L. B.' or 'J. C.'"""
    parts = name.replace(".", " ").split()
    return len(parts) >= min_count and all(len(p) == 1 for p in parts)


def locations_compatible(loc_a, loc_b):
    """Check whether two locations are compatible.

    Returns one of:
        "match"    - both present and identical (after hyphen normalization)
        "missing"  - one or both are empty
        "conflict" - definite non-match
    """
    a = loc_a.strip().lower().replace("-", "")
    b = loc_b.strip().lower().replace("-", "")

    if not a or not b:
        return "missing"
    if a == b:
        return "match"
    return "conflict"


def postnominals_compatible(post_a, post_b):
    """Check whether postnominals match.

    Returns one of:
        "match"   - both present and identical
        "missing" - one or both are empty
        "differ"  - present but different (not a blocker)
    """
    a = post_a.strip().lower()
    b = post_b.strip().lower()

    if not a or not b:
        return "missing"
    if a == b:
        return "match"
    return "differ"


_OCCUPATION_STOPWORDS = {"and", "the", "of", "at", "law", "&", "mr", "mrs"}


def occupations_compatible(occ_a, occ_b):
    """Occupation as an identifying attribute, treated like location.

    Lenient token overlap so "attorney" and "attorney at law", or
    "bookseller" and "printer and bookseller", still count as a match
    (occupations are noisy and sometimes list more than one trade).

    Returns one of:
        "match"    - share a content word
        "missing"  - one or both empty
        "conflict" - both present, no shared content word
    """
    a = {w.strip(".,&") for w in occ_a.lower().split()} - _OCCUPATION_STOPWORDS
    b = {w.strip(".,&") for w in occ_b.lower().split()} - _OCCUPATION_STOPWORDS
    a = {w for w in a if w}
    b = {w for w in b if w}
    if not a or not b:
        return "missing"
    if a & b:
        return "match"
    return "conflict"


def affiliations_compatible(aff_a, aff_b):
    """Institutional affiliation as an identifying attribute.

    Compared with punctuation and spacing removed so "T. C. D" and
    "T.C.D" match; substring containment also counts ("Trinity Coll" vs
    "Trinity College").

    Returns "match" / "missing" / "conflict".
    """
    a = "".join(c for c in aff_a.lower() if c.isalnum())
    b = "".join(c for c in aff_b.lower() if c.isalnum())
    if not a or not b:
        return "missing"
    if a == b or a in b or b in a:
        return "match"
    return "conflict"


def max_last_name_distance(last_name, first_compat):
    """Return the maximum allowed edit distance for a last name,
    scaled by name length and first-name signal strength.

    first_compat should be one of: "exact", "initial", "missing"
    """
    length = len(last_name.strip())

    if first_compat == "exact":
        if length <= 4:
            return 1
        elif length <= 7:
            return 2
        else:
            return 3
    else:
        if length <= 4:
            return 0
        elif length <= 7:
            return 1
        else:
            return 2


def entries_match(a, b, scope="within_book"):
    """Determine whether two entries should be matched.

    scope should be "within_book" or "cross_book".

    Returns (match: bool, rule_name: str) where rule_name describes
    why they matched or None if they don't.
    """
    if a.get("book") == b.get("book") and a.get("edition") == b.get("edition"):
        return False, None

    title_a = _normalize_title(_effective_title(a))
    title_b = _normalize_title(_effective_title(b))

    title_ok = titles_compatible(_effective_title(a), _effective_title(b))
    if not title_ok:
        return False, None

    first_compat = first_names_compatible(a.get("parsed_first", ""),
                                          b.get("parsed_first", ""))
    if first_compat == "conflict":
        return False, None

    loc_compat = locations_compatible(a.get("parsed_location", ""),
                                      b.get("parsed_location", ""))
    if loc_compat == "conflict":
        return False, None

    # Occupation and affiliation are identifying attributes (like location):
    # a conflict blocks the match. Missing/agreeing values fall through, and
    # agreement is counted as a strong signal below. Columns are read with
    # .get() so the matcher still runs on parsed CSVs that predate them.
    occ_compat = occupations_compatible(a.get("parsed_occupation", ""),
                                        b.get("parsed_occupation", ""))
    if occ_compat == "conflict":
        return False, None

    aff_compat = affiliations_compatible(a.get("parsed_affiliation", ""),
                                         b.get("parsed_affiliation", ""))
    if aff_compat == "conflict":
        return False, None

    post_compat = postnominals_compatible(a.get("parsed_postnominals", ""),
                                          b.get("parsed_postnominals", ""))

    last_a_raw = a.get("parsed_last", "").strip().lower()
    last_b_raw = b.get("parsed_last", "").strip().lower()

    # Special case: entries with no last name but multiple initials.
    # Within book: 2+ initials suffice. Cross book: 3+ required.
    if not last_a_raw and not last_b_raw:
        first_a = a.get("parsed_first", "").strip()
        first_b = b.get("parsed_first", "").strip()
        min_initials = 2 if scope == "within_book" else 3
        if (_is_multi_initial(first_a, min_initials)
                and _is_multi_initial(first_b, min_initials)
                and first_a.lower() == first_b.lower() and title_ok):
            return True, "multi_initials"
        return False, None

    if not last_a_raw or not last_b_raw:
        return False, None

    last_a = _strip_surname_prefix(last_a_raw)
    last_b = _strip_surname_prefix(last_b_raw)

    # Detect location absorbed into last name: one entry has
    # last="Smith London" loc="" while the other has last="Smith" loc="London".
    loc_a = a.get("parsed_location", "").strip().lower().replace("-", "")
    loc_b = b.get("parsed_location", "").strip().lower().replace("-", "")
    loc_absorbed = False
    if last_a != last_b:
        if loc_b and not loc_a and last_a == last_b + " " + loc_b:
            last_a = last_b
            loc_absorbed = True
        elif loc_a and not loc_b and last_b == last_a + " " + loc_a:
            last_b = last_a
            loc_absorbed = True
    if loc_absorbed:
        loc_compat = "match"

    equiv = EQUIV_TITLES

    # Within-book: exact last + compatible title + no conflicting first.
    # When first name is missing, require titles to be strictly identical
    # (not just equivalent) — "Mr. Ady" and "John Ady" shouldn't match.
    titles_identical = title_a == title_b
    titles_equivalent = titles_identical or (
        title_a in equiv and title_b in equiv
    )
    if (scope == "within_book" and last_a == last_b
            and first_compat != "conflict"):
        if first_compat in ("exact", "initial") and titles_equivalent:
            parts = ["exact_last", first_compat + "_first"]
            if loc_compat == "match":
                parts.append("loc")
            if post_compat == "match":
                parts.append("post")
            return True, "+".join(parts)
        if first_compat == "missing" and titles_identical:
            parts = ["exact_last", "missing_first"]
            if loc_compat == "match":
                parts.append("loc")
            if post_compat == "match":
                parts.append("post")
            return True, "+".join(parts)
        if first_compat == "fuzzy" and titles_equivalent:
            parts = ["exact_last", "fuzzy_first"]
            if title_ok and title_a not in equiv:
                parts.append("title")
            if loc_compat == "match":
                parts.append("loc")
            if post_compat == "match":
                parts.append("post")
            return True, "+".join(parts)

    # Count strong signals beyond the last name.
    # Fuzzy first names are excluded here — they require exact last name.
    strong_signals = 0
    if title_ok and title_a not in equiv:
        strong_signals += 1
    if first_compat == "exact":
        strong_signals += 1
    elif first_compat == "initial":
        strong_signals += 0.5
    if loc_compat == "match":
        strong_signals += 1
    if occ_compat == "match":
        strong_signals += 1
    if aff_compat == "match":
        strong_signals += 1
    if post_compat == "match":
        strong_signals += 0.5

    if strong_signals < 1:
        return False, None

    effective_first = first_compat if first_compat in ("exact", "initial") else "missing"
    allowed_dist = max_last_name_distance(last_a, effective_first)

    dist = levenshtein_distance(last_a, last_b)
    if dist > allowed_dist:
        return False, None

    # Build a descriptive rule name.
    parts = []
    if dist == 0:
        parts.append("exact_last")
    else:
        parts.append(f"fuzzy_last_{dist}")
    parts.append(first_compat + "_first")
    if loc_compat == "match":
        parts.append("loc")
    if occ_compat == "match":
        parts.append("occ")
    if aff_compat == "match":
        parts.append("aff")
    if post_compat == "match":
        parts.append("post")
    rule_name = "+".join(parts)

    return True, rule_name


def is_cross_book_eligible(entry, relaxed=False):
    """Non-distinctive titles require a location, postnominal, or (in relaxed mode) a first name."""
    title = _normalize_title(_effective_title(entry))
    if title not in NON_DISTINCTIVE_TITLES:
        return True
    has_location = bool(entry.get("parsed_location", "").strip())
    has_postnominals = bool(entry.get("parsed_postnominals", "").strip())
    has_occupation = bool(entry.get("parsed_occupation", "").strip())
    has_affiliation = bool(entry.get("parsed_affiliation", "").strip())
    identifying = (has_location or has_postnominals
                   or has_occupation or has_affiliation)
    if relaxed:
        has_first = bool(entry.get("parsed_first", "").strip())
        return identifying or has_first
    return identifying


def load_title_matched_ids(title_auto_path, title_cand_path):
    ids = set()
    for path in [title_auto_path, title_cand_path]:
        p = Path(path)
        if not p.exists():
            continue
        with open(p, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ids.add(row["entry_id"])
    return ids


def build_match_row(entry, group_id, match_val, rule_name, tier):
    return {
        "group_id": group_id,
        "match": match_val,
        "entry_id": entry["entry_id"],
        "person_id": entry["person_id"],
        "normalized_name": entry["normalized_name"],
        "listed as": entry.get("listed as", ""),
        "parsed_title": entry.get("parsed_title", ""),
        "parsed_first": entry.get("parsed_first", ""),
        "parsed_last": entry.get("parsed_last", ""),
        "parsed_postnominals": entry.get("parsed_postnominals", ""),
        "parsed_occupation": entry.get("parsed_occupation", ""),
        "parsed_affiliation": entry.get("parsed_affiliation", ""),
        "parsed_location": entry.get("parsed_location", ""),
        "book": entry["book"],
        "edition": entry["edition"],
        "year": entry["year"],
        "match_rule": rule_name,
        "match_tier": tier,
    }


def _entry_signature(entry):
    """Return a comparable signature for coexistence detection."""
    return (
        _normalize_title(_effective_title(entry)),
        entry.get("parsed_first", "").strip().lower(),
        entry.get("parsed_last", "").strip().lower(),
        entry.get("parsed_postnominals", "").strip().lower(),
    )


def _build_coexistence_blocks(entries):
    """Identify entries that must not be clustered because they
    represent name patterns that coexist in the same edition.

    If two entries share the same title, first, and last but differ
    in specificity (one has a first name the other lacks, or they
    have different postnominals like Jun. vs Sen.), and they coexist
    in any edition, they are different people everywhere.

    Returns a set of frozenset(entry_id, entry_id) pairs.
    """
    by_edition = defaultdict(list)
    for entry in entries:
        by_edition[(entry["book"], entry["edition"])].append(entry)

    # Collect pairs of signatures that coexist in any edition and
    # would otherwise be matchable (same title+last, compatible first).
    blocked_sig_pairs = set()
    for edition, group in by_edition.items():
        for ia in range(len(group)):
            for ib in range(ia + 1, len(group)):
                a, b = group[ia], group[ib]
                sig_a = _entry_signature(a)
                sig_b = _entry_signature(b)
                ta, fa, la, pa = sig_a
                tb, fb, lb, pb = sig_b
                if ta != tb or la != lb or not la:
                    continue
                # Same-edition, same title+last: these are different
                # people. Record the distinguishing pattern.
                first_diff = (bool(fa) != bool(fb))
                post_diff = (pa != pb)
                if first_diff or post_diff:
                    blocked_sig_pairs.add(frozenset((sig_a, sig_b)))

    if not blocked_sig_pairs:
        return set()

    # Block all entry pairs whose signatures match a blocked pair.
    blocked = set()
    sigs = {entry["entry_id"]: _entry_signature(entry) for entry in entries}
    entry_ids = list(sigs.keys())
    for i in range(len(entry_ids)):
        for j in range(i + 1, len(entry_ids)):
            pair = frozenset((sigs[entry_ids[i]], sigs[entry_ids[j]]))
            if pair in blocked_sig_pairs:
                blocked.add(frozenset((entry_ids[i], entry_ids[j])))

    return blocked


def cluster_entries(entries, scope="within_book"):
    """Group entries into match clusters based on pairwise compatibility."""
    blocked = _build_coexistence_blocks(entries)
    clusters = []
    used = set()

    for i, entry_a in enumerate(entries):
        if i in used:
            continue
        cluster = [entry_a]
        cluster_ids = {entry_a["entry_id"]}
        cluster_rule = None
        used.add(i)

        for j in range(i + 1, len(entries)):
            if j in used:
                continue
            eid = entries[j]["entry_id"]
            if any(frozenset((cid, eid)) in blocked for cid in cluster_ids):
                continue
            matched, rule_name = entries_match(entry_a, entries[j], scope)
            if matched:
                cluster.append(entries[j])
                cluster_ids.add(eid)
                used.add(j)
                if cluster_rule is None:
                    cluster_rule = rule_name

        if len(cluster) >= 2:
            clusters.append((cluster, cluster_rule))

    return clusters


def find_fuzzy_last_groups(by_last, max_dist=3):
    """Yield groups of entries whose last names are within max_dist of each other."""
    last_names = list(by_last.keys())
    yielded = set()

    for i, last_a in enumerate(last_names):
        group = list(by_last[last_a])
        partners = [last_a]
        for j in range(i + 1, len(last_names)):
            last_b = last_names[j]
            if levenshtein_distance(last_a, last_b) <= max_dist:
                group.extend(by_last[last_b])
                partners.append(last_b)

        key = tuple(sorted(partners))
        if len(partners) > 1 and key not in yielded:
            yielded.add(key)
            yield group


def main():
    parser = argparse.ArgumentParser(
        description="Match non-titled entries using rules-based component matching."
    )
    parser.add_argument(
        "input_csv",
        help="Path to the parsed CSV (from 04_parse_names.py)."
    )
    parser.add_argument(
        "--title-matches", default="outputs/05-title-matches.csv",
        help="Path to title auto-resolved matches."
    )
    parser.add_argument(
        "--title-candidates", default="outputs/05-title-candidates.csv",
        help="Path to title candidate matches."
    )
    parser.add_argument(
        "--auto-output", default="outputs/06-auto-resolved.csv",
        help="Path for auto-resolved matches."
    )
    parser.add_argument(
        "--candidates-output", default="outputs/06-candidates.csv",
        help="Path for candidate matches needing review."
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Require a location or postnominal (not just a first name) for "
             "non-distinctive titles in cross-book matching."
    )
    args = parser.parse_args()

    input_path = Path(args.input_csv)
    rows = []
    with open(input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            print(f"ERROR: {input_path} is missing columns: {missing}")
            sys.exit(1)
        for row in reader:
            rows.append(row)

    title_ids = load_title_matched_ids(args.title_matches, args.title_candidates)
    eligible = [
        r for r in rows
        if r["entry_id"] not in title_ids
        and r["name_type"] != "titled"
        and r["name_type"] != "anonymous"
    ]
    print(f"Eligible entries: {len(eligible)} (excluded {len(title_ids)} title-matched)")

    by_book = defaultdict(list)
    for entry in eligible:
        by_book[entry["book"]].append(entry)

    auto_rows = []
    candidate_rows = []
    matched_ids = set()
    candidate_ids = set()
    group_counter = 0

    # --- Within-book matching ---
    for book, book_entries in by_book.items():
        by_last = defaultdict(list)
        for entry in book_entries:
            last = entry.get("parsed_last", "").strip().lower()
            if last:
                by_last[last].append(entry)

        # Multi-initial entries (no last name, 3+ initials as first name).
        by_initials = defaultdict(list)
        for entry in book_entries:
            last = entry.get("parsed_last", "").strip()
            first = entry.get("parsed_first", "").strip()
            if not last and _is_multi_initial(first, min_count=2):
                by_initials[first.lower()].append(entry)

        for initials, group in by_initials.items():
            available = [e for e in group if e["entry_id"] not in matched_ids]
            if len(available) < 2:
                continue
            for cluster, rule_name in cluster_entries(available):
                group_counter += 1
                gid = f"cm_{group_counter:04d}"
                for entry in cluster:
                    auto_rows.append(
                        build_match_row(entry, gid, "y", rule_name, "auto_within"))
                    matched_ids.add(entry["entry_id"])

        # Exact last name groups.
        for last_name, group in by_last.items():
            available = [e for e in group if e["entry_id"] not in matched_ids]
            if len(available) < 2:
                continue
            for cluster, rule_name in cluster_entries(available):
                is_fuzzy_first = "fuzzy_first" in rule_name
                has_corroboration = is_fuzzy_first and (
                    "+title" in rule_name or "+loc" in rule_name
                    or "+post" in rule_name)
                if is_fuzzy_first and not has_corroboration:
                    group_counter += 1
                    gid = f"cm_{group_counter:04d}"
                    for entry in cluster:
                        candidate_rows.append(
                            build_match_row(entry, gid, "", rule_name,
                                            "candidate_within"))
                        candidate_ids.add(entry["entry_id"])
                else:
                    group_counter += 1
                    gid = f"cm_{group_counter:04d}"
                    for entry in cluster:
                        auto_rows.append(
                            build_match_row(entry, gid, "y", rule_name,
                                            "auto_within"))
                        matched_ids.add(entry["entry_id"])

        # --- Fuzzy linkage (within-book) ---
        # After exact clustering, spelling variants may remain unlinked
        # in two ways: (1) singletons whose exact last name had no other
        # entries, and (2) separate clusters whose last names are
        # fuzzy-similar (e.g. "Low" cluster + "Lowe" cluster).
        # This step runs before the speculative fuzzy grouping so that
        # high-confidence links to established clusters take priority.
        book_group_canonical = {}
        for row in auto_rows:
            if row.get("book") != book:
                continue
            gid = row["group_id"]
            if gid not in book_group_canonical:
                book_group_canonical[gid] = row

        if book_group_canonical:
            canonical_by_last = defaultdict(list)
            for gid, row in book_group_canonical.items():
                last = row.get("parsed_last", "").strip().lower()
                if last:
                    canonical_by_last[last].append((gid, row))

            # Phase 1: link unmatched singletons to existing groups.
            still_unmatched = [
                e for e in book_entries
                if e["entry_id"] not in matched_ids
                and e["entry_id"] not in candidate_ids
                and e.get("parsed_last", "").strip()
            ]

            for entry in still_unmatched:
                last = entry.get("parsed_last", "").strip().lower()
                for canonical_last, canonicals in canonical_by_last.items():
                    raw_dist = levenshtein_distance(last, canonical_last)
                    stripped_dist = levenshtein_distance(
                        _strip_surname_prefix(last),
                        _strip_surname_prefix(canonical_last))
                    dist = min(raw_dist, stripped_dist)
                    if (raw_dist == 0 and stripped_dist == 0) or dist > 3:
                        continue
                    linked = False
                    for gid, canonical_row in canonicals:
                        ok, rule = entries_match(entry, canonical_row, "within_book")
                        if not ok:
                            continue
                        fc = first_names_compatible(
                            entry.get("parsed_first", ""),
                            canonical_row.get("parsed_first", ""))
                        if dist <= 2 and fc == "exact":
                            auto_rows.append(
                                build_match_row(entry, gid, "y",
                                                f"fuzzy_last_{dist}+" + rule.split("+", 1)[-1],
                                                "auto_within_linkage"))
                            matched_ids.add(entry["entry_id"])
                        else:
                            candidate_rows.append(
                                build_match_row(entry, gid, "",
                                                f"fuzzy_last_{dist}+" + rule.split("+", 1)[-1],
                                                "candidate_within_linkage"))
                            candidate_ids.add(entry["entry_id"])
                        linked = True
                        break
                    if linked:
                        break

            # Phase 2: merge clusters with fuzzy-similar last names.
            merged_into = {}

            def resolve_gid(g):
                while g in merged_into:
                    g = merged_into[g]
                return g

            group_sizes = defaultdict(int)
            for row in auto_rows:
                if row.get("book") != book:
                    continue
                group_sizes[row["group_id"]] += 1

            seen_pairs = set()
            for last_a, canonicals_a in canonical_by_last.items():
                for last_b, canonicals_b in canonical_by_last.items():
                    if last_a >= last_b:
                        continue
                    raw_dist = levenshtein_distance(last_a, last_b)
                    stripped_dist = levenshtein_distance(
                        _strip_surname_prefix(last_a),
                        _strip_surname_prefix(last_b))
                    dist = min(raw_dist, stripped_dist)
                    if (raw_dist == 0 and stripped_dist == 0) or dist > 3:
                        continue
                    for gid_a, row_a in canonicals_a:
                        ra = resolve_gid(gid_a)
                        for gid_b, row_b in canonicals_b:
                            rb = resolve_gid(gid_b)
                            if ra == rb:
                                continue
                            pair = (min(ra, rb), max(ra, rb))
                            if pair in seen_pairs:
                                continue
                            seen_pairs.add(pair)
                            ok, rule = entries_match(row_a, row_b, "within_book")
                            if not ok:
                                continue
                            fc = first_names_compatible(
                                row_a.get("parsed_first", ""),
                                row_b.get("parsed_first", ""))
                            if dist <= 2 and fc == "exact":
                                keep = ra if group_sizes[ra] >= group_sizes[rb] else rb
                                absorb = rb if keep == ra else ra
                                merged_into[absorb] = keep
                                group_sizes[keep] += group_sizes[absorb]
                            else:
                                group_counter += 1
                                cgid = f"cm_{group_counter:04d}"
                                for row in (row_a, row_b):
                                    candidate_rows.append(
                                        build_match_row(row, cgid, "",
                                                        f"fuzzy_last_{dist}+" + rule.split("+", 1)[-1],
                                                        "candidate_cluster_merge"))
                                    candidate_ids.add(row["entry_id"])

            if merged_into:
                for row in auto_rows:
                    if row.get("book") != book:
                        continue
                    new_gid = resolve_gid(row["group_id"])
                    if new_gid != row["group_id"]:
                        row["group_id"] = new_gid
                        row["match_rule"] = row.get("match_rule", "") + "+cluster_merge"

        # Fuzzy last name groups (speculative).
        for fuzzy_group in find_fuzzy_last_groups(by_last):
            available = [e for e in fuzzy_group
                         if e["entry_id"] not in matched_ids
                         and e["entry_id"] not in candidate_ids]
            if len(available) < 2:
                continue
            for cluster, rule_name in cluster_entries(available):
                lasts = set(e.get("parsed_last", "").strip().lower() for e in cluster)
                if len(lasts) < 2:
                    continue
                group_counter += 1
                gid = f"cm_{group_counter:04d}"
                for entry in cluster:
                    candidate_rows.append(
                        build_match_row(entry, gid, "", rule_name, "candidate_within")
                    )
                    candidate_ids.add(entry["entry_id"])

    # --- Cross-book matching ---
    # Include within-book matched entries so they can anchor cross-book groups.
    all_by_last = defaultdict(list)
    for entry in eligible:
        if entry["entry_id"] in candidate_ids:
            continue
        if not is_cross_book_eligible(entry, relaxed=not args.strict):
            continue
        last = entry.get("parsed_last", "").strip().lower()
        if last:
            all_by_last[last].append(entry)

    # Exact last name groups across books.
    for last_name, group in all_by_last.items():
        available = [e for e in group
                     if e["entry_id"] not in candidate_ids]
        books = set(e["book"] for e in available)
        if len(books) < 2:
            continue
        for cluster, rule_name in cluster_entries(available, scope="cross_book"):
            cluster_books = set(e["book"] for e in cluster)
            if len(cluster_books) < 2:
                continue
            group_counter += 1
            gid = f"cm_{group_counter:04d}"
            for entry in cluster:
                if entry["entry_id"] not in matched_ids:
                    candidate_rows.append(
                        build_match_row(entry, gid, "", rule_name, "candidate_cross")
                    )
                    candidate_ids.add(entry["entry_id"])
                else:
                    candidate_rows.append(
                        build_match_row(entry, gid, "", rule_name, "anchor_cross")
                    )

    # Fuzzy last name groups across books.
    for fuzzy_group in find_fuzzy_last_groups(all_by_last):
        available = [e for e in fuzzy_group
                     if e["entry_id"] not in candidate_ids]
        if len(available) < 2:
            continue
        for cluster, rule_name in cluster_entries(available, scope="cross_book"):
            cluster_books = set(e["book"] for e in cluster)
            if len(cluster_books) < 2:
                continue
            lasts = set(e.get("parsed_last", "").strip().lower() for e in cluster)
            if len(lasts) < 2:
                continue
            group_counter += 1
            gid = f"cm_{group_counter:04d}"
            for entry in cluster:
                if entry["entry_id"] not in matched_ids:
                    candidate_rows.append(
                        build_match_row(entry, gid, "", rule_name, "candidate_cross")
                    )
                    candidate_ids.add(entry["entry_id"])
                else:
                    candidate_rows.append(
                        build_match_row(entry, gid, "", rule_name, "anchor_cross")
                    )

    # Write outputs.
    auto_path = Path(args.auto_output)
    auto_path.parent.mkdir(parents=True, exist_ok=True)
    with open(auto_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MATCH_COLUMNS)
        writer.writeheader()
        writer.writerows(auto_rows)

    cand_path = Path(args.candidates_output)
    with open(cand_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MATCH_COLUMNS)
        writer.writeheader()
        writer.writerows(candidate_rows)

    auto_groups = len(set(r["group_id"] for r in auto_rows))
    cand_groups = len(set(r["group_id"] for r in candidate_rows))
    print(f"\nAuto-resolved: {auto_groups} groups ({len(auto_rows)} entries)")
    print(f"Candidates:    {cand_groups} groups ({len(candidate_rows)} entries)")
    print(f"\nWrote {auto_path}")
    print(f"Wrote {cand_path}")


if __name__ == "__main__":
    main()
