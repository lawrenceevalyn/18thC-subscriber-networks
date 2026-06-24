"""
================================================================================
              Entity-Resolution Pipeline for Subscriber Lists
                              pipeline.py
================================================================================
RUN WITH: python3 pipeline.py --force [--strict]
          python3 pipeline.py --apply
          python3 pipeline.py --match
          python3 pipeline.py --review [match_file]

DESCRIPTION:
    Takes a parsed subscriber CSV (from the name-parsing pipeline) and
    produces a deduplicated CSV where matched entries share a single
    person_id.

    Pipeline stages:
        5. 05_match_titles.py      — group entries by positional title
        6. 06_match_components.py  — match non-titled entries by components
        7. 07_deduplicate.py       — apply match decisions, write
                                     deduplicated.csv

    Modes:
        --force     Run steps 5-7 with no human review (auto-accept).
        --match     Run steps 5-6, then restore prior review decisions
                    from the ledger (produces candidate files for review).
        --apply     Run step 7 only (assumes match files already exist
                    and have been reviewed).
        --review    Launch the interactive CLI review tool on a match
                    file (default: outputs/06-candidates.csv), then
                    harvest the verdicts into the durable ledger.
        --harvest   Harvest verdicts from the candidates file into the
                    ledger without launching review (e.g. after editing
                    the match column in a spreadsheet).

    Review decisions are stored pair-by-pair in resources/decisions.csv
    (keyed by entry_id, the only stable identifier across re-runs), so
    re-matching never discards manual work. See decisions.py.

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


def do_match(config, strict=False):
    paths = config["paths"]

    run_step(
        "Step 5: Match titled entries",
        ["python3", "05_match_titles.py", paths["parsed"],
         "--dictionary", paths["dictionary"],
         "--auto-output", paths["title_matches"],
         "--candidates-output", paths["title_candidates"]],
    )
    cmd = ["python3", "06_match_components.py", paths["parsed"],
           "--title-matches", paths["title_matches"],
           "--title-candidates", paths["title_candidates"],
           "--auto-output", paths["auto_resolved"],
           "--candidates-output", paths["candidates"]]
    if strict:
        cmd.append("--strict")
    run_step(
        "Step 6: Match by components" + (" (strict)" if strict else ""),
        cmd,
    )
    # Re-apply previously recorded decisions so re-matching is non-destructive:
    # the freshly regenerated (blank) candidates file gets its match column
    # pre-filled from the durable pair-level ledger.
    run_step(
        "Restore review decisions from ledger",
        ["python3", "decisions.py", "apply", paths["candidates"],
         "--ledger", paths["decisions"]],
    )


def do_harvest(config):
    """Capture verdicts from the candidates file into the durable ledger."""
    paths = config["paths"]
    run_step(
        "Harvest review decisions into ledger",
        ["python3", "decisions.py", "harvest", paths["candidates"],
         "--ledger", paths["decisions"]],
    )


def do_apply(config):
    paths = config["paths"]

    run_step(
        "Step 7: Deduplicate (apply matches)",
        ["python3", "07_deduplicate.py", paths["parsed"],
         "--output", paths["deduplicated"],
         "--title-auto", paths["title_matches"],
         "--title-candidates", paths["title_candidates"],
         "--component-auto", paths["auto_resolved"],
         "--component-candidates", paths["candidates"]],
    )


def do_force(config, strict=False):
    do_match(config, strict=strict)
    do_apply(config)


def do_review(config, match_file=None):
    paths = config["paths"]
    target = match_file or paths["candidates"]

    run_step(
        f"Review: {target}",
        ["python3", "cli_review.py", target],
    )
    # Persist the verdicts just entered so they survive the next re-match.
    # Only the component candidates feed the pair-level ledger.
    if target == paths["candidates"]:
        do_harvest(config)


def main():
    parser = argparse.ArgumentParser(
        description="Entity-resolution pipeline: parsed CSV → deduplicated CSV."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--force", action="store_true",
                       help="Run match + apply with no human review.")
    group.add_argument("--match", action="store_true",
                       help="Run match steps only (produces candidate files).")
    group.add_argument("--apply", action="store_true",
                       help="Run apply step only (writes deduplicated.csv).")
    group.add_argument("--review", nargs="?", const=True, default=None,
                       help="Launch interactive review tool. Optionally specify a match file.")
    group.add_argument("--harvest", action="store_true",
                       help="Harvest candidates-file verdicts into the ledger (e.g. after spreadsheet editing).")
    parser.add_argument("--strict", action="store_true",
                        help="Use strict cross-book matching (require location or postnominal, not just a first name, for non-distinctive titles).")
    parser.add_argument("--input", metavar="FILE",
                        help="Override the parsed CSV input path.")
    parser.add_argument("--output", metavar="FILE",
                        help="Override the deduplicated CSV output path.")
    args = parser.parse_args()

    config = load_config()
    if args.input:
        config["paths"]["parsed"] = args.input
    if args.output:
        config["paths"]["deduplicated"] = args.output

    if args.force:
        do_force(config, strict=args.strict)
    elif args.match:
        do_match(config, strict=args.strict)
    elif args.apply:
        do_apply(config)
    elif args.review is not None:
        match_file = args.review if isinstance(args.review, str) and args.review is not True else None
        do_review(config, match_file)
    elif args.harvest:
        do_harvest(config)


if __name__ == "__main__":
    main()
