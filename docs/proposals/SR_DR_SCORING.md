# Proposal: Staleness Rate and Duplication Rate scoring (D6, D7, new D8)

**Status:** PROPOSAL, not merged. Branch `proposal/sr-dr-scoring`. **Needs a decision from student + guide (D6, D7 in `docs/STATUS_2026-10-18.md`; D8 is new).**
**Affects measurement semantics:** yes. Every option below changes SR and/or DR for every run. If adopted: update METRICS_SPEC.md §2.2/§2.4 and ARCHITECTURE.md §8, then re-score all runs (no GPU re-run needed: everything below is computed from existing logs).
**Depends on D1** (`proposal/hindi-matching`): SR and DR both call `strict_match`, so on Hindi text they inherit the matcher bias until D1 lands.

All numbers are from the 36 pilot v2 logs (`runs/pilot_v2/`, 3 frameworks × 4 directions × seeds 11/22/33). They were computed read-only by `scripts/proposal_sr_dr_effect.py`. The pilot corrects **one** fact per run (f_001: peanuts → cashews), so every number here is illustrative only and not reportable.

---

## D6. Staleness Rate (SR)

### Problem
Five defects. The first is the D6 already on record; the other four came out of reading the 36 re-probe answers.

| # | Defect | Where | Effect |
|---|---|---|---|
| A | Denominator = every fact with `update` data (3), not the facts actually corrected in the run (1, from `turn_trace` records with `kind: "correction"`) | `scripts/score.py` | SR per seed can only be 0 or 0.33; a fully stale run scores 0.33. METRICS_SPEC §2.4 already says the denominator is *corrected* facts, so the code disagrees with the spec. |
| B | **Every miss is counted as stale.** The check is `has_old or (not has_new and not probe.hit_strict)`, and the runner always writes `hit_strict=False` (correctly: the runner never judges). So any answer that doesn't contain the updated value counts as stale. | `scoring/staleness.py:42` | A wrong answer ("you are allergic to carrots") counts as an update failure. That mixes write/retrieval failures into UPDATE, the same conflation AGENTS.md rule 11 forbids for recall. |
| C | Hindi answers are matched against the English `value` / `updated_value` only (no aliases) | `scoring/staleness.py` | A correct Hindi answer ("काजू से एलर्जी है") has no "cashews" in it, so by B it counts as **stale**. Note: HINDI_MATCHING.md §5 Q4 expects Hindi to *under*-count staleness. Because of B it's the opposite, it **over**-counts. |
| D | Mentioning the old value in a negated or past frame counts as stale ("cashews, **not** moong dal", "your earlier memory said peanuts, but…") | `strict_match` has no negation handling | Correct, well-hedged updates are scored stale. |
| E | A corrected fact with no `reprobe_result` is skipped (`continue`) but stays in the denominator, so it silently counts as "not stale" | `scoring/staleness.py:31` | Missing data reads as success. `score.py` already catches the run-level case (no re-probes at all); the per-fact case is still open. |

### Hand audit of the 36 re-probe answers
Labels: **U** = asserts the updated value only; **S** = asserts the old value (alone or next to the new one = "conflicted", which the spec counts as stale); **W** = neither (wrong, garbled, or no answer). An old value mentioned only as negated/past counts as U. Classified by hand by Claude, **not** by a bilingual reviewer, so it needs a second check (several Hindi answers are garbled transliterations: कशुअर, काश्वे, चाशून, कешू).

| | en→en | en→hi | hi→en | hi→hi |
|---|---|---|---|---|
| **Mem0** | S S S | U S S | U U U | U U U |
| **Letta** | U U U | U U U | S W S † | W W W |
| **A-MEM** | U U U | W U U | U U U | U W U |

† Letta hi→en: seed 22 answers "绿豆" (mung bean), which is how Letta *wrote* the original peanut fact (see the WF hand audit). Seed 33 gives "绿豆 and 腰果 (cashews)". Whether returning a corrupted copy of the old value counts as stale is exactly what option 2 below settles.

| Run | SR now (3 seeds) | SR with A only | SR, hand audit (S / corrected) | W (misses) |
|---|---|---|---|---|
| mem0_enen | 0.33 ± 0 | 1.00 ± 0 | **1.00** | 0 |
| mem0_enhi | 0.33 ± 0 | 1.00 ± 0 | **0.67** | 0 |
| mem0_hien | 0 | 0 | 0 | 0 |
| mem0_hihi | 0.22 ± 0.19 | 0.67 ± 0.58 | **0** | 0 |
| letta_enen | 0 | 0 | 0 | 0 |
| letta_enhi | 0.33 ± 0 | 1.00 ± 0 | **0** | 0 |
| letta_hien | 0.22 ± 0.19 | 0.67 ± 0.58 | 0.67 | 1 |
| letta_hihi | 0.33 ± 0 | 1.00 ± 0 | **0** | 3 |
| amem_enen | 0 | 0 | 0 | 0 |
| amem_enhi | 0.33 ± 0 | 1.00 ± 0 | **0** | 1 |
| amem_hien | 0 | 0 | 0 | 0 |
| amem_hihi | 0.33 ± 0 | 1.00 ± 0 | **0** | 1 |

**Fixing the denominator (A) alone makes things worse:** it scales the artifacts from B/C up to 1.00. Fixing A without B and C would report that A-MEM and Letta never update on Hindi probes, which the answers contradict.

**The one real signal** (n = 1 fact, so a lead, not a result): Mem0 keeps *both* "Has a severe allergy to peanuts" and "Allergic to cashews" in the final store after an English correction, and answers with both. Mem0's Hindi-stored runs had already mis-written peanuts as "moong dal", and its correction merged cleanly ("cashews instead of moong dal"). This bears on RQ3, but nothing about it can be claimed until the update subset is scaled up.

### Proposed definition
1. **Denominator (A):** corrected facts = facts with a `kind: "correction"` turn in `run_log.jsonl`. This matches METRICS_SPEC §2.4 as written.
2. **Write-first gating:** a corrected fact is SR-eligible only if its original value was written (WF, under D1). This mirrors rule 11. If the old value was never stored correctly, "did the update replace it" is undefined. Letta hi→en's 绿豆 case drops out of SR and stays a WF failure.
3. **Three outcomes, not two (B):** classify each eligible corrected fact as UPDATED / STALE (old asserted, with or without new) / MISS. Report `staleness_rate = STALE / eligible` (the spec's formula) **and** `reprobe_miss_rate = MISS / eligible` next to it, so a run that answers nothing is never read as "updates worked" or as "updates failed".
4. **Hindi targets (C):** `update.value_aliases.hi` for the old and new values, authored by the D1 rule (verbatim spans from the fact's own Hindi surfaces; never taken from model outputs).
5. **Negation (D):** strict matching can't tell "peanuts" from "not peanuts". Options: (a) strict SR treats any old-value mention as stale and is labelled an upper bound, with the NLI lenient tier ("the user is allergic to {old}" entailed?) as the reported SR; (b) a small fixed list of negation cues per language within N tokens of the match. (a) is my recommendation: (b) is a hand-tuned heuristic in Hindi and English that reviewers will poke at.
6. **Missing re-probe (E):** a corrected fact with no `reprobe_result` makes SR `null` with an `invalid_metrics` entry, the same as the existing run-level rule.

### Questions for the guide
1. Is MISS reported separately (recommended), or folded into SR's denominator (SR = STALE / (STALE + UPDATED))? The second hides how often the agent answers nothing.
2. Is the write-first gate acceptable? It makes SR undefined for facts the framework mis-wrote, which on Hindi input with Letta is most of them.
3. Negation: NLI tier as the reported SR (5a) or a cue list (5b)?

---

## D7. Duplication Rate (DR)

### Problem
`compute_duplication_rate` counts every record in `store_final` that contains `fact.value` (or one of the surface sentences) as a copy of the fact. Distractors and corrections share the value, so they count:

- "My sister has an allergy to peanuts" (the f_001 distractor) → copy of f_001
- "Correction: I am not allergic to peanuts, but to cashews" → copy of f_001
- The denominator is `|F|` = 20 **including** the 3 distractors, and each distractor also "finds" its base fact's records.

There are no real duplicates in any of the 36 stores. On Hindi stores DR is 0 only because the matcher can't see Hindi (D1).

### Options (numbers: mean over 3 seeds; all std = 0)

| Run | DR now | Option 1: plant snapshot, planted facts only | Option 2: final store, planted facts only |
|---|---|---|---|
| amem_enen / amem_enhi | 0.20 | 0 | 0.12 |
| mem0_enen / mem0_enhi | 0.10 | 0 | 0.06 |
| all other runs | 0 | 0 | 0 |

- **Option 1: score DR on `store_after_plant.json` over planted facts.** Distractors (filler sessions) and corrections both arrive *after* the plant snapshot, so they can't inflate DR. Simple and framework-neutral. Cost: it can't see duplication created later (frameworks consolidate at different times: AGENTS.md §14).
- **Option 2: final store, planted facts only.** It still counts the distractor and the correction record, as the residual 0.06/0.12 shows. Not enough on its own.
- **Option 3: final store, disambiguated matching.** A record counts toward f only if it matches f's value **and** matches neither its distractor's distinguishing entity ("sister") nor f's updated value. It works across the timeline, but it's a per-fact heuristic that needs Hindi aliases for the entity terms as well.
- **Rejected: harness provenance metadata** (`metadata.fact_id` / `kind`). It's exact for Mem0 and A-MEM, but Letta's core-memory block has no per-record metadata, and Mem0's metadata after a merge belongs to whichever turn won. Scoring on it would make DR depend on adapter behaviour (rule 4 in §3, "special-casing a framework").

My recommendation: **Option 1 as the reported DR**, plus Option 3 on the final store as a secondary "post-session" DR once D1 aliases exist. But see D8 first: under the current session structure DR has nothing to measure either way.

---

## D8 (new). The session structure never restates a fact, so CONSOLIDATE is not tested

METRICS_SPEC §2.2 defines DR as the failure to recognise that "two turns (or parallel cross-lingual statements) express the same ground truth fact". The generator (`xlmem/benchmark/generator.py`) emits exactly **one** `plant` turn per fact. No fact is ever stated twice, in either language. So the only possible duplicates are a framework splitting one sentence into several records, and real DR is structurally ≈ 0 under every option above. That makes the EXPERIMENT_PLAN §4 gate criterion "DR ≥ 0.10" unreachable by construction, not "not met".

FMR is unaffected: it is tested by the distractor pairs, which do exist.

**Proposed:** add a `restatement` turn kind. A subset of planted facts (e.g. 30%) gets re-stated in a later session, in the **other** language from the plant (store_lang ≠ restatement lang is the cross-lingual consolidation test, RQ2). Surfaces come from the already-authored `surface` map, so no new authoring is needed for hi/en. This is a **session-structure change** (AGENTS.md §8, "ask, don't assume"). It has to be the same across all compared conditions, and it belongs with the P1 fact-bank scale-up, before P3. Open question: does a restatement in the other language make the four directions differ in more than language? (Restatement language = the opposite of store_lang, so it's symmetric by construction, but the guide should confirm.)

The same goes for SR: corrections are issued in `store_lang`, so no cross-language update is tested (already noted under D6 in the status report). A `correction_lang` ≠ `store_lang` arm is the RQ3 test. With `update_subset_ratio` at 0.2 and 3 facts with `update` data, the pilot corrects 1 fact. P1 targets ≥ 30% of ~200–250 facts.

---

## What changes if all recommendations are adopted
- `scoring/staleness.py`: three-way classification, eligible = corrected ∩ written, `reprobe_miss_rate`, null on a missing re-probe.
- `scripts/score.py`: corrected set from the log; DR on the plant snapshot over planted facts.
- `benchmark/generator.py` (D8): `restatement` turns; optional `correction_lang`.
- METRICS_SPEC §2.2/§2.4, ARCHITECTURE §8, EXPERIMENT_PLAN §4 (the DR gate) updated to match.
- Hand-computed fixture tests from the real pilot answers above, e.g. mem0_enen/11 (S), mem0_hihi/11 (U, with the old value negated), letta_hihi/33 (W).
- Re-score all runs. Nothing is implemented on this branch yet; the code waits for the decision.
