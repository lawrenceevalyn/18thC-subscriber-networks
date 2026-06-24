"""
================================================================================
              Top-level Pipeline Orchestrator
                              pipeline.py
================================================================================
RUN WITH: python3 pipeline.py all [--strict]
          python3 pipeline.py parse [--input DIR] [--output FILE]
          python3 pipeline.py dedupe [--strict] [--input FILE] [--output FILE]
          python3 pipeline.py graph [--input FILE] [--output FILE]

DESCRIPTION:
    Thin wrapper that chains the three stages of the subscriber-overlap
    pipeline, each of which also runs standalone from its own directory:

        parse    namelist CSVs   → parsed CSV       (name-parsing/)
        dedupe   parsed CSV      → deduplicated CSV  (entity-resolution/)
        graph    deduplicated CSV → chord overlap network + shared-subscriber CSV
                                    (bipartite-graphs/ → bipartite-viz/)

    Each stage reads its input from the previous stage's default output
    location (see each stage's pipeline.toml), so `all` needs no arguments:
    it runs on data/input-lists/ and writes the final outputs under
    bipartite-viz/outputs/.

    All stages run on the same Python interpreter that runs this script, so
    activate your virtualenv first (see README.md) and the dependencies in
    requirements.txt will be picked up throughout.
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


ROOT = Path(__file__).resolve().parent


def abspath(p):
    """Resolve a user-supplied path against the repo root before passing it to
    a stage runner (which runs with cwd=stage_dir, so relative paths break)."""
    if p is None:
        return None
    path = Path(p)
    return str(path.resolve() if path.is_absolute() else (ROOT / p).resolve())


def run_stage(stage_dir, cmd_after_python):
    """Run a command inside a stage directory using this script's interpreter."""
    full_cmd = [sys.executable] + cmd_after_python
    print(f"\n{'=' * 60}")
    print(f"  → {stage_dir.name}: {' '.join(cmd_after_python)}")
    print(f"{'=' * 60}", flush=True)
    result = subprocess.run(full_cmd, cwd=stage_dir)
    if result.returncode != 0:
        print(f"\nERROR: {stage_dir.name} failed with exit code {result.returncode}")
        sys.exit(result.returncode)


# ---------------------------------------------------------------------------
# Subcommand handlers.
# ---------------------------------------------------------------------------

def cmd_parse(args):
    cmd = ["pipeline.py"]
    if args.input:
        cmd += ["--input", abspath(args.input)]
    if args.output:
        cmd += ["--output", abspath(args.output)]
    run_stage(ROOT / "name-parsing", cmd)


def cmd_dedupe(args):
    cmd = ["pipeline.py", "--force"]
    if getattr(args, "strict", False):
        cmd.append("--strict")
    if args.input:
        cmd += ["--input", abspath(args.input)]
    if args.output:
        cmd += ["--output", abspath(args.output)]
    run_stage(ROOT / "entity-resolution", cmd)


def cmd_graph(args):
    cmd = ["pipeline.py"]
    if args.input:
        cmd += ["--input", abspath(args.input)]
    if args.output:
        cmd += ["--output", abspath(args.output)]
    run_stage(ROOT / "bipartite-graphs", cmd)


def cmd_all(args):
    """Chain parse → dedupe → graph on the default data directory."""
    cmd_parse(argparse.Namespace(input=None, output=None))
    cmd_dedupe(argparse.Namespace(strict=args.strict, input=None, output=None))
    cmd_graph(argparse.Namespace(input=None, output=None))
    print("\nDone. Final outputs in bipartite-viz/outputs/:")
    print("  overlap-network.png / .svg   — chord diagram of shared subscribers")
    print("  overlap-namelist.csv         — every subscriber shared across works")


# ---------------------------------------------------------------------------
# Argument parsing.
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="pipeline.py",
        description="Turn subscriber-list CSVs into a cross-book overlap network.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_parse = sub.add_parser("parse", help="Parse namelist CSVs into structured fields.")
    p_parse.add_argument("--input", help="Override input directory.")
    p_parse.add_argument("--output", help="Override parsed CSV output path.")
    p_parse.set_defaults(func=cmd_parse)

    p_dedupe = sub.add_parser("dedupe", help="Deduplicate the parsed CSV (entity resolution).")
    p_dedupe.add_argument("--input", help="Parsed CSV input path.")
    p_dedupe.add_argument("--output", help="Deduplicated CSV output path.")
    p_dedupe.add_argument("--strict", action="store_true",
                          help="Stricter cross-book matching (require a location or "
                               "postnominal, not just a first name, for common titles).")
    p_dedupe.set_defaults(func=cmd_dedupe)

    p_graph = sub.add_parser("graph", help="Build the graph, chord network, and shared-subscriber CSV.")
    p_graph.add_argument("--input", help="Deduplicated CSV input path.")
    p_graph.add_argument("--output", help="GraphML output path.")
    p_graph.set_defaults(func=cmd_graph)

    p_all = sub.add_parser("all", help="Run parse → dedupe → graph end to end.")
    p_all.add_argument("--strict", action="store_true",
                       help="Pass --strict to the dedupe step.")
    p_all.set_defaults(func=cmd_all)

    return parser


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
