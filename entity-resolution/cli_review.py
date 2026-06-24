"""
================================================================================
       Bipartite Graph Pipeline for Eighteenth-Century Subscriber Lists
                            cli_review.py
================================================================================
RUN WITH: python3 cli_review.py outputs/06-candidates.csv
          python3 cli_review.py outputs/06-candidates.csv --filter fuzzy
          python3 cli_review.py outputs/05-title-candidates.csv

DESCRIPTION:
    Interactive terminal-based review tool for candidate match groups.
    Alternative to editing the CSV in a spreadsheet.

    Displays one candidate group at a time with parsed fields in aligned
    columns. Keybindings:
        y       Accept the group (mark all as "y")
        n       Reject the group (mark first as "n")
        x <#>   Exclude a specific entry by its row number
        s       Skip this group (leave unchanged)
        q       Quit and save

    Progress is saved after each decision. The tool can resume from
    where it left off (skips already-reviewed groups).

    Use --filter to show only groups matching a specific rule name
    (e.g., --filter fuzzy to review only fuzzy matches).

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


def load_candidates(csv_path):
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        for row in reader:
            rows.append(row)
    return fieldnames, rows


def group_rows(rows):
    groups = defaultdict(list)
    order = []
    for row in rows:
        gid = row["group_id"]
        if gid not in groups:
            order.append(gid)
        groups[gid].append(row)
    return order, groups


def is_reviewed(group_rows):
    first_match = group_rows[0]["match"].strip().lower()
    return first_match in ("y", "n")


def display_group(group_id, entries, group_num, total_groups):
    rule = entries[0].get("match_rule", "")
    tier = entries[0].get("match_tier", "")

    print(f"\n{'=' * 70}")
    print(f"  Group {group_num} of {total_groups}  |  ID: {group_id}  |  "
          f"Rule: {rule}  |  Tier: {tier}")
    print(f"{'=' * 70}")

    display_cols = [
        ("edition", 4),
        ("year", 4),
        ("normalized_name", 35),
        ("parsed_title", 8),
        ("parsed_first", 12),
        ("parsed_last", 15),
        ("parsed_postnominals", 8),
        ("parsed_location", 12),
    ]

    header = f"  {'#':>3}  "
    for col_name, width in display_cols:
        label = col_name.replace("parsed_", "").replace("normalized_", "")
        header += f"{label:<{width}}  "
    print(header)
    print(f"  {'─' * (len(header) - 2)}")

    for i, entry in enumerate(entries, 1):
        marker = entry["match"].strip()
        prefix = f"  {i:>3}  "
        if marker == "x":
            prefix = f"  {i:>3}x "

        line = prefix
        for col_name, width in display_cols:
            val = entry.get(col_name, "")
            if len(val) > width:
                val = val[:width - 1] + "…"
            line += f"{val:<{width}}  "
        print(line)

    print()


def save_csv(csv_path, fieldnames, all_rows):
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)


def main():
    parser = argparse.ArgumentParser(
        description="Interactively review candidate match groups."
    )
    parser.add_argument(
        "candidates_csv",
        help="Path to the candidates CSV file."
    )
    parser.add_argument(
        "--filter", default=None,
        help="Only show groups matching this rule name (e.g., 'fuzzy_last_first')."
    )
    args = parser.parse_args()

    csv_path = Path(args.candidates_csv)
    if not csv_path.is_file():
        print(f"ERROR: {csv_path} is not a file.")
        sys.exit(1)

    fieldnames, all_rows = load_candidates(csv_path)
    order, groups = group_rows(all_rows)

    # Filter by rule if requested.
    if args.filter:
        order = [
            gid for gid in order
            if args.filter.lower() in groups[gid][0].get("match_rule", "").lower()
        ]

    # Find unreviewed groups.
    unreviewed = [gid for gid in order if not is_reviewed(groups[gid])]
    total = len(order)
    pending = len(unreviewed)

    print(f"Loaded {total} groups from {csv_path}")
    print(f"Already reviewed: {total - pending}")
    print(f"Pending review:   {pending}")

    if pending == 0:
        print("\nAll groups have been reviewed.")
        return

    reviewed_count = 0

    for gid in unreviewed:
        entries = groups[gid]
        group_num = order.index(gid) + 1

        display_group(gid, entries, group_num, total)

        prompt = "[y] Match all  [n] Reject  [x #] Exclude entry  [s] Skip  [q] Quit\n> "
        try:
            choice = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nSaving and quitting...")
            break

        if choice == "y":
            for entry in entries:
                if entry["match"].strip().lower() != "x":
                    entry["match"] = "y"
            print(f"  Marked group {gid} as MATCH.")
            reviewed_count += 1

        elif choice == "n":
            entries[0]["match"] = "n"
            print(f"  Marked group {gid} as REJECTED.")
            reviewed_count += 1

        elif choice.startswith("x "):
            try:
                num = int(choice.split()[1])
                if 1 <= num <= len(entries):
                    entries[num - 1]["match"] = "x"
                    print(f"  Excluded entry #{num} from group {gid}.")
                else:
                    print(f"  Invalid entry number. Valid range: 1-{len(entries)}")
                    continue
            except (ValueError, IndexError):
                print("  Usage: x <number>")
                continue

        elif choice == "s":
            print(f"  Skipped group {gid}.")
            continue

        elif choice == "q":
            print("Saving and quitting...")
            break

        else:
            print("  Unknown command. Use y, n, x <#>, s, or q.")
            continue

        save_csv(csv_path, fieldnames, all_rows)

    save_csv(csv_path, fieldnames, all_rows)
    print(f"\nReviewed {reviewed_count} groups this session.")
    print(f"Saved to {csv_path}")


if __name__ == "__main__":
    main()
