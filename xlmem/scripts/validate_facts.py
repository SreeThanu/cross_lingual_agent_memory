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
    parser.add_argument(
        "--alias-bank",
        default=None,
        help="Also check a v3 alias bank against the matching contract (METRICS_SPEC §3.5.4).",
    )
    args = parser.parse_args()

    report = validate_fact_bank(args.facts)
    print(format_report(report))
    ok = report.is_valid

    if args.alias_bank:
        from xlmem.benchmark.facts import load_facts
        from xlmem.benchmark.generator import DEFAULT_FILLER_TURNS
        from xlmem.scoring.alias_bank import load_alias_bank_v2, validate_contract_bank

        facts = load_facts(args.facts)
        errors = validate_contract_bank(
            facts, load_alias_bank_v2(args.alias_bank, facts, args.facts), DEFAULT_FILLER_TURNS
        )
        for err in errors:
            print(f"[contract] {err}")
        print(f"Matching-contract checks: {'PASS' if not errors else f'{len(errors)} error(s)'}")
        ok = ok and not errors

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
