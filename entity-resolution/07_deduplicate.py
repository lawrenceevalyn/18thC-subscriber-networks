"""
================================================================================
                Entity-Resolution Pipeline — 07_deduplicate.py
================================================================================
RUN WITH: python3 07_deduplicate.py <parsed.csv> --output outputs/deduplicated.csv
          python3 07_deduplicate.py <parsed.csv> \
              --output outputs/deduplicated.csv \
              --title-auto outputs/05-title-matches.csv \
              --title-candidates outputs/05-title-candidates.csv \
              --component-auto outputs/06-auto-resolved.csv \
              --component-candidates outputs/06-candidates.csv

DESCRIPTION:
    Reads the parsed CSV plus all four match files (title auto/candidates +
    component auto/candidates) and writes a deduplicated CSV — same rows as
    the parsed input, but with collapsed person_id values so matched entries
    share a single ID.

    Processing order:
      1. Title auto-resolved
      2. Title candidates
      3. Component auto-resolved
      4. Component candidates (highest precedence)

    Later files overwrite earlier assignments when an entry appears
    in multiple match files.

    Match column convention:
        "y" on the first row of a group → accept the group.
        Blank or "n" on the first row   → reject the group.
        "x" on any individual row       → exclude that entry.

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


def parse_match_file(csv_path):
    path = Path(csv_path)
    if not path.is_file():
        print(f"WARNING: {path} not found, skipping.")
        return []

    rows_by_group = defaultdict(list)
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if "group_id" not in reader.fieldnames or "match" not in reader.fieldnames or "entry_id" not in reader.fieldnames:
            print(f"ERROR: {path} is missing required columns (group_id, match, entry_id)")
            sys.exit(1)
        for row in reader:
            rows_by_group[row["group_id"]].append(row)

    groups = []
    for group_id, rows in rows_by_group.items():
        first_match = rows[0]["match"].strip().lower()
        accepted = (first_match == "y")
        included_entries = []
        for row in rows:
            if row["match"].strip().lower() == "x":
                continue
            included_entries.append(row["entry_id"])
        groups.append({
            "group_id": group_id,
            "accepted": accepted,
            "entries": included_entries,
        })
    return groups


def build_person_id_mapping(match_file_groups_list):
    mapping = {}
    stats = {"accepted": 0, "rejected": 0, "warnings": 0}
    seen = {}

    for label, groups in match_file_groups_list:
        for group in groups:
            if not group["accepted"]:
                stats["rejected"] += 1
                continue
            entries = group["entries"]
            if len(entries) < 2:
                stats["rejected"] += 1
                continue
            stats["accepted"] += 1
            canonical_id = entries[0]
            for entry_id in entries:
                if entry_id in seen:
                    prev = seen[entry_id]
                    if prev != (label, group["group_id"]):
                        stats["warnings"] += 1
                seen[entry_id] = (label, group["group_id"])
                mapping[entry_id] = canonical_id

    return mapping, stats


def main():
    parser = argparse.ArgumentParser(
        description="Apply entity resolution and write a deduplicated CSV."
    )
    parser.add_argument(
        "parsed_csv",
        help="Path to the parsed CSV (from name-parsing/04_parse_names.py)."
    )
    parser.add_argument(
        "--output", default="outputs/deduplicated.csv",
        help="Path to write the deduplicated CSV."
    )
    parser.add_argument(
        "--title-auto", default="outputs/05-title-matches.csv",
        help="Path to title auto-resolved matches."
    )
    parser.add_argument(
        "--title-candidates", default="outputs/05-title-candidates.csv",
        help="Path to title candidate matches."
    )
    parser.add_argument(
        "--component-auto", default="outputs/06-auto-resolved.csv",
        help="Path to component auto-resolved matches."
    )
    parser.add_argument(
        "--component-candidates", default="outputs/06-candidates.csv",
        help="Path to component candidate matches."
    )
    args = parser.parse_args()

    parsed_path = Path(args.parsed_csv)
    if not parsed_path.is_file():
        print(f"ERROR: {parsed_path} is not a file.")
        sys.exit(1)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    match_files = [
        ("title_auto", parse_match_file(args.title_auto)),
        ("title_candidates", parse_match_file(args.title_candidates)),
        ("component_auto", parse_match_file(args.component_auto)),
        ("component_candidates", parse_match_file(args.component_candidates)),
    ]

    for label, groups in match_files:
        accepted = sum(1 for g in groups if g["accepted"] and len(g["entries"]) >= 2)
        print(f"  {label}: {len(groups)} groups ({accepted} accepted)")

    mapping, stats = build_person_id_mapping(match_files)

    rows = []
    with open(parsed_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        for row in reader:
            rows.append(row)

    changed_count = 0
    for row in rows:
        entry_id = row["entry_id"]
        if entry_id in mapping:
            new_pid = mapping[entry_id]
            if row["person_id"] != new_pid:
                row["person_id"] = new_pid
                changed_count += 1

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    unique_pids = len(set(mapping.values()))
    print(f"\n--- Summary ---")
    print(f"  Groups accepted:               {stats['accepted']}")
    print(f"  Groups rejected:               {stats['rejected']}")
    print(f"  Unique merged identities:      {unique_pids}")
    print(f"  Entries with updated person_id: {changed_count}")
    if stats["warnings"]:
        print(f"  Warnings:                      {stats['warnings']}")
    print(f"\nWrote deduplicated CSV to {output_path}")


if __name__ == "__main__":
    main()
