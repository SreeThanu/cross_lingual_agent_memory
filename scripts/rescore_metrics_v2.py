#!/usr/bin/env python3
"""Rescore the pilot v2 runs under metrics v2 (D6, D7) without touching the original outputs.

Reads runs/pilot_v2/<run>/seed_*/ read-only. Writes (refusing to overwrite):
  --baseline  immutable index of the original v1 scores + input checksums (docs/rescore/)
  --out       v2 scores per seed, per-run aggregates, diagnostics, provenance (runs/...)
  --report    old-vs-new comparison tables (docs/rescore/)

Staged D6 diagnostics are labelled DIAGNOSTIC: they are not metric versions.
Run from the repo root: PYTHONPATH=. python scripts/rescore_metrics_v2.py
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
from xlmem.benchmark.facts import Fact, Memory, ProbeResult, load_facts
from xlmem.scoring.aliases import ValueAliases, load_value_aliases, sha256_file
from xlmem.scoring.duplication import compute_duplication_rate
from xlmem.scoring.retrieval import compute_write_fidelity
from xlmem.scoring.staleness import (
    AFFIRMED,
    AMBIGUOUS,
    ASSERTED,
    InvalidReprobe,
    compute_staleness_rate,
    find_mentions,
    parse_reprobe_record,
    sr_targets,
)
from xlmem.scripts.score import METRICS_VERSION, compute_seed_scores

SCORER_FILES = (
    "xlmem/scoring/staleness.py",
    "xlmem/scoring/duplication.py",
    "xlmem/scoring/aliases.py",
    "xlmem/scoring/retrieval.py",
    "xlmem/scoring/judge.py",
    "xlmem/scripts/score.py",
    "scripts/rescore_metrics_v2.py",
)
SEED_FILES = ("run_log.jsonl", "store_after_plant.json", "store_final.json", "scores.json")
D6_STAGES = ("S0", "S1", "S2", "S3a", "S3b", "S4", "S5")


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout
    return out.rstrip("\n")  # keep leading spaces: `git status --porcelain` columns


def _load_log(seed_dir: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"metadata": None, "turns": [], "reprobes": [], "invalid_reprobes": []}
    for line in (seed_dir / "run_log.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec["record_type"] == "metadata":
            out["metadata"] = rec
        elif rec["record_type"] == "turn_trace":
            out["turns"].append(rec["data"])
        elif rec["record_type"] == "reprobe_result":
            # Same validation as the official scorer (v2.1); diagnostics use valid records only.
            parsed = parse_reprobe_record(rec.get("data"))
            key = "invalid_reprobes" if isinstance(parsed, InvalidReprobe) else "reprobes"
            out[key].append(parsed)
    return out


def _memories(path: Path) -> list[Memory] | None:
    if not path.exists():
        return None
    return [Memory.from_dict(m) for m in json.loads(path.read_text(encoding="utf-8"))]


def _binary_stale(
    fact: Fact, probe: ProbeResult, aliases: ValueAliases | None, use_aliases: bool, frames: bool
) -> bool | None:
    """DIAGNOSTIC binary staleness (stale vs not) with the v2 tokenizer; None if not scorable."""
    if use_aliases:
        targets = sr_targets(fact, probe.probe_lang, aliases)
        if targets is None:
            return None
        old, new = targets
    else:
        old = [fact.value]
        new = [str((fact.update_data or {}).get("updated_value", ""))]
    old_m, new_m = find_mentions(probe.response, old), find_mentions(probe.response, new)
    if not frames:
        return bool(old_m) or not new_m
    if any(m.frame in (ASSERTED, AFFIRMED, AMBIGUOUS) for m in old_m):
        return True
    return not any(m.frame in (ASSERTED, AFFIRMED) for m in new_m)


def d6_stages(
    facts: list[Fact],
    log: dict[str, Any],
    written: set[str],
    aliases: ValueAliases | None,
    v1_sr: float | None,
    v2: dict[str, Any],
) -> dict[str, Any]:
    """Per-seed SR under each cumulative change, in the order the D6 task lists them."""
    by_id = {f.id: f for f in facts}
    corrected_ids = list(
        dict.fromkeys(t["fact_id"] for t in log["turns"] if t.get("kind") == "correction")
    )
    corrected = [by_id[i] for i in corrected_ids if i in by_id]
    rp = {r.fact_id: r for r in log["reprobes"]}
    gated = [f for f in corrected if f.id in written]

    def binary(use_aliases: bool, frames: bool) -> dict[str, Any]:
        verdicts = [
            _binary_stale(f, rp[f.id], aliases, use_aliases, frames) for f in gated if f.id in rp
        ]
        if not gated or len(verdicts) != len(gated) or any(v is None for v in verdicts):
            return {"sr": None, "n": len(gated)}
        return {"sr": sum(bool(v) for v in verdicts) / len(gated), "n": len(gated)}

    return {
        "S0": {"sr": v1_sr, "n": None, "label": "v1 as originally stored"},
        "S1": {
            "sr": compute_staleness_rate(corrected, log["reprobes"]) if corrected else None,
            "n": len(corrected),
            "label": "+ denominator = corrected facts (v1 rule)",
        },
        "S2": {
            "sr": compute_staleness_rate(gated, log["reprobes"]) if gated else None,
            "n": len(gated),
            "label": "+ write gate (v1 rule)",
        },
        "S3a": {**binary(False, False), "label": "+ v2 tokenizer, English targets only, binary"},
        "S3b": {**binary(True, False), "label": "+ authored Hindi aliases, binary"},
        "S4": {**binary(True, True), "label": "+ negation/ambiguity frames, binary"},
        "S5": {
            "sr": v2["staleness_rate"],
            "mr": v2["miss_rate"],
            "n": v2["eligible_corrections"],
            "label": f"+ MISS separated from STALE = official v{METRICS_VERSION}",
        },
    }


def snapshot_timing(
    log: dict[str, Any], seed_dir: Path, plant: list[Memory] | None
) -> dict[str, Any]:
    """Evidence that Snapshot A precedes distractor and correction turns (D7)."""
    sessions: dict[str, list[int]] = {}
    for t in log["turns"]:
        sessions.setdefault(t["kind"], []).append(int(t["session_id"]))
    later = [t for t in log["turns"] if t["kind"] in ("filler", "correction")]
    plant_texts = {m.text.strip() for m in plant or []}
    leaked = sorted({t["fact_id"] or "-" for t in later if t["text"].strip() in plant_texts})
    a, b = seed_dir / "store_after_plant.json", seed_dir / "store_final.json"
    max_plant = max(sessions.get("plant", [0]))
    min_later = min(sessions.get("filler", []) + sessions.get("correction", []) or [10**9])
    return {
        "plant_sessions_before_filler_and_correction": max_plant < min_later,
        "later_turn_texts_found_verbatim_in_snapshot_a": leaked,
        "snapshot_a_mtime_before_snapshot_b": a.exists()
        and b.exists()
        and a.stat().st_mtime <= b.stat().st_mtime,
    }


def _mean_std(values: list[float | None]) -> str:
    v = [x for x in values if x is not None]
    if not v:
        return "null"
    if len(v) == 1:
        return f"{v[0]:.2f} (n=1)"
    return f"{statistics.mean(v):.2f} ± {statistics.stdev(v):.2f}"


def _fmt(x: float | None) -> str:
    return "null" if x is None else f"{x:.2f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", default="runs/pilot_v2")
    ap.add_argument("--facts", default="data/facts_v1.yaml")
    ap.add_argument("--aliases", default="data/aliases/facts_v1.aliases.yaml")
    ap.add_argument("--out", default="runs/pilot_v2/rescore_metrics-v2")
    ap.add_argument("--baseline", default="docs/rescore/pilot_v2_baseline_v1.json")
    ap.add_argument("--report", default="docs/rescore/pilot_v2_v1_vs_v2_tables.md")
    args = ap.parse_args()

    runs_root, out = Path(args.runs), Path(args.out)
    for p in (out, Path(args.baseline), Path(args.report)):
        if p.exists():
            print(f"Refusing to overwrite existing {p}", file=sys.stderr)
            return 1

    facts = load_facts(args.facts)
    aliases = load_value_aliases(args.aliases, facts, args.facts)
    manifest_dir = runs_root / "manifest"
    pilot_sha = (manifest_dir / "git_sha.txt").read_text().strip()
    rerun_sha_file = manifest_dir / "mem0_hien_rerun_git_sha.txt"
    rerun_sha = rerun_sha_file.read_text().strip() if rerun_sha_file.exists() else None

    run_dirs = sorted(d for d in runs_root.iterdir() if d.is_dir() and any(d.glob("seed_*")))
    run_dirs = [d for d in run_dirs if d.resolve() != out.resolve()]

    baseline: dict[str, Any] = {
        "description": "Original metrics-v1 scores of runs/pilot_v2, indexed before rescoring. "
        "The files themselves are left in place and unmodified.",
        "indexed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "metrics_version": "1",
        "fact_bank": {"path": args.facts, "sha256": sha256_file(args.facts)},
        "runs": {},
    }
    results: dict[str, Any] = {}
    unscorable: dict[str, str] = {}

    for run in run_dirs:
        code_sha = rerun_sha if run.name == "mem0_hien" and rerun_sha else pilot_sha
        baseline["runs"][run.name] = {"run_code_git_sha": code_sha, "seeds": {}}
        results[run.name] = {}
        for seed_dir in sorted(run.glob("seed_*")):
            key = f"{run.name}/{seed_dir.name}"
            files = {n: seed_dir / n for n in SEED_FILES}
            checksums = {n: sha256_file(p) for n, p in files.items() if p.exists()}
            v1 = (
                json.loads(files["scores.json"].read_text())
                if files["scores.json"].exists()
                else None
            )
            baseline["runs"][run.name]["seeds"][seed_dir.name] = {
                "path": str(seed_dir),
                "sha256": checksums,
                "missing_files": [n for n, p in files.items() if not p.exists()],
                "scores_v1": v1,
            }
            if not files["run_log.jsonl"].exists():
                unscorable[key] = "run_log.jsonl missing"
                continue

            v2 = compute_seed_scores(seed_dir, facts=facts, aliases=aliases)
            log = _load_log(seed_dir)
            plant = _memories(files["store_after_plant.json"])
            final = _memories(files["store_final.json"])
            _, written_ids = compute_write_fidelity(
                planted_facts=facts, dumped_memories=plant or []
            )
            planted_ids = {t["fact_id"] for t in log["turns"] if t["kind"] == "plant"}
            planted_base = [f for f in facts if f.id in planted_ids and f.distractor_of is None]
            sr_report = {
                k: v2[k]
                for k in (
                    "staleness_rate",
                    "miss_rate",
                    "write_ineligible_rate",
                    "eligible_corrections",
                    "updated_count",
                    "stale_count",
                    "miss_count",
                    "write_ineligible_count",
                    "missing_or_invalid_reprobe_count",
                )
            }
            results[run.name][seed_dir.name] = {
                "scores_v2": v2,
                "checks_after_scoring_sha256": {
                    n: sha256_file(p) for n, p in files.items() if p.exists()
                },
                "d6_stages_DIAGNOSTIC": d6_stages(
                    facts,
                    log,
                    set(written_ids),
                    aliases,
                    (v1 or {}).get("staleness_rate"),
                    sr_report,
                ),
                "d7_DIAGNOSTIC": {
                    "v1_final_store_all_facts": (v1 or {}).get("duplication_rate"),
                    "final_store_planted_only": compute_duplication_rate(planted_base, final)
                    if final is not None
                    else None,
                    "v2_plant_duplication_rate": v2["plant_duplication_rate"],
                },
                "snapshot_a_timing": snapshot_timing(log, seed_dir, plant),
                "probe_lang": (log["metadata"] or {}).get("probe_lang"),
            }
            if results[run.name][seed_dir.name]["checks_after_scoring_sha256"] != checksums:
                print(f"INPUT CHANGED DURING SCORING: {key}", file=sys.stderr)
                return 2

    # Write outputs (all create-only).
    Path(args.baseline).parent.mkdir(parents=True, exist_ok=True)
    with open(args.baseline, "x", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2, ensure_ascii=False)

    out.mkdir(parents=True)
    head = _git("rev-parse", "HEAD")
    dirty = _git("status", "--porcelain", "--", *SCORER_FILES, "data/aliases")
    provenance = {
        "scored_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "metrics_version": METRICS_VERSION,
        "metric_spec": "METRICS_SPEC.md §2.2, §2.4, §3.3, §3.4, §6 (v2)",
        "spec_sha256": sha256_file("METRICS_SPEC.md"),
        "scorer_git_head": head,
        "scorer_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "scorer_uncommitted_changes": dirty.splitlines(),
        "scorer_source_sha256": {p: sha256_file(p) for p in SCORER_FILES},
        "fact_bank": {"path": args.facts, "sha256": sha256_file(args.facts)},
        "aliases": {"path": aliases.path, "sha256": aliases.sha256},
        "inputs_root": str(runs_root),
        "baseline_index": args.baseline,
        "unscorable": unscorable,
    }
    (out / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")

    for run_name, seeds in results.items():
        run_out = out / run_name
        for seed_name, rec in seeds.items():
            (run_out / seed_name).mkdir(parents=True)
            with open(run_out / seed_name / "scores.json", "x", encoding="utf-8") as f:
                json.dump(rec["scores_v2"], f, indent=2, ensure_ascii=False)
            with open(run_out / seed_name / "diagnostics.json", "x", encoding="utf-8") as f:
                diag = {k: v for k, v in rec.items() if k != "scores_v2"}
                json.dump(diag, f, indent=2, ensure_ascii=False)
        agg = aggregate_seed_metrics([r["scores_v2"] for r in seeds.values()])
        agg["eligible_corrections_per_seed"] = {
            s: r["scores_v2"]["eligible_corrections"] for s, r in seeds.items()
        }
        with open(run_out / "aggregate.json", "x", encoding="utf-8") as f:
            json.dump(agg, f, indent=2)

    _write_report(Path(args.report), results, baseline, provenance)
    print(f"Rescored {sum(len(s) for s in results.values())} seed dirs -> {out}")
    print(f"Baseline index -> {args.baseline}; report -> {args.report}")
    return 0


def _write_report(
    path: Path, results: dict[str, Any], baseline: dict[str, Any], prov: dict[str, Any]
) -> None:
    L: list[str] = []
    L.append("# Pilot v2: metrics v1 vs v2 (generated tables)\n")
    L.append(
        f"Generated by `scripts/rescore_metrics_v2.py` at {prov['scored_at']} "
        f"(scorer HEAD `{prov['scorer_git_head'][:7]}` + uncommitted changes, "
        f"metrics v{prov['metrics_version']}). Per-seed values; mean ± sample std over seeds "
        "with a non-null value. **v1 and v2 numbers are different metrics; the deltas show "
        "the effect of the definition change, not a change in any system.**\n"
    )
    L.append("## Per run (mean ± std over seeds)\n")
    L.append(
        "| Run | SR v1 | SR v2 | ΔSR (means) | MR v2 | eligible / seed | write-inelig. / seed "
        "| DR v1 | DR v2 (plant) | ΔDR (means) |"
    )
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for run, seeds in results.items():
        v1s = [baseline["runs"][run]["seeds"][s]["scores_v1"] or {} for s in seeds]
        v2s = [r["scores_v2"] for r in seeds.values()]
        sr1 = [x.get("staleness_rate") for x in v1s]
        sr2 = [x["staleness_rate"] for x in v2s]
        dr1 = [x.get("duplication_rate") for x in v1s]
        dr2 = [x["plant_duplication_rate"] for x in v2s]

        def delta(a: list[float | None], b: list[float | None]) -> str:
            av, bv = [x for x in a if x is not None], [x for x in b if x is not None]
            return f"{statistics.mean(bv) - statistics.mean(av):+.2f}" if av and bv else "n/a"

        L.append(
            f"| {run} | {_mean_std(sr1)} | {_mean_std(sr2)} | {delta(sr1, sr2)} "
            f"| {_mean_std([x['miss_rate'] for x in v2s])} "
            f"| {', '.join(str(x['eligible_corrections']) for x in v2s)} "
            f"| {', '.join(str(x['write_ineligible_count']) for x in v2s)} "
            f"| {_mean_std(dr1)} | {_mean_std(dr2)} | {delta(dr1, dr2)} |"
        )

    L.append("\n## Per seed: SR outcome and counts\n")
    L.append(
        "| Run/seed | probe | v1 SR | v2 outcome(s) | U | S | M | write-inelig. | invalid "
        "| v2 SR | v2 MR | v2 invalid reason |"
    )
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for run, seeds in results.items():
        for s, r in seeds.items():
            v2 = r["scores_v2"]
            v1 = baseline["runs"][run]["seeds"][s]["scores_v1"] or {}
            outs = ",".join(
                f"{p['fact_id']}:{p['status']}" for p in v2["staleness_detail"]["per_fact"]
            )
            reason = (v2.get("invalid_metrics") or {}).get("staleness_rate", "")
            L.append(
                f"| {run}/{s} | {r['probe_lang']} | {_fmt(v1.get('staleness_rate'))} | {outs} "
                f"| {v2['updated_count']} | {v2['stale_count']} | {v2['miss_count']} "
                f"| {v2['write_ineligible_count']} | {v2['missing_or_invalid_reprobe_count']} "
                f"| {_fmt(v2['staleness_rate'])} | {_fmt(v2['miss_rate'])} | {reason} |"
            )

    L.append("\n## D6 staged diagnostics (DIAGNOSTIC, not metric versions)\n")
    L.append(
        "Cumulative, in the order the D6 task lists the changes. Mean over seeds (null seeds "
        "excluded; `null` = no seed scorable at that stage). With one corrected fact per seed, "
        "the step at which an effect appears depends on this order; see the report text.\n"
    )
    L.append("| Run | " + " | ".join(D6_STAGES) + " |")
    L.append("|---|" + "---|" * len(D6_STAGES))
    labels: dict[str, str] = {}
    for run, seeds in results.items():
        cells = []
        for st in D6_STAGES:
            vals = [r["d6_stages_DIAGNOSTIC"][st]["sr"] for r in seeds.values()]
            labels[st] = next(iter(seeds.values()))["d6_stages_DIAGNOSTIC"][st]["label"]
            v = [x for x in vals if x is not None]
            cells.append(f"{statistics.mean(v):.2f}" if v else "null")
        L.append(f"| {run} | " + " | ".join(cells) + " |")
    L.append("")
    for st in D6_STAGES:
        L.append(f"- **{st}**: {labels[st]}")

    L.append("\n## D7 diagnostics\n")
    L.append(
        "| Run | v1 (final store, all facts) | final store, planted base only (DIAGNOSTIC) "
        "| v2 plant DR | Snapshot A precedes later turns (all seeds) "
        "| later turn text in Snapshot A |"
    )
    L.append("|---|---|---|---|---|---|")
    for run, seeds in results.items():
        d = [r["d7_DIAGNOSTIC"] for r in seeds.values()]
        t = [r["snapshot_a_timing"] for r in seeds.values()]
        ok = all(
            x["plant_sessions_before_filler_and_correction"]
            and x["snapshot_a_mtime_before_snapshot_b"]
            for x in t
        )
        leaked = sorted(
            {fid for x in t for fid in x["later_turn_texts_found_verbatim_in_snapshot_a"]}
        )
        L.append(
            f"| {run} | {_mean_std([x['v1_final_store_all_facts'] for x in d])} "
            f"| {_mean_std([x['final_store_planted_only'] for x in d])} "
            f"| {_mean_std([x['v2_plant_duplication_rate'] for x in d])} | {ok} "
            f"| {', '.join(leaked) or 'none'} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
