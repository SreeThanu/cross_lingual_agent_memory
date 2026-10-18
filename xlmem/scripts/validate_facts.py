"""CLI: validate a fact bank YAML against the BENCHMARK_SPEC.md schema."""

from __future__ import annotations

import argparse
import logging
import sys

from xlmem.benchmark.validate import (
    check_cross_bank_collisions,
    format_report,
    validate_fact_bank,
)

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("validate_facts")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an XLMem fact bank YAML file.")
    parser.add_argument(
        "--facts",
        default="data/facts_v1.yaml",
        help="Path to the fact bank YAML (default: data/facts_v1.yaml).",
    )
    parser.add_argument(
        "--with",
        dest="others",
        nargs="*",
        default=[],
        help="Other fact banks (e.g. candidate batches) to check for collisions with --facts.",
    )
    args = parser.parse_args()

    report = validate_fact_bank(args.facts)
    print(format_report(report))
    ok = report.is_valid

    if args.others:
        collisions = check_cross_bank_collisions([args.facts, *args.others])
        errors = [i for i in collisions if i.severity == "error"]
        print(f"\nCross-bank check over {1 + len(args.others)} files: "
              f"{len(errors)} error(s), {len(collisions) - len(errors)} warning(s)")
        for i in collisions:
            print(f"  {i.severity.upper()} [{i.fact_id}] {i.message}")
        ok = ok and not errors

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
