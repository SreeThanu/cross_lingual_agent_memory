# Pilot v2 rescored under metrics v2 (D6 Staleness Rate, D7 Duplication Rate)

**Date:** 2026-10-27.
**Scope:** the 36 seed dirs of `runs/pilot_v2/` (3 frameworks × 4 directions × seeds 11/22/33; Mem0, Letta and A-MEM on Qwen2.5-7B, `facts_v1`).
**Definitions:** METRICS_SPEC §2.2, §2.4, §3.3, §3.4 and §6.
**Generated tables:** [`pilot_v2_v1_vs_v2_tables.md`](pilot_v2_v1_vs_v2_tables.md). That file is script output; this one is the reading of it.

> **Not reportable.**
> - Each seed corrects exactly one fact (f_001: peanuts → cashews), issued in `store_lang`. So every SR value is 0, 1 or null, and none of them tests a cross-lingual update.
> - The changes below come from changing the scoring definition. They don't show any system doing better or worse.

## 1. What was done
- **Rescored offline.** `PYTHONPATH=. python scripts/rescore_metrics_v2.py` read the saved logs and snapshots. No model was run and no conversation was regenerated.
- **Inputs untouched.** All 144 input files (`run_log.jsonl`, `store_after_plant.json`, `store_final.json`, `scores.json` × 36) have the same sha256 before and after. The script also re-hashes each seed dir after scoring it and aborts on any change.
- **Deterministic.** A dry run into a scratch directory and the real run produced identical tables.

### Where things are

| What | Where | In git? |
|---|---|---|
| Original v1 scores (left in place) | `runs/pilot_v2/<run>/seed_*/scores.json` | no (`runs/` is ignored) |
| Immutable baseline index: the v1 values, sha256 of every input file, the run code SHA (`8e12ba4`; `58dbcac` for mem0_hien) | `docs/rescore/pilot_v2_baseline_v1.json` | yes, once committed |
| v2 scores per seed, including the outcome per fact and the matched spans | `runs/pilot_v2/rescore_metrics-v2/<run>/seed_*/scores.json` | no |
| Per-seed diagnostics (D6 stages, D7 variants, Snapshot A timing checks) | `…/seed_*/diagnostics.json` | no |
| Per-run aggregates (mean ± sample std, `n_seeds`, eligible corrections per seed) | `…/<run>/aggregate.json` | no |
| Provenance: scorer HEAD `7eb3f46` plus the uncommitted files listed, the sha256 of each scorer source file, METRICS_SPEC sha256, alias-file sha256, timestamp | `runs/pilot_v2/rescore_metrics-v2/provenance.json` | no |

The scorer ran from the uncommitted working tree on branch `scoring/d6-d7`, so `provenance.json` pins each source file by sha256 rather than by commit. Once the change is committed, rerunning the script into a new `--out` directory should reproduce the same tables.

**Not rescored:**
- `runs/phase0_pilot_*`: single seed. Three of the four logs have no `reprobe_result`, and the hi→en log was overwritten in September (`docs/STATUS_2026-10-18.md` §2). Superseded by pilot v2.
- `runs/smoke_*`: smoke tests, not experiments.

## 2. Old vs new (mean ± sample std over seeds; per-seed detail in the tables file)

| Run | SR v1 | SR v2 | MR v2 | Eligible / seed | Write-inelig. / seed | DR v1 | DR v2 (plant) |
|---|---|---|---|---|---|---|---|
| amem_enen | 0.00 ± 0 | 0.00 ± 0 | 0.00 ± 0 | 1,1,1 | 0,0,0 | 0.20 ± 0 | 0.00 ± 0 |
| amem_enhi | 0.33 ± 0 | 0.00 ± 0 | **1.00 ± 0** | 1,1,1 | 0,0,0 | 0.20 ± 0 | 0.00 ± 0 |
| amem_hien | 0.00 ± 0 | 0.00 ± 0 | 0.00 ± 0 | 1,1,1 | 0,0,0 | 0.00 ± 0 | 0.00 ± 0 |
| amem_hihi | 0.33 ± 0 | 0.00 ± 0 | 0.33 ± 0.58 | 1,1,1 | 0,0,0 | 0.00 ± 0 | 0.00 ± 0 |
| letta_enen | 0.00 ± 0 | 0.00 ± 0 | 0.00 ± 0 | 1,1,1 | 0,0,0 | 0.00 ± 0 | 0.00 ± 0 |
| letta_enhi | 0.33 ± 0 | 0.00 ± 0 | **1.00 ± 0** | 1,1,1 | 0,0,0 | 0.00 ± 0 | 0.00 ± 0 |
| letta_hien | 0.22 ± 0.19 | null | null | 0,0,0 | 1,1,1 | 0.00 ± 0 | 0.00 ± 0 |
| letta_hihi | 0.33 ± 0 | null | null | 0,0,0 | 1,1,1 | 0.00 ± 0 | 0.00 ± 0 |
| mem0_enen | 0.33 ± 0 | **1.00 ± 0** | 0.00 ± 0 | 1,1,1 | 0,0,0 | 0.10 ± 0 | 0.00 ± 0 |
| mem0_enhi | 0.33 ± 0 | 0.00 ± 0 | **1.00 ± 0** | 1,1,1 | 0,0,0 | 0.10 ± 0 | 0.00 ± 0 |
| mem0_hien | 0.00 ± 0 | null | null | 0,0,0 | 1,1,1 | 0.00 ± 0 | 0.00 ± 0 |
| mem0_hihi | 0.22 ± 0.19 | null | null | 0,0,0 | 1,1,1 | 0.00 ± 0 | 0.00 ± 0 |

**How to read it:**
- **SR v2 = 0.00 with MR = 1.00 (all three en→hi runs) means "no evidence either way".** It does not mean updates worked.
- **`null` means the original f_001 was never written** under the existing WF criterion: Mem0 stored "moong dal", Letta stored Chinese (hand audit, `docs/STATUS_2026-10-18.md`). So whether the update replaced it is undefined. These seeds show up as `write_ineligible_rate = 1.00`, not as a good SR.
- **The one stable STALE result is mem0_enen** (3/3 seeds). After the English correction, Mem0 keeps both "Has a severe allergy to peanuts" and "Allergic to cashews" and answers with both, or with peanuts alone.

## 3. D6: what each change did (DIAGNOSTIC staging)

The stages are cumulative and run in the order the task lists them. The mean over seeds at each stage is in the tables file, and per-seed values are in each `diagnostics.json`.

| Step | Change | Runs whose SR moved | Why |
|---|---|---|---|
| S0 → S1 | Denominator = facts actually corrected (1), not facts with `update` data (3) | Every run that had a v1 "stale" verdict: 0.33 → 1.00, or 0.22 → 0.67 | Pure ×3 rescaling. No verdict changes. |
| S1 → S2 | Write gate | mem0_hien, mem0_hihi, letta_hien, letta_hihi → null | f_001 was not written in any of these 12 seeds. Their v1 values (0.00–0.33) were judging a fact that was never stored. |
| S2 → S3a | v2 tokenizer, still English targets only | none | Each pilot answer gives the same English-only verdict under both matchers. |
| S3a → S3b | Authored Hindi aliases (मूंगफली / काजू) | amem_hihi 1.00 → 0.67 | Seed 33 answers "काजू से एलर्जी" with no मूंगफली. No other Hindi answer uses the authored words. |
| S3b → S4 | Negation and past-tense frames | amem_hihi 0.67 → 0.33 | Seed 11 mentions मूंगफली only in a past frame ("…एलर्जी थे"), and asserts काजू. |
| S4 → S5 | MISS separated from STALE (official v2) | amem_enhi, letta_enhi, mem0_enhi 1.00 → 0.00; amem_hihi 0.33 → 0.00 | All of the remaining "stale" verdicts were answers matching neither value: transliterations, garbled text, or no answer. They now appear as MR. |
| — | mem0_enen | 0.33 → 1.00 at S1, then unchanged | A real STALE verdict under every stage after S1. |

**Which effects can be separated:**
- **The denominator (S1) and the write gate (S2) are cleanly separable.** Each changes the population only, never a verdict.
- **The aliases, the frames and the MISS split are not cleanly separable with this data.** With one fact per seed, each step's effect depends on the order it's applied in. For example, applying the MISS split first would have moved amem_hihi seed 22 before the aliases did anything.
- **The tokenizer change (S3a) is a separate effect that the task's list doesn't name.** The v1 matcher can't use Hindi aliases without false matches (it reduces "काजू" to "क ज"). It changed no pilot verdict.
- **None of these steps is a causal statement about any framework.**

### Check against the earlier hand labels
These are Claude's labels from 2026-10-27 (`docs/proposals/SR_DR_SCORING.md` on `proposal/sr-dr-scoring`), not a bilingual reviewer's.
- **Agreement:** of the 24 write-eligible seeds, 16 agree. No answer flips between STALE and UPDATED.
- **Disagreements:** all 8 are en→hi answers that transliterate the English word into Devanagari, and v2 scores every one of them MISS:
  - mem0_enhi seed 11: U → MISS (कैश्वर)
  - mem0_enhi seeds 22, 33: **S → MISS** (कैश्वर … पैनट्स)
  - letta_enhi seeds 11–33: U → MISS (काश्वे, चाशून, कешू)
  - amem_enhi seeds 22, 33: U → MISS (कशुअर, कashews)
- **So on Hindi probes, v2 under-counts both STALE and UPDATED.** It is conservative by design (§3.3 item 7). That's why MR has to be reported next to SR.
- **This is not an independent validation.** The labeller also wrote the rules, and the rules were written after reading these answers (METRICS_SPEC §3.3, disclosure).

## 4. D7: final store → Snapshot A

**Snapshot A precedes every distractor and correction turn.** Three independent checks:
- **The runner code:** `xlmem/runner/experiment.py` runs plant, then `consolidate()`, then the Snapshot A write, and only then the filler, distractor, correction and re-probe phases.
- **Every seed's log:** every plant turn is in session 1, and every filler, distractor and correction turn is in session ≥ 2.
- **File evidence:** in every seed, `store_after_plant.json` is older than `store_final.json`, and no filler or correction turn's text appears verbatim in Snapshot A. That last check is meaningful for A-MEM, which stores turns verbatim.

**What changed:**

| Run | v1 (final store, all 20 facts) | Final store, planted base facts only (DIAGNOSTIC) | v2 plant DR |
|---|---|---|---|
| amem_enen, amem_enhi | 0.20 | 0.12 | 0.00 |
| mem0_enen, mem0_enhi | 0.10 | 0.06 | 0.00 |
| all other runs | 0.00 | 0.00 | 0.00 |

- **Dropping the distractors from the population removes part of v1.** The distractor f_001_dist "found" its base fact's records.
- **Moving to Snapshot A removes the rest.** That rest was the distractor record ("My sister has an allergy to peanuts") and the correction record matching f_001.
- **No Snapshot A in the pilot has any fact matched by more than one record.**
- **v2 DR = 0 does not show that consolidation is perfect.** The session structure never restates a fact (D8, open), and on Hindi stores the matcher under-detects (D1, open).

## 5. Limitations and follow-up
- **One correction per seed, in `store_lang`.** SR needs the scaled fact bank (≥ 30% updates; D6b, open) and a cross-language correction arm (RQ3) before any number can be reported.
- **Hindi.** The matcher ignores transliterations and `hi-en` has no aliases, so MR on Hindi probes is high by construction. Possible follow-ups: authored transliteration aliases (that would be a D1 decision), or the NLI tier as a separately versioned metric. Both need bilingual review.
- **Matchers disagree until D1 lands.** The SR matcher (§3.3) differs from the WF, recall, DR and FMR matcher (§3.1).
- **The write gate uses the existing WF criterion, which D1 disputes.** For f_001 in this pilot, the gate agrees with the hand WF audit in all 36 seeds.
- **`score.py` overwrites `scores.json` in place** when pointed at a run directory. Use the rescore script for historical runs. Making `score.py` refuse to overwrite is a small follow-up, not done here.
- **The alias file and the negation patterns need bilingual review** before any reported run.
