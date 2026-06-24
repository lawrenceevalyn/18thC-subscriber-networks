"""
================================================================================
       Bipartite Graph Pipeline for Eighteenth-Century Subscriber Lists
                          05_match_titles.py
================================================================================
RUN WITH: python3 05_match_titles.py outputs/04-parsed.csv
          python3 05_match_titles.py outputs/04-parsed.csv \
              --dictionary resources/title-holders.csv

DESCRIPTION:
    Matches titled entries (name_type == "titled") across editions.

    Default assumption: same title = same person. This auto-resolves
    groups unless:
      - An edition collision occurs (same title appears twice in one
        edition, suggesting two different people).
      - The title-holders dictionary shows the title changed hands
        between editions in the group (holder disambiguation).

    Outputs two match files:
      - Title auto-resolved matches (high confidence).
      - Title candidates for review (ambiguous cases).

    Entry IDs of matched titled entries are written to stdout so that
    06_match_components.py can exclude them from component matching.

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


REQUIRED_COLUMNS = {"entry_id", "person_id", "name_type", "title_key", "edition", "year"}


def load_title_holders(dict_path):
    holders = defaultdict(list)
    if not dict_path.exists():
        return holders
    with open(dict_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            start = int(row["start_year"]) if row["start_year"] else None
            end = int(row["end_year"]) if row["end_year"] else None
            holders[row["title_key"].lower()].append({
                "person_name": row["person_name"],
                "wikidata_id": row.get("wikidata_id", ""),
                "start_year": start,
                "end_year": end,
            })
    return holders


def find_holder_for_year(holders_list, year):
    matches = []
    for h in holders_list:
        s, e = h["start_year"], h["end_year"]
        if s is None and e is None:
            matches.append(h)
        elif s is None and e is not None:
            if year <= e:
                matches.append(h)
        elif s is not None and e is None:
            if year >= s:
                matches.append(h)
        else:
            if s <= year <= e:
                matches.append(h)
    if len(matches) == 1:
        return matches[0]
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Match titled entries across editions."
    )
    parser.add_argument(
        "input_csv",
        help="Path to the parsed CSV (from 04_parse_names.py)."
    )
    parser.add_argument(
        "--dictionary", default="resources/title-holders.csv",
        help="Path to the title-holders dictionary."
    )
    parser.add_argument(
        "--auto-output", default="outputs/05-title-matches.csv",
        help="Path for auto-resolved title matches."
    )
    parser.add_argument(
        "--candidates-output", default="outputs/05-title-candidates.csv",
        help="Path for title match candidates needing review."
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
        for row in reader:
            rows.append(row)

    titled_rows = [r for r in rows if r["name_type"] == "titled" and r["title_key"]]
    print(f"Found {len(titled_rows)} titled entries out of {len(rows)} total")

    holders = load_title_holders(Path(args.dictionary))
    print(f"Loaded {sum(len(v) for v in holders.values())} title-holder records")

    # Group titled entries by title_key.
    groups = defaultdict(list)
    for row in titled_rows:
        groups[row["title_key"]].append(row)

    match_columns = [
        "group_id", "match", "entry_id", "person_id",
        "title_key", "title_holder",
        "normalized_name", "listed as",
        "book", "edition", "year", "match_tier",
    ]

    auto_rows = []
    candidate_rows = []
    matched_entry_ids = set()
    group_counter = 0

    for title_key, entries in sorted(groups.items()):
        if len(entries) < 2:
            continue

        group_counter += 1
        group_id = f"tt_{group_counter:04d}"

        edition_keys = [(e["book"], e["edition"]) for e in entries]
        has_collision = len(edition_keys) != len(set(edition_keys))

        # Try holder disambiguation.
        holder_groups = defaultdict(list)
        disambiguation_worked = False

        if title_key in holders and len(holders[title_key]) > 1:
            for entry in entries:
                year = int(entry["year"])
                holder = find_holder_for_year(holders[title_key], year)
                if holder:
                    holder_groups[holder["person_name"]].append(entry)
                else:
                    holder_groups["_unresolved_"].append(entry)

            if len(holder_groups) > 1:
                disambiguation_worked = True

        if disambiguation_worked:
            for holder_name, holder_entries in holder_groups.items():
                if len(holder_entries) < 2:
                    continue
                group_counter += 1
                sub_group_id = f"tt_{group_counter:04d}"
                sub_edition_keys = [(e["book"], e["edition"]) for e in holder_entries]
                sub_collision = len(sub_edition_keys) != len(set(sub_edition_keys))

                for entry in holder_entries:
                    match_row = {
                        "group_id": sub_group_id,
                        "match": "" if sub_collision else "y",
                        "entry_id": entry["entry_id"],
                        "person_id": entry["person_id"],
                        "title_key": entry["title_key"],
                        "title_holder": holder_name if holder_name != "_unresolved_" else "",
                        "normalized_name": entry["normalized_name"],
                        "listed as": entry.get("listed as", ""),
                        "book": entry["book"],
                        "edition": entry["edition"],
                        "year": entry["year"],
                        "match_tier": "title_holder",
                    }
                    if sub_collision:
                        candidate_rows.append(match_row)
                    else:
                        auto_rows.append(match_row)
                        matched_entry_ids.add(entry["entry_id"])
        else:
            for entry in entries:
                year = int(entry["year"])
                holder = find_holder_for_year(holders.get(title_key, []), year)
                holder_name = holder["person_name"] if holder else ""

                match_row = {
                    "group_id": group_id,
                    "match": "" if has_collision else "y",
                    "entry_id": entry["entry_id"],
                    "person_id": entry["person_id"],
                    "title_key": entry["title_key"],
                    "title_holder": holder_name,
                    "normalized_name": entry["normalized_name"],
                    "listed as": entry.get("listed as", ""),
                    "book": entry["book"],
                    "edition": entry["edition"],
                    "year": entry["year"],
                    "match_tier": "title_same",
                }
                if has_collision:
                    candidate_rows.append(match_row)
                else:
                    auto_rows.append(match_row)
                    matched_entry_ids.add(entry["entry_id"])

    # Write outputs.
    auto_path = Path(args.auto_output)
    auto_path.parent.mkdir(parents=True, exist_ok=True)
    with open(auto_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=match_columns)
        writer.writeheader()
        writer.writerows(auto_rows)

    cand_path = Path(args.candidates_output)
    cand_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cand_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=match_columns)
        writer.writeheader()
        writer.writerows(candidate_rows)

    auto_groups = len(set(r["group_id"] for r in auto_rows))
    cand_groups = len(set(r["group_id"] for r in candidate_rows))
    print(f"\nAuto-resolved: {auto_groups} groups ({len(auto_rows)} entries)")
    print(f"Candidates:    {cand_groups} groups ({len(candidate_rows)} entries)")
    print(f"Matched entry IDs: {len(matched_entry_ids)}")

    print(f"\nWrote {auto_path}")
    print(f"Wrote {cand_path}")


if __name__ == "__main__":
    main()
