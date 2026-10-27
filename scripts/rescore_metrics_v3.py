#!/usr/bin/env python3
"""Rescore runs under metrics v3 (matching contract MC-1) into new, create-only paths.

Reads <runs>/<run>/seed_*/ read-only. Writes (refusing to overwrite anything):
  --out       v3 scores per seed, per-run aggregates, provenance
  --baseline  index of the inputs (sha256) and of the v1 / v2.1 scores being compared
  --report    v2.1 vs v3 comparison tables

Run from the repo root: PYTHONPATH=. python scripts/rescore_metrics_v3.py --out ... \
  --baseline ... --report ...
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

from xlmem.analysis.aggregate import aggregate_seed_metrics
from xlmem.benchmark.facts import load_facts
from xlmem.benchmark.generator import DEFAULT_FILLER_TURNS
from xlmem.scoring.alias_bank import load_alias_bank_v2, sha256_file, validate_contract_bank
from xlmem.scoring.matching import TOKENIZER_VERSION
from xlmem.scripts.score import METRICS_VERSION_V3, compute_seed_scores_v3

SCORER_FILES = (
    "xlmem/scoring/matching.py",
    "xlmem/scoring/support.py",
    "xlmem/scoring/metrics_v3.py",
    "xlmem/scoring/alias_bank.py",
    "xlmem/scoring/staleness.py",
    "xlmem/scripts/score.py",
    "scripts/rescore_metrics_v3.py",
)
SEED_FILES = ("run_log.jsonl", "store_after_plant.json", "store_final.json", "scores.json")
COMPARE = (
    "write_fidelity",
    "recall_at_1_strict",
    "staleness_rate",
    "miss_rate",
    "plant_duplication_rate",
    "false_merge_rate",
)


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout
    return out.rstrip("\n")


def _mean_std(values: list[Any]) -> str:
    v = [x for x in values if isinstance(x, (int, float)) and not isinstance(x, bool)]
    if not v:
        return "null"
    if len(v) == 1:
        return f"{v[0]:.2f} (n=1)"
    return f"{statistics.mean(v):.2f} ± {statistics.stdev(v):.2f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", default="runs/pilot_v2")
    ap.add_argument("--facts", default="data/facts_v1.yaml")
    ap.add_argument("--alias-bank", default="data/aliases/facts_v1.aliases.v2.yaml")
    ap.add_argument("--compare-v21", default="runs/pilot_v2/rescore_metrics-v2.1")
    ap.add_argument("--out", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    out, runs_root, v21 = Path(args.out), Path(args.runs), Path(args.compare_v21)
    for p in (out, Path(args.baseline), Path(args.report)):
        if p.exists():
            print(f"Refusing to overwrite existing {p}", file=sys.stderr)
            return 1

    facts = load_facts(args.facts)
    bank = load_alias_bank_v2(args.alias_bank, facts, args.facts)
    errors = validate_contract_bank(facts, bank, DEFAULT_FILLER_TURNS)
    if errors:
        print("Alias bank fails the contract checks:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 3

    run_dirs = sorted(
        d
        for d in runs_root.iterdir()
        if d.is_dir() and not d.name.startswith("rescore_") and any(d.glob("seed_*"))
    )
    baseline: dict[str, Any] = {
        "indexed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "inputs_root": str(runs_root),
        "compared_v21_root": str(v21),
        "runs": {},
    }
    results: dict[str, dict[str, Any]] = {}
    for run in run_dirs:
        baseline["runs"][run.name] = {}
        results[run.name] = {}
        for seed_dir in sorted(run.glob("seed_*")):
            files = {n: seed_dir / n for n in SEED_FILES}
            before = {n: sha256_file(p) for n, p in files.items() if p.exists()}
            v21_scores = v21 / run.name / seed_dir.name / "scores.json"
            baseline["runs"][run.name][seed_dir.name] = {
                "sha256": before,
                "v21_scores": str(v21_scores) if v21_scores.exists() else None,
                "v21_scores_sha256": sha256_file(v21_scores) if v21_scores.exists() else None,
            }
            scores = compute_seed_scores_v3(seed_dir, facts, bank)
            if {n: sha256_file(p) for n, p in files.items() if p.exists()} != before:
                print(f"INPUT CHANGED DURING SCORING: {seed_dir}", file=sys.stderr)
                return 2
            prior = json.loads(v21_scores.read_text()) if v21_scores.exists() else {}
            results[run.name][seed_dir.name] = {"v3": scores, "v21": prior}

    Path(args.baseline).parent.mkdir(parents=True, exist_ok=True)
    with open(args.baseline, "x", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2)
    out.mkdir(parents=True)
    provenance = {
        "scored_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "metrics_version": METRICS_VERSION_V3,
        "tokenizer_version": TOKENIZER_VERSION,
        "metric_spec_sha256": sha256_file("METRICS_SPEC.md"),
        "contract": "docs/proposals/D1_MATCHING_CONTRACT.md (revision 3)",
        "scorer_git_head": _git("rev-parse", "HEAD"),
        "scorer_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "scorer_uncommitted_changes": _git(
            "status", "--porcelain", "--", *SCORER_FILES, "data/aliases"
        ).splitlines(),
        "scorer_source_sha256": {p: sha256_file(p) for p in SCORER_FILES},
        "fact_bank": {"path": args.facts, "sha256": sha256_file(args.facts)},
        "alias_bank": {"path": bank.path, "sha256": bank.sha256, "tiers_used": ["A", "B"]},
        "baseline_index": args.baseline,
    }
    (out / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    for run_name, seeds in results.items():
        for seed_name, rec in seeds.items():
            (out / run_name / seed_name).mkdir(parents=True)
            with open(out / run_name / seed_name / "scores.json", "x", encoding="utf-8") as f:
                json.dump(rec["v3"], f, indent=2, ensure_ascii=False)
        agg = aggregate_seed_metrics([r["v3"] for r in seeds.values()])
        with open(out / run_name / "aggregate.json", "x", encoding="utf-8") as f:
            json.dump(agg, f, indent=2)

    lines = [
        "# Pilot v2: metrics v2.1 vs v3 (generated tables)\n",
        f"Generated by `scripts/rescore_metrics_v3.py` at {provenance['scored_at']} (scorer HEAD "
        f"`{provenance['scorer_git_head'][:7]}` + uncommitted changes). Mean ± sample std over "
        "seeds with a value. **v2.1 and v3 are different metric definitions; differences are "
        "definitional, not changes in any system.**\n",
        "| Run | " + " | ".join(f"{m} v2.1 → v3" for m in COMPARE) + " | seeds flagged (v3) |",
        "|---|" + "---|" * (len(COMPARE) + 1),
    ]
    for run_name, seeds in results.items():
        cells = []
        for m in COMPARE:
            a = _mean_std([r["v21"].get(m) for r in seeds.values()])
            b = _mean_std([r["v3"].get(m) for r in seeds.values()])
            cells.append(f"{a} → {b}")
        flagged = sum(
            bool(r["v3"]["validation"]["insufficient_validation"]) for r in seeds.values()
        )
        lines.append(f"| {run_name} | " + " | ".join(cells) + f" | {flagged}/{len(seeds)} |")
    with open(args.report, "x", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Rescored {sum(len(s) for s in results.values())} seed dirs -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
