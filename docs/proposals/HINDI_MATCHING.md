# Proposal: Hindi-aware matching for Write Fidelity and Recall

**Status:** PROPOSAL, not merged. Branch `proposal/hindi-matching`. **Needs a decision from student + guide (D1 in `docs/STATUS_2026-10-18.md`).**
**Affects measurement semantics:** yes. It changes Write Fidelity (WF) and strict XL-Recall@k for every run, English included. If adopted: update METRICS_SPEC.md §3 and ARCHITECTURE.md §8, then re-score all runs (no GPU re-run needed).

## 1. Problem
In the Sep pilot, Hindi WF came out at 0.30 (hi→hi) and 0.35 (hi→en). The real store dump shows **16 of 17** planted facts stored with the correct value. The scorer, not Mem0, accounts for most of the gap. Four defects compound:

| # | Defect | Where | Effect |
|---|---|---|---|
| A | `normalize_text` drops Devanagari vowel signs (Python's `\w` doesn't match combining marks) | `scoring/judge.py` | "वर्तमान में पुणे" → "वर तम न म प ण"; Hindi tokens are mangled on both sides |
| B | Matching falls back to a raw substring test (`\b` fails around Devanagari marks) | `scoring/judge.py` | False positives: "पुणे" ⊂ "पुणेरी", "visa" ⊂ "advisable" |
| C | The only Hindi targets are *full surface sentences*; the canonical `value` is English (`pune`) | `scoring/retrieval.py` | A Hindi paraphrase of a fact can never match |
| D | WF divides by all 20 facts, distractors included. Distractors are delivered as filler *after* the `store_after_plant` snapshot | `scripts/score.py` | Distractors "pass" by sharing their base fact's value. Recall over the written set is capped (en→en R@5 can't exceed 17/20 = 0.85) |

## 2. Proposed definition
1. **Normalization (A):** keep Unicode letters, digits and combining marks. Replace everything else with a space. Fold the nukta (U+093C) so फ़िल्टर = फिल्टर.
2. **Whole-token matching (B):** a target matches if it occurs as a whole-token sequence in the normalized candidate. The existing singular/plural expansion is kept.
3. **Value aliases (C):** each fact gets `value_aliases: {hi: [...]}`. **Rule: an alias must be the value's span copied verbatim from the fact's own authored Hindi surface** (enforced when the aliases were added). Aliases are never taken from model outputs, so they are not tuned to the system under test. Strict targets = `value` + aliases + surface sentences.
4. **Planted-fact denominator (D):** WF counts only facts with a `plant` turn in `run_log.jsonl`.
5. **Lenient WF (NLI tier, PRD R8):** a fact counts as written if it strictly matches, **or** some memory entails one of its authored surface sentences under the multilingual NLI judge (mDeBERTa-xnli, threshold 0.70). It is reported **next to** strict WF, never instead of it. Opt-in via `score --nli`. The CLI refuses to run if the model fails to load, rather than using `NLIJudge`'s token-overlap fallback. The judge now passes the hypothesis verbatim (`hypothesis_template="{}"`), where the pipeline default would make it "This example is …".

## 3. Effect on the Sep pilot (Mem0 + Qwen2.5-7B, 20 facts, seed 11; illustrative only, single seed)
Strict scores. "No aliases" applies 1, 2 and 4 only.

| Run | Variant | WF | R@1 | R@5 |
|---|---|---|---|---|
| en→en | current | 1.000 | 0.750 | 0.850 |
| | proposal | 1.000 | 0.882 | 1.000 |
| en→hi | current | 1.000 | 0.750 | 0.800 |
| | proposal | 1.000 | 0.882 | 0.941 |
| hi→hi | current | 0.300 | 0.667 | 0.667 |
| | no aliases | 0.294 | 0.800 | 0.800 |
| | proposal | **0.882** | 0.933 | 0.933 |
| hi→en | current | 0.350 | 0.714 | 0.857 |
| | no aliases | 0.353 | 0.833 | 1.000 |
| | proposal | **0.941** | 0.875 | 1.000 |

What's left uncaught under the proposal:
- **f_001, a real write failure, in both Hindi runs.** Mem0 stored "मुझे मूंगफली से गंभीर एलर्जी है" (peanut allergy) as *"Has a serious allergy to moong dal"*. It mistranslated the fact during extraction. This is exactly the kind of cross-lingual write corruption the paper is about, and the proposal keeps it as a miss under both tiers.
- **f_005 (hi→hi), a spelling variant.** Stored as "गोल्डन रिट्रवर" against the authored "रिट्रीवर". Strict misses it; lenient NLI is expected to recover it.

The English-run changes come only from defect D, the distractor denominator. So **the "current" en recall of 0.85 is an artifact as well**.

## 4. Tests
`tests/test_hindi_matching.py` runs on the real hi→hi dump, copied to `tests/fixtures/`. The expected sets are hand-judged per fact; the reasoning is in the file's comments.
- Strict WF = 15/17 (misses f_001 and f_005).
- Lenient WF with a hand-labelled stub NLI judge = 16/17 (recovers f_005, keeps the f_001 miss).
- Normalization keeps vowel signs and folds the nukta. Matching is whole-token ("पुणे" ∉ "पुणेरी", "visa" ∉ "advisable").

The real NLI model has **not** been run: it isn't downloaded yet, and no GPU runs were in scope. Its agreement with the hand labels still needs checking. If the guide wants it, the next step is to spot-check NLI against human judgement on the 18 pilot memories.

## 5. Open questions for the guide
1. Adopt strict = value + verbatim-surface aliases? Or also allow curated spelling variants (रिट्रीवर / रिट्रिवर) and romanized forms? Every variant added makes strict more lenient, and has to be authored without looking at model outputs.
2. Is the NLI lenient tier the reporting tier for WF, or only a diagnostic? PRD R8 says to report both.
3. Should the whole-token change (B) also apply to English? It already does in this draft. It changed no English pilot numbers, but it is a definitional change.
4. Staleness Rate also uses `strict_match` on old and new values with no aliases. Hindi re-probe responses will under-count staleness until `update.value_aliases` exists. That's not done here; it can be decided together with D6.
5. The aliases need the same bilingual review as the surfaces (BENCHMARK_SPEC §7.4).
