"""
================================================================================
              Name-Parsing Pipeline for Subscriber Lists
                              pipeline.py
================================================================================
RUN WITH: python3 pipeline.py [--input DIR] [--output FILE]

DESCRIPTION:
    Takes a directory of subscriber-list CSVs (each with a `listed as`
    column and book/author/edition/year metadata) and produces a single
    parsed CSV with structured fields per entry:

        person_id, entry_id, parsed_title, parsed_first, parsed_last,
        parsed_postnominals, parsed_location, parsed_notes, name_type,
        plus the source metadata columns.

    Pipeline stages:
        1. 01_ingest.py            — consolidate input CSVs, assign IDs
        2. 02_split_compounds.py   — split "Lord and Lady X" into rows
        3. 03_normalize.py         — spelling, punctuation, abbreviations
        4. 04_parse_names.py       — decompose into structured fields

    Paths come from pipeline.toml.
--------------------------------------------------------------------------------
LICENSE:
    MIT License
    Copyright (c) 2026 Lawrence Evalyn
================================================================================
"""

import argparse
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


HERE = Path(__file__).parent


def load_config():
    config_path = HERE / "pipeline.toml"
    if not config_path.exists():
        print(f"ERROR: {config_path} not found.")
        sys.exit(1)
    with open(config_path, "rb") as f:
        return tomllib.load(f)


def run_step(description, cmd):
    print(f"\n{'─' * 60}")
    print(f"  {description}")
    print(f"{'─' * 60}")
    result = subprocess.run(cmd, shell=False, cwd=HERE)
    if result.returncode != 0:
        print(f"\nERROR: Step failed with exit code {result.returncode}")
        sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(
        description="Name-parsing pipeline: namelist CSVs → parsed CSV."
    )
    parser.add_argument("--input", metavar="DIR",
                        help="Override the input directory (default from pipeline.toml).")
    parser.add_argument("--output", metavar="FILE",
                        help="Override the final parsed CSV path (default from pipeline.toml).")
    args = parser.parse_args()

    config = load_config()
    paths = config["paths"]

    input_dir = args.input or paths["input_dir"]
    parsed = args.output or paths["parsed"]

    run_step(
        "Step 1: Ingest spreadsheets",
        ["python3", "01_ingest.py", input_dir,
         "--output", paths["consolidated"]],
    )
    run_step(
        "Step 2: Split compound entries",
        ["python3", "02_split_compounds.py", paths["consolidated"]],
    )
    run_step(
        "Step 3: Normalize names",
        ["python3", "03_normalize.py", paths["consolidated"],
         "--output", paths["normalized"]],
    )
    run_step(
        "Step 4: Parse names into components",
        ["python3", "04_parse_names.py", paths["normalized"],
         "--output", parsed],
    )

    print(f"\nDone. Parsed CSV at: {parsed}")


if __name__ == "__main__":
    main()
