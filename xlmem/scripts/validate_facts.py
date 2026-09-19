"""CLI: validate a fact bank YAML against the BENCHMARK_SPEC.md schema."""

from __future__ import annotations

import argparse
import logging
import sys

from xlmem.benchmark.validate import format_report, validate_fact_bank

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("validate_facts")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an XLMem fact bank YAML file.")
    parser.add_argument(
        "--facts",
        default="data/facts_v1.yaml",
        help="Path to the fact bank YAML (default: data/facts_v1.yaml).",
    )
    args = parser.parse_args()

    report = validate_fact_bank(args.facts)
    print(format_report(report))

    return 0 if report.is_valid else 1


if __name__ == "__main__":
    sys.exit(main())
