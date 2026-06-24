"""
================================================================================
       Bipartite Graph Pipeline for Eighteenth-Century Subscriber Lists
                              01_ingest.py
================================================================================
RUN WITH: python3 01_ingest.py <input_dir>
          python3 01_ingest.py <input_dir> --output outputs/01-consolidated.csv

DESCRIPTION:
    Reads all CSV files in the input directory and consolidates them into
    a single CSV. Each row represents one subscriber entry from one
    edition of one book.

    A unique entry_id is generated for each row from the author, book
    title, edition, and the subscriber's number in the original list.
    A person_id column is set to match entry_id; downstream resolution
    steps overwrite person_id so that entries for the same person share
    a single identifier.

    If a "refined listing" column is present and non-empty for a row,
    that value is used for "normalization input"; otherwise, "listed as"
    is used.

    Any extra columns in the input CSV are preserved alongside the
    required ones, so downstream parsing and matching steps can use them.

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


REQUIRED_COLUMNS = {"listed as", "book", "author", "edition", "year", "no."}

LEADING_OUTPUT_COLUMNS = [
    "entry_id", "person_id", "normalization input", "listed as",
    "book", "author", "edition", "year",
]


def make_entry_id(author, book, edition, number):
    last_name = author.split()[0].rstrip(",")
    articles = {"a", "an", "the"}
    words = book.split()
    first_word = next(
        (w for w in words if w.lower() not in articles),
        words[0],
    )
    return f"{last_name}-{first_word}-{edition}-{int(number):04d}"


def ingest_one_file(csv_path):
    raw_rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            print(f"WARNING: Skipping {csv_path.name} - missing columns: {missing}")
            return None, 0, []

        has_refined = "refined listing" in reader.fieldnames
        input_fieldnames = list(reader.fieldnames)

        for row in reader:
            raw_rows.append(row)

    max_no = {}
    for row in raw_rows:
        edition = row["edition"]
        no_str = row["no."].strip()
        if no_str:
            try:
                no_int = int(no_str)
                max_no[edition] = max(max_no.get(edition, 0), no_int)
            except ValueError:
                pass

    next_no = {ed: mx + 1 for ed, mx in max_no.items()}
    auto_numbered = 0
    refined_count = 0

    rows = []
    seen_ids = set()

    for row in raw_rows:
        blank_fields = [
            col for col in ("author", "book", "edition", "listed as")
            if not row[col].strip()
        ]
        if blank_fields:
            print(f"    WARNING: Skipping row in {csv_path.name} - "
                  f"blank {', '.join(blank_fields)}")
            continue

        edition = row["edition"]
        no_str = row["no."].strip()

        if not no_str:
            assigned = next_no.get(edition, 1)
            next_no[edition] = assigned + 1
            no_str = str(assigned)
            auto_numbered += 1

        entry_id = make_entry_id(row["author"], row["book"], edition, no_str)

        if entry_id in seen_ids:
            print(
                f"ERROR: Duplicate edition+no. pair in {csv_path.name}: "
                f"edition '{row['edition']}', no. '{row['no.']}'\n"
                f"  Each edition+no. pair must be unique within a file.\n"
                f"  Please fix the source data and re-run."
            )
            sys.exit(1)
        seen_ids.add(entry_id)

        if has_refined and row.get("refined listing", "").strip():
            normalization_input = row["refined listing"]
            refined_count += 1
        else:
            normalization_input = row["listed as"]

        out_row = {
            "entry_id": entry_id,
            "person_id": entry_id,
            "normalization input": normalization_input,
        }
        for col in input_fieldnames:
            if col not in out_row and col not in ("no.", "refined listing"):
                out_row[col] = row[col]

        rows.append(out_row)

    if auto_numbered:
        print(f"    Auto-numbered {auto_numbered} entries with blank no. column")

    extra_cols = [
        c for c in input_fieldnames
        if c not in set(LEADING_OUTPUT_COLUMNS) | {"no.", "refined listing"}
    ]
    return rows, refined_count, extra_cols


def main():
    parser = argparse.ArgumentParser(
        description="Consolidate raw subscriber-list CSVs into a single CSV."
    )
    parser.add_argument(
        "input_dir",
        help="Directory containing raw CSV spreadsheets."
    )
    parser.add_argument(
        "--output", default="outputs/01-consolidated.csv",
        help="Path for the consolidated CSV output (default: outputs/01-consolidated.csv)"
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.is_dir():
        print(f"ERROR: {input_dir} is not a directory.")
        sys.exit(1)

    csv_files = sorted(input_dir.glob("*.csv"))
    if not csv_files:
        print(f"ERROR: No CSV files found in {input_dir}")
        sys.exit(1)

    print(f"Found {len(csv_files)} CSV file(s) in {input_dir}")

    all_rows = []
    all_extra_cols = []
    total_refined = 0
    skipped = 0

    for csv_path in csv_files:
        rows, refined_count, extra_cols = ingest_one_file(csv_path)
        if rows is None:
            skipped += 1
            continue
        print(f"  {csv_path.name}: {len(rows)} rows", end="")
        if refined_count > 0:
            print(f" ({refined_count} using 'refined listing')")
        else:
            print()
        all_rows.extend(rows)
        total_refined += refined_count
        for col in extra_cols:
            if col not in all_extra_cols:
                all_extra_cols.append(col)

    if skipped:
        print(f"\nSkipped {skipped} file(s) due to missing columns.")

    output_columns = LEADING_OUTPUT_COLUMNS + all_extra_cols

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=output_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nWrote {len(all_rows)} rows to {output_path}")
    if total_refined > 0:
        print(f"  ({total_refined} rows used 'refined listing' instead of 'listed as')")
    if all_extra_cols:
        print(f"  Extra columns preserved: {', '.join(all_extra_cols)}")


if __name__ == "__main__":
    main()
