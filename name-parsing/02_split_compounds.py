"""
================================================================================
       Bipartite Graph Pipeline for Eighteenth-Century Subscriber Lists
                          02_split_compounds.py
================================================================================
RUN WITH: python3 02_split_compounds.py outputs/01-consolidated.csv
          python3 02_split_compounds.py outputs/01-consolidated.csv \
              --output outputs/01-consolidated.csv

DESCRIPTION:
    Splits compound subscriber entries (rows where two people are listed
    together as a single entry) into separate rows, one per person.

    Compound entries are identified by " and " joining two personal or
    peerage titles:
        "Lord and Lady Barnard"         -> "Lord Barnard" + "Lady Barnard"
        "Duke and Duchess of Montague"  -> "Duke of Montague" +
                                          "Duchess of Montague"


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


REQUIRED_COLUMNS = {"entry_id", "person_id", "normalization input"}

PERSONAL_TITLES = {
    "Mr.", "Mrs.", "Ms.", "Miss", "Messrs.",
    "Dr.", "Rev.", "Capt.", "Col.", "Lt.", "Adm.", "Sgt.", "Prof.",
    "Mister", "Reverend", "Captain", "Colonel", "Lieutenant",
    "Admiral", "Doctor", "Professor",
    "Sir", "Dame",
    "Lord", "Lady",
    "Duke", "Duchess",
    "Earl", "Countess",
    "Marquess", "Marquis", "Marchioness",
    "Viscount", "Viscountess", "Visc.",
    "Baron", "Baroness",
}

TITLE_MODIFIERS = {"Dowager", "Right", "Most"}


def find_title_at_start(text):
    words = text.split()
    if not words:
        return None, None
    if len(words) >= 2 and words[0] in TITLE_MODIFIERS:
        if words[1] in PERSONAL_TITLES:
            title = f"{words[0]} {words[1]}"
            suffix = " ".join(words[2:])
            return title, suffix
    if words[0] in PERSONAL_TITLES:
        suffix = " ".join(words[1:])
        return words[0], suffix
    return None, None


def text_contains_title(text):
    return any(word in PERSONAL_TITLES for word in text.split())


def try_split(name):
    if " and " not in name:
        return [name]
    and_index = name.index(" and ")
    left = name[:and_index].strip()
    right = name[and_index + 5:].strip()
    right_title, shared_suffix = find_title_at_start(right)
    if right_title is None:
        return [name]
    if not text_contains_title(left):
        return [name]
    person2 = right
    if shared_suffix:
        person1 = f"{left} {shared_suffix}"
    else:
        person1 = left
    return [person1, person2]


def main():
    parser = argparse.ArgumentParser(
        description="Split compound subscriber entries into separate rows."
    )
    parser.add_argument(
        "input_csv",
        help="Path to the consolidated CSV (from 01_ingest.py)."
    )
    parser.add_argument(
        "--output", default=None,
        help="Path for the output CSV. Defaults to overwriting the input file."
    )
    args = parser.parse_args()

    input_path = Path(args.input_csv)
    if not input_path.is_file():
        print(f"ERROR: {input_path} is not a file.")
        sys.exit(1)

    output_path = Path(args.output) if args.output else input_path

    rows = []
    with open(input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            print(f"ERROR: {input_path} is missing columns: {missing}")
            sys.exit(1)
        input_fieldnames = list(reader.fieldnames)
        for row in reader:
            rows.append(row)

    print(f"Read {len(rows)} rows from {input_path}")

    idx = input_fieldnames.index("entry_id")
    output_fieldnames = (
        input_fieldnames[:idx + 1]
        + ["source_entry_id"]
        + input_fieldnames[idx + 1:]
    )

    output_rows = []
    split_count = 0

    for row in rows:
        original_entry_id = row["entry_id"]
        names = try_split(row["normalization input"])

        if len(names) == 1:
            row["source_entry_id"] = original_entry_id
            output_rows.append(row)
        else:
            split_count += 1
            suffixes = ["a", "b"]
            for i, name in enumerate(names):
                new_entry_id = f"{original_entry_id}{suffixes[i]}"
                new_row = dict(row)
                new_row["entry_id"] = new_entry_id
                new_row["source_entry_id"] = original_entry_id
                new_row["person_id"] = new_entry_id
                new_row["normalization input"] = name
                output_rows.append(new_row)
            print(f"  Split: \"{row['normalization input']}\"")
            print(f"    -> \"{names[0]}\"")
            print(f"    -> \"{names[1]}\"")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=output_fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"\n--- Summary ---")
    print(f"  Input rows:     {len(rows)}")
    print(f"  Entries split:  {split_count}")
    print(f"  Output rows:    {len(output_rows)}")
    print(f"  Net new rows:   {len(output_rows) - len(rows)}")
    print(f"\nWrote {len(output_rows)} rows to {output_path}")


if __name__ == "__main__":
    main()
