# Fact bank: open decisions (2026-10-18)

**Status of this document:** a record of open questions and proposals. **Nothing here is approved.** AGENTS.md §8 says research-design decisions are "owned by the student and guide". On 2026-10-18 the student reported, in a chat session, that the guide delegated these choices to the student's judgement. The student then replied "approved" to a table of recommendations for D1–D7. **That approval is not yet recorded** in the decision log (`docs/STATUS_2026-10-18.md` on `resume-oct18`), so every item below is treated as open until it is.

Counts below come from the source files on `benchmark/templates`. "Canonical" means `data/facts_v1.yaml`, the only merged fact bank. "Candidate" means `data/candidates/*.yaml`; none of it is bilingually reviewed (BENCHMARK_SPEC §7.4).

## Metric decisions (logged in `docs/STATUS_2026-10-18.md`, main checkout)
| # | Question | Repository status | Depends on / affects |
|---|---|---|---|
| D1 | How strict WF and recall match Hindi: which aliases are "authorized" (METRICS_SPEC §3.1) | Open. Proposal on branch `proposal/hindi-matching` (`docs/proposals/HINDI_MATCHING.md`). Recommendation approved in chat only. | Every Hindi WF and recall number; item B below; the skipped test `test_every_fact_has_a_value_form_in_its_own_sentences` |
| D2 | Is the code-switched (hi-en) condition in scope? | Open | Whether hi-en probes need review priority |
| D3 | Full 72-run mitigation matrix, or a subset | Open | Compute plan only |
| D4 | Upgrade Mem0 0.1.26 → 2.x before the main runs | Open | Comparability with the pilot runs |
| D5 | Positioning against Agarwal (NeurIPS 2026 PALM workshop) | Open | Writing only |
| D6 | SR denominator: facts with update data, or facts actually corrected | Open | SR values; D6b below |
| D6b | Correct every fact that has update data, instead of a 20% subset | Open. **Conflicts with BENCHMARK_SPEC §5**, which says "explicit correction turns for a fixed 20% subset of facts". Also `update_subset_ratio = 0.2` in `xlmem/benchmark/generator.py`. | If approved: §5 must be amended (text below), the generator default and its tests changed, and every run re-scored |
| D7 | DR counts distractor and correction records as duplicates of the base fact | Open | All DR values; FMR interpretation |

**Amendment required if D6b is approved (not applied):** BENCHMARK_SPEC §5, CORRECTION PHASE. Replace "Ingestion of explicit correction turns for a fixed 20% subset of facts in language L_update" with "Ingestion of explicit correction turns for every base fact that carries an `update` block, in language L_update". Then update `update_subset_ratio` in `generator.py` and the generator tests. If the correction language is also approved as `probe_lang` (RQ3), §5 should name it: "L_update = L_probe".

## Fact-bank questions
### A. Overlapping diet facts (`f_012`, `f_104`, `f_104_dist`)
**Evidence:**

| Fact | File | (entity, relation, value) | Statement (en) | Probe (en) | Kind |
|---|---|---|---|---|---|
| f_012 | facts_v1.yaml (canonical) | (user, dietary_preference, vegetarian) | I follow a strictly vegetarian diet. | What is my dietary preference? | base, probed |
| f_104 | health_batch_01.yaml (candidate) | (user, dietary_restriction, gluten_free), corrected to lactose_free | I eat a gluten-free diet. | What kind of diet do I follow? | base, probed |
| f_104_dist | health_batch_01.yaml (candidate) | (user, dietary_restriction, vegetarian), value-shift of f_104 | I am also vegetarian. | What kind of diet do I follow? | distractor, never probed |

**The problem:**
- `f_104_dist` states the same proposition as `f_012` under a different relation name. Planted together, the benchmark itself contains two records of one fact, which inflates duplicates and confuses false-merge counts.
- Separately, `f_104`'s question is also answered by `f_012`, and both are base facts that get asked. So a correct "vegetarian" answer to `f_104` would be scored as a miss.
- The shared question between `f_104` and `f_104_dist` is *not* the problem in itself. BENCHMARK_SPEC §4 rule 2 (value-shift) implies a shared question, and distractors are never asked (`generator.py`: "Probe all base facts").

**Alternatives:**
1. *(Recommended)* Replace `f_104_dist` with an entity-shift distractor such as (user_sister, dietary_restriction, gluten_free). Give `f_104` a question that "vegetarian" cannot answer, e.g. "What do I avoid in my diet for health reasons?" (wording needs review).
   - Effect: removes the duplicate and the ambiguity; health keeps 3 distractors.
2. Drop `f_104_dist` and reword `f_104`'s question as in 1.
   - Effect: health loses a distractor (4 → 3 for the domain, including facts_v1).
3. Treat `dietary_preference` and `dietary_restriction` as one relation, and model vegetarian + gluten-free as a multi-valued fact.
   - Effect: changes the schema's single-valued assumption for this relation, and strict scoring of multi-valued answers needs a rule. Larger change.

**Approval needed:** student + guide. Item E applies too, because `f_012` is canonical.

### B. Value matching for `f_105`, `f_109`, `f_110`
**Evidence:**
- The canonical values `flu_shot_pending`, `regular_donor` and `yoga_daily` are abstract labels. The schema (BENCHMARK_SPEC §2.1) only requires snake_case, not that the value occurs in the text.
- `compute_write_fidelity` (`xlmem/scoring/retrieval.py`) accepts the value **or any full surface sentence** as a target. So these facts match only a memory that contains a whole authored sentence verbatim; a paraphrase never matches.
- METRICS_SPEC §3.1 allows "the canonical value string … or authorized surface alias", but never says which aliases are authorized.

**Classification:** an unresolved question about what counts as a match (D1). It is not a data error under the current spec, and not an implementation bug.

**Alternatives** (after D1):
1. Add `value_aliases` copied verbatim from each fact's own sentences, e.g. "flu shot" or "फ्लू का टीका", per the D1 proposal's rule.
2. Rename the value keys to text that occurs in the sentence.
   - Effect: changes canonical tuples for the 3 facts.

**Approval needed:** D1. A ready test exists and is skipped until D1 is recorded. Run directly, it currently fails on exactly these three facts.

### C. Speaker persona in first-person Hindi / Hinglish
**Evidence:**
- 13 facts use masculine first-person verbs (रहता हूँ / karta hoon): `f_002 f_003 f_004 f_008 f_009 f_012 f_017` (canonical) and `f_103 f_104 f_104_dist f_106 f_109 f_110` (health candidates).
- BENCHMARK_SPEC §7.2's own example is "मैं पुणे में रहता हूँ", which is masculine.
- The template facts avoid first-person verbs altogether.
- The bank also includes `user_wife`, so the user is already implicitly cast as having a wife.

**The problem:** not a grammar error. It's an unstated persona, plus inconsistency between the hand-written and template facts. A model's handling of gendered Hindi could also differ by speaker gender.

**Alternatives:**
1. Document a fixed male speaker persona in BENCHMARK_SPEC and the dataset card, and leave the text unchanged.
2. Rewrite the 13 facts without speaker-gendered verbs (possessive or "मुझे … है" constructions).
   - Effect: changes canonical text in facts_v1, see item E.
3. Make speaker gender a controlled covariate with paired versions.
   - Effect: doubles part of the bank. Out of scope.

**Approval needed:** student + guide.

### D. Domain of `f_004` and domain balance
**Evidence:**
- `f_004` (user, speaks_language, marathi) has domain `languages`. That is not one of the 8 approved domains (BENCHMARK_SPEC §3).
- BENCHMARK_SPEC §3 also sets a target of "30–35 facts per domain, total target ~250". Base-fact counts if every candidate were merged (distractors excluded):

| Domain | Canonical base | Candidate base | Total base | Distractors | With correction |
|---|---|---|---|---|---|
| dining | 2 | 34 | **36** | 13 | 17 |
| family | 2 | 31 | 33 | 12 | 11 |
| finance | 2 | 24 | **26** | 9 | 10 |
| health | 2 | 10 | **12** | 4 | 11 |
| hobbies | 1 | 30 | 31 | 11 | 12 |
| languages | 1 | 0 | 1 | 0 | 0 |
| tech | 2 | 29 | 31 | 11 | 12 |
| travel | 3 | 29 | 32 | 12 | 13 |
| work | 2 | 29 | 31 | 11 | 13 |
| **total** | **17** | **216** | **233** | **83** | **99** |

**Outside the 30–35 range:** dining (36), finance (26) and health (12). Whether "facts" in §3 means base facts only is not stated; this table excludes distractors.

**Alternatives:**
- **For `f_004`:**
  1. Re-label it `family`: a language spoken at home.
  2. Re-label it `work`.
  3. Add `languages` as a ninth domain (amends §3).
- **For the balance:**
  1. Author more health and finance facts, which expands the bank.
  2. Amend §3 to a looser range.
  3. Report the imbalance as a limitation.

Every option changes either the bank or the spec. **Approval needed:** student + guide.

### E. Fix legacy facts in place, or at the next bank version
**Evidence:**
- Confirmed text defects in canonical `facts_v1.yaml`:
  - `f_010`: "अगली महीने" should be "अगले महीने".
  - `f_006`: the probe drops "morning", and has a Hindi gender error ("मेरी पसंदीदा पेय"; पेय is m).
- Proposed corrections, written without speaker gender, are in the workbook's "Existing data" tab.
- `facts_v1.yaml` is the input to the Sep and Oct pilot runs, and its sha256 is in `runs/pilot_v2/manifest/inputs.sha256` (main checkout).

**Alternatives:**
1. *(Proposed)* Keep facts_v1 frozen, and apply the agreed corrections when the reviewed facts are merged into the next bank.
   - Effect: pilot provenance stays exact; the next bank differs textually from the pilot's.
2. Edit facts_v1 in place.
   - Effect: the pilot manifest hash no longer matches the file; the logs keep the texts that were actually used.

**Approval needed:** student.

### F. Synthetic health content and public release
**Evidence:**
- PRD §4 lists "Human-subject data collection" as a non-goal: "All conversations are synthetic and scripted."
- PRD G1 is to release the benchmark.
- BENCHMARK_SPEC §3 approves Health & Medical (allergies, chronic conditions, prescriptions) as domain 1.
- No release or sensitive-content policy exists anywhere in the repository.
- The health facts are fictional statements about a fictional user: no real person, record or identifier.

**The problem:** no conflict with any written policy, because none exists. That absence is itself the gap: there is nothing yet to check a release against.

**Alternatives:**
1. *(Proposed)* Before release, add a dataset card saying all people and facts are fictional and template-authored, and that no real personal data is included. Keep the domain.
2. Ask whether VIT requires an ethics or data review for a public dataset with health-themed synthetic content.

**Approval needed:** student + guide. Possibly the institution, which is unknown.

## Wording that still needs bilingual review
No sentence in the bank has been checked by a native or bilingual speaker. The audit's Hindi judgements are Claude's. Items with an explicit author's note in the workbook:
- P025 भोजन शैली;
- P105 (double का);
- P122 (किसमें है);
- department (डिपार्टमेंट vs विभाग);
- instrument (वाद्ययंत्र vs साज़);
- Mysuru (मैसूर);
- Egypt (मिस्र);
- commute values (auto / cycle);
- People: मेरे दोस्त (gender), and पिता vs पिताजी.
