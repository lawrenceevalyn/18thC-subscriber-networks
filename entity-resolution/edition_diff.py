"""
================================================================================
          Edition-Diff Missed-Match Analysis — edition_diff.py
================================================================================
RUN WITH: python3 edition_diff.py
          python3 edition_diff.py --input outputs/deduplicated.csv
          python3 edition_diff.py --author "Equiano, Olaudah" --min-score 2.0
          python3 edition_diff.py --output outputs/edition-diff-candidates.csv

DESCRIPTION:
    Identifies potential missed entity-resolution matches by looking at
    subscriber names that "arrive" or "depart" at each edition boundary.

    A missed match looks like:
        - Person A's person_id last appears in edition N
        - Person B's person_id first appears in edition N+1
        - A and B have similar name components (last name, title, location)

    For each consecutive edition pair, the script computes:
        - Departures: person_ids whose LAST appearance is edition N
        - Arrivals:   person_ids whose FIRST appearance is edition N+1

    Each departure is compared to each arrival using a scoring rubric:
        last_name similarity   (scaled 0-3, using Levenshtein ratio)
        title compatibility    (0 or 1)
        first name / initial   (0-1)
        location match         (0 or 1)
        postnominals match     (0 or 0.5)

    Only pairs scoring above --min-score are reported.

    Output columns:
        score, edition_boundary, dep_entry_ids, dep_label, arr_entry_ids,
        arr_label, dep_last, arr_last, dep_title, arr_title, dep_first,
        arr_first, dep_location, arr_location, dep_postnominals,
        arr_postnominals, dep_editions, arr_editions

USAGE NOTES:
    Run with --review to write only the candidate CSV (no terminal table).
    The candidate CSV can be hand-reviewed and used to build additional
    match files for 07_deduplicate.py.
--------------------------------------------------------------------------------
LICENSE:
    MIT License
    Copyright (c) 2026 Lawrence Evalyn
================================================================================
"""

import csv
import argparse
import sys
from collections import defaultdict
from pathlib import Path

try:
    from rapidfuzz.distance import Levenshtein as _Lev
    def levenshtein_distance(a, b):
        return _Lev.distance(a, b)
except ImportError:
    def levenshtein_distance(a, b):
        m, n = len(a), len(b)
        dp = list(range(n + 1))
        for i in range(1, m + 1):
            prev = dp[0]
            dp[0] = i
            for j in range(1, n + 1):
                temp = dp[j]
                dp[j] = prev if a[i-1] == b[j-1] else 1 + min(prev, dp[j], dp[j-1])
                prev = temp
        return dp[n]


# ---------------------------------------------------------------------------
# Title compatibility (mirrors 06_match_components.py logic)
# ---------------------------------------------------------------------------

TITLE_EQUIVALENCES = [
    {"Mr.", "Esq.", ""},        # within-book equivalents (all scope)
    {"Rev.", "Rev. Mr."},
    {"Mrs.", ""},               # Mrs. / bare treated as compatible
    {"Miss", ""},
]

def titles_compatible(t1, t2):
    t1, t2 = t1.strip(), t2.strip()
    if t1 == t2:
        return True
    for group in TITLE_EQUIVALENCES:
        if t1 in group and t2 in group:
            return True
    return False


# ---------------------------------------------------------------------------
# Last-name similarity score (0–3)
# ---------------------------------------------------------------------------

def last_name_score(a, b):
    a, b = a.strip().lower(), b.strip().lower()
    if not a or not b:
        return 0.0
    if a == b:
        return 3.0
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 0.0
    dist = levenshtein_distance(a, b)
    ratio = 1.0 - dist / max_len
    if ratio >= 0.85:
        return 2.5
    if ratio >= 0.70:
        return 1.5
    if ratio >= 0.55:
        return 0.8
    return 0.0


# ---------------------------------------------------------------------------
# First name / initial compatibility (0, 0.5, or 1)
# ---------------------------------------------------------------------------

def first_name_score(f1, f2):
    f1, f2 = f1.strip().lower(), f2.strip().lower()
    if not f1 or not f2:
        return 0.3   # missing first: small neutral signal
    if f1 == f2:
        return 1.0
    # initial compatibility
    if len(f1) == 1 and f2.startswith(f1):
        return 0.7
    if len(f2) == 1 and f1.startswith(f2):
        return 0.7
    # conflicting initials → small penalty
    if f1[0] != f2[0]:
        return -0.5
    return 0.3


# ---------------------------------------------------------------------------
# Build a summary label for a person_id
# ---------------------------------------------------------------------------

def make_label(entries):
    # Use the entry with the most information
    best = max(entries, key=lambda e: len(e.get("normalized_name", "")))
    parts = [
        best.get("parsed_title", "").strip(),
        best.get("parsed_first", "").strip(),
        best.get("parsed_last", "").strip(),
    ]
    name = " ".join(p for p in parts if p)
    loc = best.get("parsed_location", "").strip()
    post = best.get("parsed_postnominals", "").strip()
    suffix = ", ".join(p for p in [post, loc] if p)
    return f"{name} ({suffix})" if suffix else name


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def load_deduplicated(path, author_filter):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if author_filter and row.get("author", "").strip() != author_filter:
                continue
            rows.append(row)
    return rows


def group_by_person_edition(rows):
    """Map person_id -> set of edition ints."""
    pid_editions = defaultdict(set)
    pid_entries = defaultdict(list)
    for row in rows:
        pid = row["person_id"]
        try:
            ed = int(row["edition"])
        except (ValueError, KeyError):
            continue
        pid_editions[pid].add(ed)
        pid_entries[pid].append(row)
    return pid_editions, pid_entries


def summarise_person(entries):
    """Collapse a list of entries for one person_id into a single dict."""
    # Prefer entries with the most filled-in fields
    def richness(e):
        return sum(1 for v in [e.get("parsed_last"), e.get("parsed_first"),
                                e.get("parsed_title"), e.get("parsed_location"),
                                e.get("parsed_postnominals")] if v and v.strip())
    best = max(entries, key=richness)
    return {
        "parsed_title":        best.get("parsed_title", "").strip(),
        "parsed_first":        best.get("parsed_first", "").strip(),
        "parsed_last":         best.get("parsed_last", "").strip(),
        "parsed_postnominals": best.get("parsed_postnominals", "").strip(),
        "parsed_location":     best.get("parsed_location", "").strip(),
        "name_type":           best.get("name_type", "").strip(),
    }


def compare_pair(dep_summ, arr_summ):
    """Score a departure/arrival pair. Returns (score, details_dict)."""
    dep_last  = dep_summ["parsed_last"]
    arr_last  = arr_summ["parsed_last"]
    dep_title = dep_summ["parsed_title"]
    arr_title = arr_summ["parsed_title"]
    dep_first = dep_summ["parsed_first"]
    arr_first = arr_summ["parsed_first"]
    dep_loc   = dep_summ["parsed_location"]
    arr_loc   = arr_summ["parsed_location"]
    dep_post  = dep_summ["parsed_postnominals"]
    arr_post  = arr_summ["parsed_postnominals"]

    # Bare/anonymous entries with no last name can't be meaningfully compared
    if not dep_last and not arr_last:
        return 0.0, {}

    s_last  = last_name_score(dep_last, arr_last)
    # No last-name similarity → skip
    if s_last == 0.0:
        return 0.0, {}

    s_title = 1.0 if titles_compatible(dep_title, arr_title) else -1.0
    s_first = first_name_score(dep_first, arr_first)

    # Location: strong positive if matching non-empty, small negative if conflicting
    s_loc = 0.0
    if dep_loc and arr_loc:
        if dep_loc.lower() == arr_loc.lower():
            s_loc = 1.0
        else:
            s_loc = -0.3

    # Postnominals: supporting signal
    s_post = 0.0
    if dep_post and arr_post and dep_post.lower() == arr_post.lower():
        s_post = 0.5

    score = s_last + s_title + s_first + s_loc + s_post
    details = {
        "s_last": round(s_last, 2),
        "s_title": s_title,
        "s_first": round(s_first, 2),
        "s_loc": s_loc,
        "s_post": s_post,
    }
    return round(score, 2), details


def find_missed_matches(rows, min_score, editions_range=None):
    pid_editions, pid_entries = group_by_person_edition(rows)

    if editions_range is None:
        all_eds = sorted({ed for eds in pid_editions.values() for ed in eds})
        if len(all_eds) < 2:
            return []
        editions_range = range(min(all_eds), max(all_eds))

    candidates = []

    for ed_n in editions_range:
        ed_np1 = ed_n + 1

        # Departures: person_ids whose last edition is ed_n
        departures = {
            pid: pid_entries[pid]
            for pid, eds in pid_editions.items()
            if max(eds) == ed_n
        }

        # Arrivals: person_ids whose first edition is ed_np1
        arrivals = {
            pid: pid_entries[pid]
            for pid, eds in pid_editions.items()
            if min(eds) == ed_np1
        }

        dep_summs = {pid: summarise_person(entries) for pid, entries in departures.items()}
        arr_summs = {pid: summarise_person(entries) for pid, entries in arrivals.items()}

        for dep_pid, dep_summ in dep_summs.items():
            for arr_pid, arr_summ in arr_summs.items():
                score, details = compare_pair(dep_summ, arr_summ)
                if score >= min_score:
                    dep_eds = sorted(pid_editions[dep_pid])
                    arr_eds = sorted(pid_editions[arr_pid])
                    dep_entry_ids = sorted(e["entry_id"] for e in pid_entries[dep_pid])
                    arr_entry_ids = sorted(e["entry_id"] for e in pid_entries[arr_pid])
                    candidates.append({
                        "score": score,
                        "edition_boundary": f"{ed_n}→{ed_np1}",
                        "dep_pid": dep_pid,
                        "arr_pid": arr_pid,
                        "dep_label": make_label(pid_entries[dep_pid]),
                        "arr_label": make_label(pid_entries[arr_pid]),
                        "dep_last":  dep_summ["parsed_last"],
                        "arr_last":  arr_summ["parsed_last"],
                        "dep_title": dep_summ["parsed_title"],
                        "arr_title": arr_summ["parsed_title"],
                        "dep_first": dep_summ["parsed_first"],
                        "arr_first": arr_summ["parsed_first"],
                        "dep_location": dep_summ["parsed_location"],
                        "arr_location": arr_summ["parsed_location"],
                        "dep_postnominals": dep_summ["parsed_postnominals"],
                        "arr_postnominals": arr_summ["parsed_postnominals"],
                        "dep_editions": ",".join(str(e) for e in dep_eds),
                        "arr_editions": ",".join(str(e) for e in arr_eds),
                        "dep_entry_ids": "|".join(dep_entry_ids),
                        "arr_entry_ids": "|".join(arr_entry_ids),
                        **{f"detail_{k}": v for k, v in details.items()},
                    })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


# ---------------------------------------------------------------------------
# Edition-overview table
# ---------------------------------------------------------------------------

def print_edition_overview(rows):
    pid_editions, pid_entries = group_by_person_edition(rows)
    all_eds = sorted({ed for eds in pid_editions.values() for ed in eds})

    print(f"\n{'─'*60}")
    print(f"  Edition overview")
    print(f"{'─'*60}")

    for i, ed in enumerate(all_eds):
        in_ed = {pid for pid, eds in pid_editions.items() if ed in eds}
        total = len(in_ed)
        if i == 0:
            new_pids = in_ed
            cont_pids = set()
            dep_pids = set()
        else:
            prev_ed = all_eds[i - 1]
            prev = {pid for pid, eds in pid_editions.items() if prev_ed in eds}
            new_pids  = in_ed - prev
            cont_pids = in_ed & prev
            dep_pids  = prev - in_ed

        if i == 0:
            print(f"  Ed {ed}: {total:4d} total")
        else:
            print(f"  Ed {ed}: {total:4d} total  "
                  f"(+{len(new_pids):3d} new, "
                  f"{len(cont_pids):3d} continued, "
                  f"-{len(dep_pids):3d} departed)")

    print()


# ---------------------------------------------------------------------------
# CLI output
# ---------------------------------------------------------------------------

OUTPUT_COLUMNS = [
    "score", "edition_boundary",
    "dep_label", "arr_label",
    "dep_last", "arr_last",
    "dep_title", "arr_title",
    "dep_first", "arr_first",
    "dep_location", "arr_location",
    "dep_postnominals", "arr_postnominals",
    "dep_editions", "arr_editions",
    "dep_pid", "arr_pid",
    "dep_entry_ids", "arr_entry_ids",
]


def print_candidates(candidates, limit=50):
    if not candidates:
        print("No candidates found at this score threshold.")
        return

    shown = candidates[:limit]
    print(f"\n{'─'*60}")
    print(f"  Top {len(shown)} missed-match candidates "
          f"(of {len(candidates)} total)")
    print(f"{'─'*60}\n")

    for c in shown:
        print(f"  Score {c['score']:5.2f}  [{c['edition_boundary']}]")
        print(f"    DEP {c['dep_editions']:>12s}  {c['dep_label']}")
        print(f"    ARR {c['arr_editions']:>12s}  {c['arr_label']}")
        score_parts = (
            f"last={c['detail_s_last']}, "
            f"title={c['detail_s_title']}, "
            f"first={c['detail_s_first']}, "
            f"loc={c['detail_s_loc']}, "
            f"post={c['detail_s_post']}"
        )
        print(f"    ({score_parts})")
        print()

    if len(candidates) > limit:
        print(f"  ... {len(candidates) - limit} more candidates omitted "
              f"(lower --min-score or check the output CSV)\n")


def write_csv(candidates, output_path):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    all_cols = OUTPUT_COLUMNS + [k for k in candidates[0] if k not in OUTPUT_COLUMNS]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(candidates)
    print(f"Wrote {len(candidates)} candidates to {output_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Identify potential missed matches by comparing arrivals/departures across editions."
    )
    parser.add_argument(
        "--input", default="outputs/deduplicated.csv",
        help="Path to deduplicated CSV (default: outputs/deduplicated.csv)."
    )
    parser.add_argument(
        "--output", default="outputs/edition-diff-candidates.csv",
        help="Path to write candidate CSV (default: outputs/edition-diff-candidates.csv)."
    )
    parser.add_argument(
        "--author", default="Equiano, Olaudah",
        help="Filter to a single author (default: 'Equiano, Olaudah'). Pass '' to include all."
    )
    parser.add_argument(
        "--min-score", type=float, default=2.5,
        help="Minimum score to include a candidate pair (default: 2.5)."
    )
    parser.add_argument(
        "--limit", type=int, default=60,
        help="Maximum candidates to print to terminal (default: 60)."
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"ERROR: {input_path} not found.")
        sys.exit(1)

    author_filter = args.author.strip() if args.author else None
    print(f"Loading {input_path}"
          + (f" (filtered to '{author_filter}')" if author_filter else "") + " ...")

    rows = load_deduplicated(input_path, author_filter)
    print(f"  {len(rows)} rows loaded.")

    print_edition_overview(rows)

    print(f"Scanning for missed matches (min_score={args.min_score}) ...")
    candidates = find_missed_matches(rows, min_score=args.min_score)
    print(f"  Found {len(candidates)} candidates.\n")

    print_candidates(candidates, limit=args.limit)

    if candidates:
        write_csv(candidates, args.output)


if __name__ == "__main__":
    main()
