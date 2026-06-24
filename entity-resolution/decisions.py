"""
================================================================================
                Entity-Resolution Pipeline — decisions.py
================================================================================
RUN WITH: python3 decisions.py harvest outputs/06-candidates.csv
          python3 decisions.py apply   outputs/06-candidates.csv
          python3 decisions.py harvest outputs/06-candidates.csv --ledger resources/decisions.csv

DESCRIPTION:
    A durable, pair-level record of human match decisions, so manual
    review survives re-running the matcher.

    The problem it solves: 06_match_components.py regenerates
    06-candidates.csv from scratch every run, with the `match` column
    blank, and group ids (cm_0001, ...) are a re-assigned sequential
    counter. So review verdicts stored in that file are wiped on every
    re-match, and could not be re-attached by group id even if they
    survived.

    The fix: store every verdict as a PAIR of entry_ids — the only
    identifier stable across re-runs — in a separate ledger
    (resources/decisions.csv). Two operations move data between the
    ledger and the (disposable) candidates file:

        harvest  reviewed candidates `match` column  ->  ledger pairs
        apply    ledger pairs  ->  fresh candidates `match` column

    A reviewed group is decomposed into pairwise verdicts:
        accept (y) : every included pair is "same person" (y);
                     each excluded (x) entry vs each included is "n".
        reject (n) : every pair in the group is "different" (n).
    On apply, a fresh group is reconstructed from those pairs:
        all internal pairs y  -> mark the whole group y
        all internal pairs n  -> mark the group rejected (n)
        decided but mixed     -> accept the y-connected cluster of the
                                 canonical row; exclude (x) entries with
                                 an n to it
        any internal pair unknown -> leave the group blank for review
                                 (no decision is lost; the known pairs
                                 stay in the ledger)

    Because apply rewrites the candidates `match` column, the rest of the
    pipeline (cli_review.py, 07_deduplicate.py) is unchanged.

--------------------------------------------------------------------------------
LICENSE:
    MIT License
    Copyright (c) 2026 Lawrence Evalyn
================================================================================
"""

import csv
import argparse
import sys
from itertools import combinations
from pathlib import Path
from collections import defaultdict


LEDGER_COLUMNS = [
    "entry_a", "entry_b", "verdict",
    "name_a", "name_b", "context_a", "context_b", "note",
]

DEFAULT_LEDGER = "resources/decisions.csv"


# ---------------------------------------------------------------------------
# Ledger IO
# ---------------------------------------------------------------------------

def pair_key(a, b):
    """Canonical, order-independent key for a pair of entry_ids."""
    return tuple(sorted((a, b)))


def load_ledger(path):
    """Return {(entry_a, entry_b): record} keyed by canonical pair."""
    ledger = {}
    p = Path(path)
    if not p.is_file():
        return ledger
    with open(p, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = pair_key(row["entry_a"], row["entry_b"])
            ledger[key] = row
    return ledger


def save_ledger(path, ledger):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Stable, human-readable ordering: verdict then names.
    rows = sorted(
        ledger.values(),
        key=lambda r: (r.get("verdict", ""), r.get("name_a", ""), r.get("name_b", "")),
    )
    with open(p, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LEDGER_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _context(row):
    return f"{row.get('book', '')}|{row.get('edition', '')}"


def _record(row_a, row_b, verdict, note=""):
    """Build a ledger record for an ordered-canonical pair."""
    a, b = row_a["entry_id"], row_b["entry_id"]
    if a <= b:
        first, second = row_a, row_b
    else:
        first, second = row_b, row_a
    return {
        "entry_a": first["entry_id"],
        "entry_b": second["entry_id"],
        "verdict": verdict,
        "name_a": first.get("normalized_name", ""),
        "name_b": second.get("normalized_name", ""),
        "context_a": _context(first),
        "context_b": _context(second),
        "note": note,
    }


# ---------------------------------------------------------------------------
# Candidates IO
# ---------------------------------------------------------------------------

def load_candidate_groups(path):
    """Return (fieldnames, all_rows, order, groups-by-id) for a candidates CSV."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)
    groups = defaultdict(list)
    order = []
    for row in rows:
        gid = row["group_id"]
        if gid not in groups:
            order.append(gid)
        groups[gid].append(row)
    return fieldnames, rows, order, groups


# ---------------------------------------------------------------------------
# harvest: reviewed candidates -> ledger
# ---------------------------------------------------------------------------

def group_to_pairs(entries):
    """Decompose one reviewed group into (row_a, row_b, verdict) decisions.

    Returns [] for an unreviewed group (blank first row).
    """
    first = entries[0]["match"].strip().lower()
    if first not in ("y", "n"):
        return []

    included = [e for e in entries if e["match"].strip().lower() != "x"]
    excluded = [e for e in entries if e["match"].strip().lower() == "x"]

    decisions = []
    if first == "y":
        for a, b in combinations(included, 2):
            decisions.append((a, b, "y"))
        # An excluded entry is a confirmed non-match with the accepted set.
        for x in excluded:
            for inc in included:
                decisions.append((x, inc, "n"))
    else:  # rejected: nothing in this group is the same person
        for a, b in combinations(entries, 2):
            decisions.append((a, b, "n"))
    return decisions


def harvest(candidates_path, ledger_path):
    _, _, order, groups = load_candidate_groups(candidates_path)
    ledger = load_ledger(ledger_path)

    added = updated = conflicts = 0
    for gid in order:
        for row_a, row_b, verdict in group_to_pairs(groups[gid]):
            key = pair_key(row_a["entry_id"], row_b["entry_id"])
            rec = _record(row_a, row_b, verdict)
            existing = ledger.get(key)
            if existing is None:
                ledger[key] = rec
                added += 1
            elif existing["verdict"] != verdict:
                # Human changed their mind: newest verdict wins, but flag it.
                conflicts += 1
                rec["note"] = (existing.get("note", "") +
                               f" [was {existing['verdict']}, now {verdict}]").strip()
                ledger[key] = rec
                updated += 1

    save_ledger(ledger_path, ledger)
    print(f"Harvested into {ledger_path}: "
          f"{added} new, {updated} updated ({conflicts} changed verdicts), "
          f"{len(ledger)} total pairs.")


# ---------------------------------------------------------------------------
# apply: ledger -> fresh candidates match column
# ---------------------------------------------------------------------------

def _resolve_group(entries, ledger):
    """Decide the match-column values for one fresh group from the ledger.

    The group's first row anchors any merge (07_deduplicate keys acceptance
    on row 0), so a decision is representable only when the canonical entry
    is part of the accepted cluster. Returns a dict
    {entry_id: "y"|"n"|"x"} or None to leave the group blank for review.
    """
    ids = [e["entry_id"] for e in entries]
    if len(ids) < 2:
        return None

    def verdict(a, b):
        rec = ledger.get(pair_key(a, b))
        return rec["verdict"] if rec else None

    # Grow the canonical entry's cluster over known "same person" (y) pairs.
    canonical = ids[0]
    cluster = {canonical}
    changed = True
    while changed:
        changed = False
        for a, b in combinations(ids, 2):
            if verdict(a, b) == "y":
                if a in cluster and b not in cluster:
                    cluster.add(b); changed = True
                elif b in cluster and a not in cluster:
                    cluster.add(a); changed = True

    # A recorded "n" inside the y-cluster is a contradiction — send to review.
    for a, b in combinations(cluster, 2):
        if verdict(a, b) == "n":
            return None

    others = [eid for eid in ids if eid not in cluster]

    if len(cluster) >= 2:
        # Canonical merges with at least one entry. Every other entry must be
        # confidently OUT (an explicit "n" to some cluster member); otherwise
        # its membership is unknown and the group needs review.
        for o in others:
            if not any(verdict(o, c) == "n" for c in cluster):
                return None
        return {**{c: "y" for c in cluster}, **{o: "x" for o in others}}

    # Canonical merges with no one. We can only act if the whole group is a
    # confirmed non-match (all pairs "n"); a y-pair among the *other* entries
    # can't be expressed in this format, so that case goes to review.
    if all(verdict(a, b) == "n" for a, b in combinations(ids, 2)):
        return {eid: "n" for eid in ids}
    return None


def apply(candidates_path, ledger_path):
    fieldnames, rows, order, groups = load_candidate_groups(candidates_path)
    ledger = load_ledger(ledger_path)
    if not ledger:
        print(f"Ledger {ledger_path} is empty or missing; nothing to apply.")
        return

    decided = touched = 0
    for gid in order:
        entries = groups[gid]
        resolution = _resolve_group(entries, ledger)
        if resolution is None:
            continue
        decided += 1
        for e in entries:
            new_val = resolution.get(e["entry_id"], "")
            if e["match"] != new_val:
                e["match"] = new_val
                touched += 1

    with open(candidates_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Applied ledger to {candidates_path}: "
          f"{decided} of {len(order)} groups pre-filled from "
          f"{len(ledger)} recorded pairs ({touched} rows set).")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Pair-level decision ledger: persist match review across re-runs."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_h = sub.add_parser("harvest", help="Reviewed candidates -> ledger.")
    p_h.add_argument("candidates_csv")
    p_h.add_argument("--ledger", default=DEFAULT_LEDGER)

    p_a = sub.add_parser("apply", help="Ledger -> fresh candidates match column.")
    p_a.add_argument("candidates_csv")
    p_a.add_argument("--ledger", default=DEFAULT_LEDGER)

    args = parser.parse_args()

    if not Path(args.candidates_csv).is_file():
        print(f"ERROR: {args.candidates_csv} is not a file.")
        sys.exit(1)

    if args.cmd == "harvest":
        harvest(args.candidates_csv, args.ledger)
    elif args.cmd == "apply":
        apply(args.candidates_csv, args.ledger)


if __name__ == "__main__":
    main()
