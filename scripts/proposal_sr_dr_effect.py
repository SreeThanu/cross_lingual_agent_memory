"""Read-only effect of the D6/D7 SR/DR variants on runs/pilot_v2 (docs/proposals/SR_DR_SCORING.md).

Run from the repo root: PYTHONPATH=. python scripts/proposal_sr_dr_effect.py
Writes nothing to runs/.
"""

import json
import statistics
from pathlib import Path

from xlmem.benchmark.facts import Memory, ProbeResult, load_facts
from xlmem.scoring.duplication import compute_duplication_rate
from xlmem.scoring.staleness import compute_staleness_rate

facts = load_facts("data/facts_v1.yaml")
planted = [f for f in facts if f.distractor_of is None]
root = Path("runs/pilot_v2")


def load_mem(p: Path) -> list[Memory]:
    return [Memory.from_dict(m) for m in json.load(open(p, encoding="utf-8"))] if p.exists() else []


def ms(xs: list[float]) -> str:
    if len(xs) == 1:
        return f"{xs[0]:.2f}"
    return f"{statistics.mean(xs):.2f} ± {statistics.stdev(xs):.2f}"


rows = []
for run in sorted(d for d in root.iterdir() if d.is_dir() and (d / "seed_11").exists()):
    acc = {k: [] for k in ("sr_cur", "sr_new", "dr_cur", "dr_plant", "dr_final_planted")}
    n_corr = set()
    for seed_dir in sorted(run.glob("seed_*")):
        reprobes, corrected_ids = [], []
        for line in open(seed_dir / "run_log.jsonl", encoding="utf-8"):
            r = json.loads(line)
            if r["record_type"] == "reprobe_result":
                reprobes.append(ProbeResult.from_dict(r["data"]))
            elif r["record_type"] == "turn_trace" and r["data"].get("kind") == "correction":
                corrected_ids.append(r["data"]["fact_id"])
        with_update = [f for f in facts if f.update_data is not None]
        corrected = [f for f in facts if f.id in set(corrected_ids)]
        n_corr.add((len(with_update), len(corrected)))
        acc["sr_cur"].append(compute_staleness_rate(with_update, reprobes))
        acc["sr_new"].append(compute_staleness_rate(corrected, reprobes))
        plant_m = load_mem(seed_dir / "store_after_plant.json")
        final_m = load_mem(seed_dir / "store_final.json")
        acc["dr_cur"].append(compute_duplication_rate(facts, final_m or plant_m))
        acc["dr_plant"].append(compute_duplication_rate(planted, plant_m))
        acc["dr_final_planted"].append(compute_duplication_rate(planted, final_m or plant_m))
    rows.append((run.name, n_corr, {k: ms(v) for k, v in acc.items()}, acc))

print(
    "run | (|F_update|,|F_corrected|) | SR cur | SR D6 | DR cur"
    " | DR plant-snapshot | DR final, planted-only"
)
for name, n, s, _ in rows:
    cols = ("sr_cur", "sr_new", "dr_cur", "dr_plant", "dr_final_planted")
    print(name, n, *(s[c] for c in cols), sep=" | ")
print()
for name, _, _, acc in rows:
    print(name, "SR per seed cur", acc["sr_cur"], "D6", acc["sr_new"])
