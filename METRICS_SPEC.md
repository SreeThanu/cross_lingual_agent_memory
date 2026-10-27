# METRICS_SPEC.md — XLMem Metrics Specification

**Status:** Approved Specification · **Metrics version:** v3 (2026-10-27; see §3.5 and §6). v2.1 definitions below remain the reference for `metrics_version: "2.1"` scores.  
**Purpose:** Defines exact mathematical formulas, operation attribution, matching algorithms (strict vs lenient), failure isolation ordering, and seed aggregation procedures for XLMem.

---

## 1. Metric Hierarchy & The Attribution Invariant

Every failure in an agent memory system belongs to exactly **one** of four lifecycle operations:
1. **WRITE:** The fact was never successfully extracted or persisted into the store.
2. **CONSOLIDATE:** The store failed to deduplicate cross-lingual duplicates, or erroneously fused distinct near-miss facts.
3. **RETRIEVE:** The fact was stored, but the retrieval mechanism failed to surface it given a cross-lingual query.
4. **UPDATE:** A correction was issued, but the store kept the stale/superseded fact or created contradictory entries.

### The Write-First Ordering Rule (Non-Negotiable)

```
        ┌─────────────────────────────────────────────────────────┐
        │ 1. INSPECT DUMP() AFTER PLANT: Compute Write Fidelity   │
        └────────────────────────────┬────────────────────────────┘
                                     │
                    Is fact f in store dump?
                   /                        \
                 NO                          YES
                 │                            │
       ┌─────────▼────────┐          ┌────────▼────────┐
       │   WRITE FAILURE  │          │ Eligible for    │
       │ (Not a retrieval │          │ RETRIEVAL eval  │
       │     failure!)    │          │ (XL-Recall@k)   │
       └──────────────────┘          └─────────────────┘
```

> **CRITICAL RULE:** If a fact $f$ is absent from `dump()` after the plant phase, it is a **WRITE failure**. It MUST NOT be counted as a retrieval failure in `XL-Recall@k` without explicit partitioning. Conflating write omissions with cross-lingual retrieval failure destroys measurement validity.

---

## 2. Operation-by-Operation Metric Definitions

### 2.1 Operation 1: WRITE

#### A. Write Fidelity (WF)
> **Metrics v3:** this metric is defined by the matching contract in §3.5 (policy in §3.5.8). The text below defines the v2.1 version, kept for reproducing `metrics_version: "2.1"` scores.

Measures whether planted conversational facts are successfully extracted and stored in the memory substrate.
$$\text{WF}(L) = \frac{|\{f \in \mathcal{F}_{\text{planted}, L} \mid \text{matches\_store}(f, \mathcal{M}_{\text{plant}})\}|}{|\mathcal{F}_{\text{planted}, L}|}$$
- **Domain:** $[0.0, 1.0]$ (higher is better).
- **Operation Tested:** WRITE.
- **Computation:** For each planted fact $f$, inspect `dump()` taken immediately after Session 1 plant turns. $\text{matches\_store}(f, \mathcal{M}_{\text{plant}})$ is true if at least one stored memory record contains the canonical value of $f$ (strict or NLI entailment).

#### B. Encoding Asymmetry (EA)
Measures whether storing in Hindi incurs greater memory encoding loss than storing in English.
$$\text{EA} = \text{Recall}(L_{\text{store}}=\text{hi}, L_{\text{probe}}=\text{en}) - \text{Recall}(L_{\text{store}}=\text{en}, L_{\text{probe}}=\text{hi})$$
- **Domain:** $[-1.0, +1.0]$ (value near $0$ indicates symmetric cross-lingual capability; positive means Hindi storage is surprisingly better; negative means English storage dominates).
- **Operation Tested:** WRITE / Storage substrate representation.

---

### 2.2 Operation 2: CONSOLIDATE

#### A. Duplication Rate (DR), primary: `plant_duplication_rate` (metrics v2, decision D7)
> **Metrics v3:** this metric is defined by the matching contract in §3.5 (policy in §3.5.8). The text below defines the v2.1 version, kept for reproducing `metrics_version: "2.1"` scores.

Measures the failure of the consolidation mechanism to recognise that two turns (or parallel cross-lingual statements) express the same ground truth fact, resulting in redundant memory bloat.
$$\text{DR}_{\text{plant}} = \frac{1}{|\mathcal{F}_{\text{base}}|} \sum_{f \in \mathcal{F}_{\text{base}}} \max(0, N_{\text{records}}(f, \mathcal{M}_{\text{plant}}) - 1)$$
- $\mathcal{F}_{\text{base}}$: the facts that have a `plant` turn in `run_log.jsonl` and are not distractors (`distractor_of` is null). Distractors and corrections are never members.
- $\mathcal{M}_{\text{plant}}$: Snapshot A, `store_after_plant.json`. The runner takes it after the plant session and its consolidation trigger, **before** any filler, distractor or correction turn (BENCHMARK_SPEC §5). So distractor and correction records cannot be in it.
- $N_{\text{records}}(f, \mathcal{M}_{\text{plant}})$: the number of distinct records in Snapshot A that `strict_match` (§3.1) $f$'s canonical value or one of $f$'s own authored surface sentences. This matcher is unchanged from v1.
- **Missing facts:** a planted fact with $N = 0$ contributes $0$ and stays in the denominator (it is a WRITE failure, measured by WF).
- **Multiple matches:** a fact matched by $N > 1$ records contributes $N - 1$. One record that matches two different facts counts once toward each.
- **Missing Snapshot A:** $\text{DR}_{\text{plant}}$ is `null`, with a reason in `invalid_metrics`. It never falls back to the final store.
- **No base facts planted:** `null`, with a reason.
- **Uniform across frameworks:** no framework metadata (`metadata.fact_id`, `kind`, …) is used. Every framework is scored on its record texts alone.
- **Domain:** $[0.0, \infty)$ (ideal is $0.0$; $1.0$ means on average every fact is stored twice).
- **Operation Tested:** CONSOLIDATE, at the end of the plant phase only. Duplication a framework creates later (it consolidates at different times, AGENTS.md §14) is out of scope for the primary metric.
- **Known limitations:**
  - (a) The session structure plants each fact once and never restates it (open decision D8), so a real duplicate can only come from a framework splitting one statement into several records.
  - (b) `strict_match` mis-normalises Devanagari (open decision D1), so duplicates written in Hindi are under-detected.

**Not official: post-session DR.** Duplication on the final store (Snapshot B) is a possible future *diagnostic*. Before it can be one, it needs validated language aliases (D1) and tested handling of distractor and correction records. The v1 `duplication_rate` (below) is not a valid version of it.

**Superseded: v1 `duplication_rate`.** Same formula, computed on Snapshot B (falling back to Snapshot A) over **all** facts, distractors included. Every record containing the value counted, so a distractor ("My sister has an allergy to peanuts") and a correction ("…not peanuts, but cashews") both counted as copies of the base fact. In the pilot every non-zero v1 DR came from this. See §6.

#### B. False Merge Rate (FMR)
> **Metrics v3:** this metric is defined by the matching contract in §3.5 (policy in §3.5.8). The text below defines the v2.1 version, kept for reproducing `metrics_version: "2.1"` scores.

Measures over-eager consolidation where two semantically related but distinct facts (e.g. a base fact and its near-miss distractor) are incorrectly collapsed into a single memory entry.
$$\text{FMR} = \frac{|\{(f, f') \in \mathcal{D}_{\text{distractor\_pairs}} \mid \text{falsely\_merged}(f, f', \mathcal{M})\}|}{|\mathcal{D}_{\text{distractor\_pairs}}|}$$
where $\text{falsely\_merged}(f, f', \mathcal{M})$ is true if a single memory entry matches both canonical values while failing to separate distinct entities/relations.
- **Domain:** $[0.0, 1.0]$ (ideal is $0.0$).
- **Operation Tested:** CONSOLIDATE.

---

### 2.3 Operation 3: RETRIEVE

#### A. XL-Recall@k
> **Metrics v3:** this metric is defined by the matching contract in §3.5 (policy in §3.5.8). The text below defines the v2.1 version, kept for reproducing `metrics_version: "2.1"` scores.

The fraction of successfully stored planted facts retrieved in the top-$k$ candidates when probed in an alternate language.
$$\text{XL-Recall}@k (L_{\text{store}} \to L_{\text{probe}}) = \frac{\sum_{f \in \mathcal{F}_{\text{written}}} \mathbb{I}(\text{hit}(f, \mathcal{R}_k(f)))}{|\mathcal{F}_{\text{written}}|}$$
where $\mathcal{F}_{\text{written}} = \{f \in \mathcal{F}_{\text{planted}} \mid f \in \text{dump}()\}$ and $\mathcal{R}_k(f)$ is the list of top-$k$ memory records returned by `retrieve()`.
- **Evaluated at:** $k \in \{1, 3, 5\}$.
- **Operation Tested:** RETRIEVE.

#### B. Language Transfer Gap (LTG)
The performance penalty incurred purely by switching languages between storage and retrieval.
$$\text{LTG} = \text{Recall}_{\text{same-lang}} - \text{Recall}_{\text{cross-lang}}$$
where:
$$\text{Recall}_{\text{same-lang}} = \frac{1}{2}\left(\text{Recall}(\text{en}\to\text{en}) + \text{Recall}(\text{hi}\to\text{hi})\right)$$
$$\text{Recall}_{\text{cross-lang}} = \frac{1}{2}\left(\text{Recall}(\text{hi}\to\text{en}) + \text{Recall}(\text{en}\to\text{hi})\right)$$
- **Domain:** $[-1.0, +1.0]$ ($0.0$ means zero language tax; positive value indicates language transfer degradation).
- **Operation Tested:** RETRIEVE.

---

### 2.4 Operation 4: UPDATE

#### A. Staleness Rate (SR) and Miss Rate (MR) (metrics v2, decision D6)
> **Metrics v3:** this metric is defined by the matching contract in §3.5 (policy in §3.5.8). The text below defines the v2.1 version, kept for reproducing `metrics_version: "2.1"` scores.

**What it measures:** *observed stale recall after correction*. SR is judged from the agent's generated re-probe answer. It is **not** a direct measurement of the internal store: a framework can keep a stale record that the answer never surfaces, or answer stale from a store that holds only the new record.

**Populations.** For one seed:
- $\mathcal{F}_{\text{corrected}}$: facts with a `turn_trace` record of `kind: "correction"` in `run_log.jsonl`. Facts that merely carry `update` data in the fact bank are **not** members (the generator corrects only a subset, BENCHMARK_SPEC §5).
- **Write gate:** $f \in \mathcal{F}_{\text{corrected}}$ is *write-ineligible* if $f$ is not in $\mathcal{F}_{\text{written}}$ under the existing WF criterion (§2.1, Snapshot A). It is reported separately and excluded from SR and MR. If the original value was never stored, whether the update replaced it is undefined (§1, write-first rule).
- **Re-probe validity:** each remaining fact needs exactly one `reprobe_result` record with its `fact_id` and a `response` field. A missing, duplicated or field-less record is *missing_or_invalid*. Operationally (v2.1):
  - A record is *well-formed* only if its `data` is a mapping with a non-empty string `fact_id` and `probe_lang`, a string `store_lang` and a string `response`. The `response` may be empty: an empty answer is MISS. If `retrieved` is present, it must be a list of memory records.
  - A null or non-string `response` is never converted to text.
  - Validity is judged on **raw** records. For a fact to qualify, it must have exactly one raw record, and that record must be well-formed. One well-formed plus one malformed record is two records, so the fact is *missing_or_invalid*.
  - A malformed record whose `fact_id` is missing or unusable can't be attributed to a fact. It could be a duplicate of any correction, so its presence makes the seed's SR and MR `null` (case (v) below).
  - Malformed records never stop the rest of the seed from being scored.
- **Fact reference:** a correction whose `fact_id` is not in the fact bank, or whose fact has no `update` block, is *missing_or_invalid*. This is a data defect, and the write gate is not applied to it.
- **Alias availability:** if `probe_lang` is not `en`, the fact needs authored aliases (§3.3) for both its old and updated value in `probe_lang`. Otherwise it is *missing_or_invalid*. English-only matching is never applied silently to a non-English answer.
- $\mathcal{F}_{\text{eligible}}$: the corrected facts left after these exclusions.

**Outcome of each eligible re-probe** (exactly one, rules in §3.3):
- `STALE`: the old value is *asserted* as current, whether or not the new value is also there ("conflicted" counts as stale, as in v1).
- `UPDATED`: the new value is asserted and the old value is not asserted.
- `MISS`: anything else, i.e. an empty, wrong, garbled or unrelated answer, an old value mentioned only in an ambiguous frame, or a new value that is only negated.

$$\text{SR} = \frac{|\text{STALE}|}{|\mathcal{F}_{\text{eligible}}|}, \qquad \text{MR} = \frac{|\text{MISS}|}{|\mathcal{F}_{\text{eligible}}|}, \qquad \text{write\_ineligible\_rate} = \frac{|\text{write-ineligible}|}{|\mathcal{F}_{\text{corrected}}|}$$

Misses stay in the SR denominator. A wrong answer is a MISS, never STALE.

**Reconciliation (checked by the scorer):** $|\mathcal{F}_{\text{corrected}}| = |\text{write-ineligible}| + |\text{missing\_or\_invalid}| + |\mathcal{F}_{\text{eligible}}|$ and $|\mathcal{F}_{\text{eligible}}| = |\text{UPDATED}| + |\text{STALE}| + |\text{MISS}|$.

**SR and MR are `null`** (with the reason in `invalid_metrics`; the counts are still reported) when:
- (i) the log has no correction turn;
- (ii) Snapshot A is missing, so the write gate can't be applied;
- (iii) any correction is *missing_or_invalid* (a write-eligible correction without a valid re-probe or aliases, or a bad fact reference). In a correct run every correction refers to a known fact with an `update` block and gets re-probed, so a gap is a harness or data defect and the whole seed's SR is invalid;
- (iv) $|\mathcal{F}_{\text{eligible}}| = 0$, e.g. every corrected fact is write-ineligible;
- (v) the log holds a malformed `reprobe_result` that can't be attributed to a fact (v2.1).

`write_ineligible_rate` is `null` only in cases (i) and (ii).

**Reported per seed:** `eligible_corrections`, `updated_count`, `stale_count`, `miss_count`, `write_ineligible_count`, `missing_or_invalid_reprobe_count`, `staleness_rate`, `miss_rate`, `write_ineligible_rate`, plus each fact's outcome and the matched spans. **Across seeds:** the mean ± sample std of the per-seed rates (§5), with `n_seeds` valid and the eligible count per seed. Seeds are never pooled into one denominator.

- **Domain:** SR, MR in $[0.0, 1.0]$ (SR ideal is $0.0$).
- **Operation Tested:** UPDATE.
- **Strict only.** SR v2 has no lenient (NLI) tier. §3's rule that every response metric is reported under both modes doesn't apply to SR v2, because decision D6 excludes NLI and LLM judges from this metric. A lenient SR would be a new, separately versioned metric.

**Superseded: v1 `staleness_rate`.** Denominator = every fact with `update` data (whether or not it was corrected). Stale if `strict_match(old) or (not strict_match(new) and not hit_strict)`, but the runner always writes `hit_strict = False`, so **any** answer without the new value counted as stale. Answers were matched against the English values only, with no negation handling, and a missing re-probe counted as not stale. See §6.

---

## 3. Matching Procedures: Strict vs Lenient (NLI)

To avoid evaluator bias and prevent claims that results depend on string parsing, **all retrieval and response metrics are scored under both Strict and Lenient modes simultaneously**.

### 3.1 Strict Matching
1. **Canonical Normalization:** Strip punctuation, lowercase, normalize whitespace, and apply Unicode NFC normalization.
2. **Hit Condition:** The canonical value string $v$ (e.g. `"peanuts"`) or authorized surface alias in the probe language must appear as an exact token/substring within the retrieved memory or generated answer.

### 3.2 Lenient (NLI) Matching
Uses the local open-weight multilingual NLI model `mDeBERTa-v3-base-xnli-multilingual`.
1. **Premise ($P$):** The text of the retrieved memory record or agent's generated answer.
2. **Hypothesis ($H$):** A templated declarative assertion of the target fact in the probe language:
   - For `(user, allergic_to, peanuts)` in English: *"The user is allergic to peanuts."*
   - In Hindi: *"यूज़र को मूंगफली से एलर्जी है।"*
3. **Hit Condition:** $P(\text{entailment} \mid P, H) \ge 0.70$.

Both Strict and Lenient scores must be reported side-by-side in all final evaluation tables. (Exception: SR v2, §2.4.) **Suspended in metrics v3** (§3.5.10): no lenient column is reported until a lenient tier has a defined purpose and has been validated independently.

### 3.3 Staleness re-probe matching (SR v2 only, decision D6)
SR v2 classifies re-probe answers with its own deterministic matcher, `xlmem/scoring/staleness.py`. The §3.1 matcher (`judge.strict_match`) can't be used. Its normalisation deletes Devanagari vowel signs ("काजू" → "क ज"), and its raw-substring fallback would then match unrelated Hindi words. Fixing §3.1 is part of the open decision D1 and would change WF and recall, so until D1 lands **SR uses a different matcher from WF, recall, DR and FMR**. That difference is a known limitation, to be resolved together with D1.

1. **Normalisation:** Unicode NFC, `casefold()`, `_` → space.
2. **Sentences:** the answer is split on `. ! ? । ॥ ;` and newlines. Every rule below applies within one sentence.
3. **Tokens:** maximal runs of characters whose Unicode category is a letter (L\*), a mark (M\*) or a decimal digit (Nd). Everything else separates tokens. Vowel signs are kept. "don't" becomes `don`, `t`. A mixed-script run such as "कashews" is one token and matches no target.
4. **Targets.**
   - Old: the canonical `value`, plus the authored aliases for `probe_lang` (§3.4).
   - New: `update.updated_value`, plus its authored aliases for `probe_lang`.
   - The canonical (English) values are targets in every probe language, because answers often embed them.
   - Plural variant: if a target's last token is ASCII-alphabetic, also try that token with a trailing `s` removed (if longer than 3 characters) or added (as in §3.1).
   - A **mention** is a target's token sequence occurring contiguously, as whole tokens, in a sentence.
5. **Frame of each mention**, checked in this order:
   1. **AFFIRMED (supported contrast):**
      - `but` or `बल्कि` among the 2 tokens before the mention, with no negation cue (`not no never नहीं न मत`) between it and the mention ("not X, but Y"; "X से नहीं, बल्कि Y से").
      - `instead` or `not` as the very next token ("Y instead of X"; "Y, not X").
      - The pair `न कि` among the 4 tokens after the mention, with no other negation cue before it ("Y से एलर्जी है, न कि X से").
   2. **NEGATED (supported negation or past frame):**
      - English: `not`, `no` or `never` among the 3 tokens before; `instead of` / `rather than` right before; `previously`, `earlier` or `formerly` among the 4 tokens before; the pair `used to` starting among the 6 tokens before ("used to be allergic to X"); `was` or `were` among the 3 tokens before.
      - Hindi: `नहीं` among the 2 tokens after ("X से नहीं", "X नहीं"); `न कि` right before; `बजाय` among the 2 tokens after ("X के बजाय"); `पहले` among the 4 tokens before; `था` / `थी` / `थे` among the 3 tokens after.
   3. **AMBIGUOUS:** the sentence contains any cue token from the lexicon below, but no supported pattern covers the mention.
   4. **ASSERTED:** everything else.
   - Cue lexicon. English: `not no never nor neither instead rather but however although though longer t was were previously earlier formerly used`. Hindi: `नहीं न मत बजाय लेकिन परंतु किंतु बल्कि पहले था थी थे`.
6. **Outcome:**
   - any old mention ASSERTED **or AFFIRMED** → `STALE`. AFFIRMED is the contrastive form of assertion ("peanuts, not cashews"; "not cashews, but peanuts"), so the rule is the same for both values (§2.4: STALE = old value asserted as current). v2.0 counted AFFIRMED only for the new value;
   - otherwise, any old mention AMBIGUOUS → `MISS`;
   - otherwise, any new mention ASSERTED (or AFFIRMED) → `UPDATED`;
   - otherwise → `MISS`.
   - A sentence such as "You are allergic to cashews and peanuts" asserts both values, so it is STALE (conflicted).
7. **Limitations (must be reported with any SR number):**
   - The patterns are a short, fixed list. They do not capture Hindi or English semantics in general. Any construction not listed is ASSERTED if the sentence has no cue word, and AMBIGUOUS → MISS if it does.
   - Hindi transliterations of the English value ("कैश्वर", "काश्वे") are not authored aliases, so such answers are MISS.
   - Code-switched (`hi-en`) answers have no aliases yet, so their re-probes are *missing_or_invalid*.
   - **Unresolved (needs a specification decision): contrast followed by negation.** An AFFIRMED frame from a preceding `but` / `बल्कि` is not cancelled by a negation that *follows* the mention. So "I don't know, but cashews are not listed." is scored UPDATED, where MISS is the expected result. Not changed in v2.1.
   - **Disclosure:** the pattern list was written on 2026-10-27, *after* the 36 pilot v2 re-probe answers had been read during the D6 analysis. Two refinements were added the same day while writing the hand-computed tests (`tests/test_metrics_v2.py`), **before** any pilot run was rescored: the "Y, not X" / "Y …, न कि X" affirmed forms, and the 6-token `used to` window. It is based on the benchmark's own authored correction templates ("not X, but Y", "X से नहीं, बल्कि Y से") and common negation forms, but the pilot answers are not an independent test set for it. No native-speaker validation has been done.

### 3.4 Authored value aliases for SR (decision D6)
Aliases live in a sidecar file next to the fact bank: `data/aliases/<fact bank stem>.aliases.yaml`. They are not stored in the fact bank, so `facts_v1.yaml` and the hashes in the pilot manifests are unchanged, and nothing here pre-empts the field design of the open decision D1.
- The file records the sha256 of the fact bank it was written for. The loader refuses to use it with any other fact bank.
- Per fact, it holds `value: {<lang>: [...]}` and `updated_value: {<lang>: [...]}`.
- **Authoring rule (enforced by the loader):**
  - Every `value` alias must occur verbatim in the same fact's `surface[<lang>]`.
  - Every `updated_value` alias must occur verbatim in the same fact's `update.surface[<lang>]`.
  - Aliases are never taken from model outputs.
- **Scope:** used **only** by SR v2. WF, recall, DR and FMR do not read the file. Whether they should is D1.
- Like the surfaces, the aliases still need bilingual review (BENCHMARK_SPEC §7.4).

### 3.5 Matching contract MC-1 (metrics v3; decision D1)
Normative for every `metrics_version: "3"` score. Rationale, worked cases and the decision record: `docs/proposals/D1_MATCHING_CONTRACT.md` (revision 3, adopted 2026-10-27). Code: `xlmem/scoring/matching.py` (foundation), `support.py` (support evidence), `metrics_v3.py` (metric policies), `alias_bank.py` (aliases). Golden tests: `tests/golden/test_matching_v3.py`.

#### 3.5.1 Layers and principle
1. **Foundation:** normalisation, tokens, sentences, cue lexicons, targets, mentions and frames.
2. **Value match:** a mention of one of the fact's value targets. A match alone never earns credit.
3. **Support evidence** for a specific fact: SUPPORTED (confirmed or provisional) / UNRESOLVED / NOT_SUPPORTED / NONE.
4. **Metric policies** (§3.5.8).

**Principle:** insufficient evidence earns neither credit nor penalty. UNRESOLVED evidence is never counted as a write, hit, duplicate, merge or staleness event. It is counted and reported (§3.5.9).

#### 3.5.2 Foundation
- **Normalisation:** NFC, `casefold()`, `_` → space, Devanagari nukta (U+093C) folded. The tokenizer version is pinned (`TOKENIZER_VERSION = "mc1-tok-1"`); changing it requires regenerating tier-A spans and bumping the metrics version.
- **Tokens:** maximal runs of letters, combining marks and digits. **Sentences:** break on `. ! ? । ॥ ;` and newline.
- **Matching:** whole tokens only, never substrings. English plural ±`s` on a target's last ASCII token. No other stemming.
- **Longest match wins:** a mention contained in a longer mention of a different target in the same sentence is displaced.
- **Cue lexicons are language-scoped.** English cues are always active. The context language's lexicon is added on top: the store language for records, the probe language for answers. Hinglish (`hi-en`, in scope per D2) has its own romanized lexicon.

  | Category | en | hi | hi-en |
  |---|---|---|---|
  | NEG (before, 3 tokens) | not, no, never | मत | — |
  | NEG (after, 2 tokens) | — | नहीं | nahi, nahin |
  | NEG pair right before | instead of, rather than | न कि | na ki |
  | CONTRAST | but | बल्कि | balki |
  | PAST | previously, earlier, formerly (4 before); was, were (3 before); `used to` (6 before) | पहले (4 before); था, थी, थे (3 after) | pehle (4 before); tha, thi (3 after) |
  | NOW | now, currently | अब, फिलहाल | ab, abhi |
  | other ambiguity | nor, neither, however, although, though, longer, t | लेकिन, परंतु, किंतु, न | lekin, magar |
  | user subject (records / answers) | i, user / you | मैं, मुझे, मुझको / आप, आपको, तुम, तुम्हें | main, mujhe / aap, aapko, tum, tumhe |
  | pronoun | he, she, they, him, her | वह, वो, उसे, उसको | woh |

  `the` is not a Hinglish past cue, because it collides with English.

#### 3.5.3 Frames (per mention, within one sentence)
1. **AFFIRMED:**
   - a CONTRAST cue among the 2 tokens before, with no NEG cue between it and the mention; or
   - a NOW cue among the 2 tokens before, or right after, with no NEG cue among the 3 tokens before; or
   - `instead` or `not` right after the mention ("Y, not X"); or
   - the pair `न कि` / `na ki` among the 4 tokens after.
   - **O5:** a contrast- or NOW-affirmed mention with a NEG cue among the 3 tokens *after* it is **AMBIGUOUS**: the statement doesn't establish the current value. The after-forms ("Y, not X") are exempt, because there the NEG cue is the pattern itself.
2. **NEGATED:** NEG before (3 tokens), a NEG pair right before, NEG after (2 tokens), or `बजाय` after (2 tokens).
3. **PAST** (O4). Never negation by itself. It is resolved over the whole text unit (the record or answer): **NEGATED** (superseded) if the unit has a NOW cue, or asserts or affirms a different value of the same fact; otherwise **AMBIGUOUS**.
4. **AMBIGUOUS:** the mention isn't covered by a pattern, and the sentence holds a cue token that **no recognized pattern used**. A cue consumed by another mention's pattern doesn't make this mention ambiguous ("peanuts se allergy hai, cashews se nahi": `nahi` negates cashews and leaves peanuts ASSERTED). For pairs, only the first token is a cue (`used`, `instead`, `न`, `na`), never its common partner (`to`, `of`, `कि`).
5. **ASSERTED:** otherwise.

#### 3.5.4 Aliases (tiers) and the bank validator
- **Targets.** A fact's value targets in language L are its canonical value plus its aliases for L and for `en`. The same holds for `update.updated_value`. **Full authored sentences are never targets by default.**
- **Tier A (mechanical).**
  - `data/aliases/<bank stem>.aliases.v2.yaml` stores token-span references: `{field: surface | update.surface, lang, role: value | updated_value | relation_cue | subject_cue, start, end, expect}`.
  - The loader tokenizes the authored string with §3.5.2 and extracts tokens `[start, end)`. It refuses the file unless the extracted span equals `expect` (normalised), the span is 1–4 tokens within one sentence, value spans come from `surface`, updated-value spans come from `update.surface`, `tokenizer_version` matches, and the fact-bank sha256 matches.
- **Tier B.** Variants listed with ≥ 2 distinct annotators, a date, and `frozen: true`. Written blind to model outputs.
- **Tier C.** `added_by`, `date` and `reason` are required. Excluded from primary scores; used for sensitivity analysis only.
- **Bank validator** (`validate_contract_bank`; CLI `python -m xlmem.scripts.validate_facts --alias-bank …`):
  - every base fact has tier-A value and relation-cue spans in each surface language;
  - every entity-shift distractor has subject-cue spans;
  - no two base facts share a value target;
  - no relation cue serves two relations;
  - **no filler template contains any fact's value target.** This is required by the template guarantee.

#### 3.5.5 Subject attribution (per sentence)
Checked in order:
1. **AMBIGUOUS:** a user cue together with a distractor subject cue.
2. **DISTRACTOR:** a distractor subject cue.
3. **USER:** an explicit user cue. Possessives are excluded (`my`, `your`, `मेरी`, `aapki`, and an English user cue followed by `'s`).
4. **UNKNOWN:** a pronoun.
5. **No subject word:** USER **only under the template guarantee**, otherwise UNKNOWN. The guarantee holds when one of these is true:
   - the fact has no entity-shift distractor; or
   - the evidence is Snapshot A; or
   - the identical sentence (token tuple) occurs in Snapshot A; or
   - the text is a re-probe answer to the authored question about the user.

Distractor subject cues are the fact's entity-shift distractors' tier-A `subject_cue` spans.

#### 3.5.6 Relation status (per sentence)
- **CONFIRMED:** one of the fact's own tier-A relation cues is present.
- **CONFLICTING:** none of its own cues, but a relation cue of a fact with a *different* relation is present.
- **UNKNOWN:** otherwise.

Only authored cues are used; there is no general relation lexicon.

#### 3.5.7 Support status
- **A sentence SUPPORTS fact f** when all of these hold:
  - it has a value mention of f that is ASSERTED or AFFIRMED and not displaced;
  - the subject is USER (or DISTRACTOR, when scoring an entity-shift distractor);
  - the relation is not CONFLICTING.
  - It is *provisional* if the relation is UNKNOWN.
- **UNRESOLVED:** an AMBIGUOUS frame, or an AMBIGUOUS or UNKNOWN subject.
- **NOT_SUPPORTED:** NEGATED, the other subject, or CONFLICTING.
- **Record status:**
  - SUPPORTED-confirmed beats everything else.
  - Otherwise, a provisional SUPPORTED is kept only if **no sentence in the same record** carries contradictory evidence for f's value (any UNRESOLVED or NOT_SUPPORTED sentence for it). If one does, the record is UNRESOLVED.
  - Otherwise: UNRESOLVED > NOT_SUPPORTED > NONE.

#### 3.5.8 Metric policies
- **WF.**
  - Population: intended planted base facts (facts with a `plant` turn in the log; distractors excluded).
  - Written: some Snapshot A record SUPPORTS the fact.
  - Also reported: `wf_confirmed` (confirmed support only, a lower bound) and the provisional count.
  - Snapshot A missing → `null`.
- **XL-Recall@k (strict; k = 1, 3, 5).**
  - Eligible facts: the ones v3 WF says were written.
  - Hit: one of the top-k retrieved records SUPPORTS the fact. Denominator: eligible facts.
  - No `hit_strict` / `hit_lenient` fallback.
  - A record that SUPPORTS the fact's entity-shift distractor is not a hit; it counts toward `distractor_retrieval_at_k`.
- **SR / MR.**
  - The D6 eligibility rules (§2.4) apply unchanged, with the v3 WF write gate. For a non-`en` probe, tier-A/B value and updated-value targets in the probe language are required.
  - Outcome relative to the fact's old and corrected values:
    1. old ASSERTED or AFFIRMED → STALE;
    2. else old AMBIGUOUS → MISS;
    3. else new ASSERTED or AFFIRMED → UPDATED;
    4. else → MISS.
  - Mentions in a sentence whose subject is the distractor are ignored. An AMBIGUOUS or UNKNOWN subject makes a mention AMBIGUOUS.
  - `unresolved_count` = MISS outcomes caused by ambiguity.
- **plant DR.**
  - N(f) = distinct Snapshot A records that SUPPORT f. A record that merely contains the value doesn't count.
  - DR = Σ max(0, N(f) − 1) / |planted base facts|. Snapshot A missing → `null`.
- **FMR.**
  - Population: (base, distractor) pairs whose distractor turn actually occurs in the log.
  - FMR = events / pairs. Categories are decided per sentence, so a single-record store such as Letta's core block can still be SEPARATED.

  | Category | Entity-shift pair | Value-shift pair | Event |
  |---|---|---|---|
  | JOINT | a sentence states the value for both subjects, and the distractor is SUPPORTED nowhere | one sentence SUPPORTS both values | entity-shift: yes; value-shift: **no** (O3) |
  | WRONG_PERSON | the distractor is SUPPORTED nowhere, no sentence has its subject cue with the value, and a sentence absent from Snapshot A SUPPORTS the base fact with an explicit user cue | — | yes |
  | OVERWRITTEN | — | the base fact is SUPPORTED in Snapshot A, nowhere in the final store, and the distractor is SUPPORTED | yes |
  | SEPARATED | both SUPPORTED | both SUPPORTED | no |
  | UNRESOLVED | the distractor isn't SUPPORTED, and a new subject-UNKNOWN sentence has the value | ambiguous evidence | no (counted) |
  | BASE_LOST | the distractor is SUPPORTED, the base fact isn't | same | no |
  | LOST | otherwise | otherwise | no (distractor write failure) |

  A correct distractor fact used for the user's probe is a retrieval or answer error, not FMR.

#### 3.5.9 Unresolved and relation-unverified reporting (O6)
Every v3 `scores.json` has a `validation` block.

- `unresolved[metric] = {count, denominator, share}`:

  | Metric | Unresolved count | Denominator |
  |---|---|---|
  | WF | planted base facts whose best status is UNRESOLVED | planted base facts |
  | recall@k | eligible facts with no SUPPORTED top-k record but an UNRESOLVED one | eligible facts |
  | SR | ambiguity-caused MISS | eligible corrections |
  | DR | planted base facts with an UNRESOLVED Snapshot A record | planted base facts |
  | FMR | UNRESOLVED pairs | pairs |

- `relation_unverified` (provisional credit / credited items, for WF, recall@1 and DR) is reported **separately**, and never added to the unresolved share.
- `insufficient_validation[metric]` is set when the unresolved share exceeds **10%** (provisional threshold). **The score itself never changes.**

#### 3.5.10 Lenient tier
Suspended. No lenient column is reported in v3. A future lenient tier would be the local NLI judge, versioned separately and reported beside strict, never instead of it.

#### 3.5.11 Known limitations (report with any v3 number)
- **Relation:**
  - hometown vs current residence, and office location vs residence, are caught only when the record contains the *other* fact's authored relation cue;
  - otherwise the credit is provisional (relation UNKNOWN), and the relational audit measures how often that's wrong.
- **Transliterations:** model-made transliterations outside tier B are unmatched. They only enter through tier C, in sensitivity analysis.
- **Cue patterns:** the patterns are a short, fixed list (e.g. "Not peanuts — cashews" is MISS). Native-speaker validation of the cue lexicons and of the Hindi/Hinglish golden wordings is pending.
- **Pronoun subjects** ("He works at Infosys") are UNRESOLVED. Frameworks that write third-person memories will show high unresolved shares, which are flagged and not hidden.
- **D8:** DR and FMR have few positive candidates without restatement turns. Claims about their validation coverage wait for D8.

---

## 4. Hand-Computed Worked Example

Consider a mini-run of $N=5$ planted facts in Hindi (`hi`), probed in English (`en`), with $1$ distractor pair and $1$ correction:

### Planted Facts:
- $f_1$: `(user, allergic_to, peanuts)`
- $f_2$: `(user, lives_in, pune)`
- $f_3$: `(user, works_at, infosys)`
- $f_4$: `(user, speaks_language, marathi)`
- $f_5$: `(user, owns_pet, golden_retriever)`
- $f_{1,\text{dist}}$: `(user_sister, allergic_to, peanuts)`

### Step 1: Dump Inspection (Write Fidelity)
- Memory entries found in `dump()`:
  - Entry 1: "User has peanut allergy" $\to$ matches $f_1$
  - Entry 2: "User lives in Pune" $\to$ matches $f_2$
  - Entry 3: "User works at Infosys" $\to$ matches $f_3$
  - Entry 4: "User works at Infosys Bangalore" $\to$ duplicate match for $f_3$
  - Entry 5: "User has a dog" $\to$ matches $f_5$ (via NLI)
  - *(Notice $f_4$ "marathi" is missing from the store entirely!)*
- **Write Fidelity (WF):** $4 / 5 = 0.80$ ($80\%$). Fact $f_4$ failed at WRITE.
- **Duplication Rate (DR):** Fact $f_3$ has 2 entries; others have 1 or 0.
  $$\text{DR} = \frac{(1-1) + (1-1) + (2-1) + (0) + (1-1)}{5} = \frac{1}{5} = 0.20$$
- **False Merge Rate (FMR):** $f_1$ and $f_{1,\text{dist}}$ exist as separate records $\to \text{FMR} = 0 / 1 = 0.00$.

### Step 2: Retrieval Probing (XL-Recall@1 on facts written)
- Evaluated on written facts $\{f_1, f_2, f_3, f_5\}$:
  - Probe $f_1$: Retrieves Entry 1 $\to$ HIT (Strict & Lenient)
  - Probe $f_2$: Retrieves unrelated entry $\to$ MISS
  - Probe $f_3$: Retrieves Entry 3 $\to$ HIT (Strict & Lenient)
  - Probe $f_5$: Retrieves Entry 5 $\to$ HIT (Lenient only)
- **XL-Recall@1 (Strict):** $2 / 4 = 0.50$ ($50\%$)
- **XL-Recall@1 (Lenient):** $3 / 4 = 0.75$ ($75\%$)
- *(If $f_4$ had been wrongly counted as a retrieval failure, recall would be erroneously reported as $2/5 = 40\%$ and $3/5 = 60\%$. Write-first separation guarantees correct measurement.)*

### Step 3: Update & Re-probe
- Fact $f_2$ updated: "User moved from Pune to Mumbai".
- Re-probe: "Where does the user live now?"
- Response: "You live in Pune and Mumbai." (Contains stale value).
- $f_2$ has a correction turn and was written (Step 1), so it is eligible: $|\mathcal{F}_{\text{eligible}}| = 1$.
- "pune" and "mumbai" are both ASSERTED (the sentence has no cue word) → `STALE` (conflicted).
- **Staleness Rate (SR):** $1 / 1 = 1.00$ ($100\%$). **Miss Rate (MR):** $0 / 1 = 0.00$.
- (If the response had been "You live in Delhi.", the outcome would be `MISS`: SR $= 0.00$, MR $= 1.00$. Under v1 it was scored stale.)

---

## 5. Seed Aggregation and Variance Reporting

To ensure statistical significance and prevent cherry-picking:
1. Every experimental configuration is executed across $\ge 3$ random seeds (default: $\{11, 22, 33\}$).
2. For each metric $M$, compute sample mean $\bar{M}$ and sample standard deviation $s$:
   $$\bar{M} = \frac{1}{S} \sum_{s=1}^S M_s, \quad s = \sqrt{\frac{1}{S-1}\sum_{s=1}^S (M_s - \bar{M})^2}$$
3. All values in `results/` are formatted as:
   $$\bar{M} \pm s$$
4. **Single-seed reporting is strictly prohibited.** Any cell in a table without mean and variance over $\ge 3$ seeds is invalid.

---

## 6. Metric Version History

Each `scores.json` written by `xlmem/scripts/score.py` carries `metrics_version`. Files without the field are v1.

| Version | Date | Change | Decision record |
|---|---|---|---|
| v1 | 2026-09-17 | Initial definitions | — |
| **v2** | 2026-10-27 | **SR** redefined (§2.4, §3.3, §3.4): denominator = corrected and write-eligible facts with a valid re-probe; three outcomes UPDATED / STALE / MISS; separate MR and write-ineligible rate; authored Hindi aliases; deterministic negation handling; `null` when the evidence is insufficient. **Primary DR** becomes `plant_duplication_rate` (§2.2): Snapshot A, base facts only. The v1 `duplication_rate` is dropped from official scores. WF, recall, FMR, LTG and EA are unchanged. | D6, D7: `docs/STATUS_2026-10-18.md` (decision log) |
| **v2.1** | 2026-10-27 | **SR only.** (a) §3.3 item 6: an AFFIRMED old-value mention now counts toward STALE, as an ASSERTED one already did. v2.0 scored contrastive stale answers as MISS. (b) §2.4: re-probe validity is judged on raw records (well-formedness defined; a null or non-string `response` is invalid; a malformed record can't hide a duplicate; an unattributable malformed record → `null`, case (v)). Found by the read-only audit of 2026-10-27. MR, DR and every other metric are unchanged. | D6 (corrections within the approved definition) |
| **v3** | 2026-10-27 | **Matching contract MC-1** (§3.5): one shared Unicode-safe, whole-token foundation (nukta folding, language-scoped cue lexicons including Hinglish, longest match). Value matching is separated from support evidence (subject attribution with the template guarantee, relation status). Metric-specific policies for WF, recall, SR/MR, plant DR and FMR. Tier-A/B/C aliases in an alias bank v2. Unresolved and relation-unverified reporting with an insufficient-validation flag. Lenient column suspended. FMR population = injected distractors, with snapshot-aware categories. **Every metric is redefined.** | D1 (D1.1–D1.10, O1–O8) and D2 (Hinglish in scope): `docs/proposals/D1_MATCHING_CONTRACT.md` rev. 3; decision log in `docs/STATUS_2026-10-18.md` |

**Approval:** approved by the student on 2026-10-27. The guide delegated decisions D1–D7 to the student (as the student reported on 2026-10-18). Still open and **not** changed by v2: D1 (Hindi matching for WF and recall), D6b (correcting every fact with `update` data instead of the 20% subset), D8 (restatement turns).

**Defects in v1 that v2 fixes:**
- **SR**
  - The denominator counted facts that were never corrected (in the pilot, 3 instead of 1, so SR ≤ 0.33).
  - Every answer without the new value counted as stale, because `hit_strict` is always `False` in runner logs. Wrong answers were therefore update failures.
  - Answers were matched against the English values only, so correct Hindi answers counted as stale.
  - A negated old value ("not peanuts") counted as stale.
  - A missing per-fact re-probe counted as not stale.
- **DR:** distractor and correction records on the final store, plus distractors in the denominator, inflated DR. No pilot store held a real duplicate.

**Compatibility:**
- **v2.1 → v3:** no v3 value is comparable with any v1, v2 or v2.1 value. The v2.1 path stays available (`score.py --metrics-version 2.1`, `compute_seed_scores`). v3 rescores go to new directories (`scripts/rescore_metrics_v3.py`); existing outputs are never reinterpreted as v3.
- **v2.0 → v2.1:** the pilot v2 rescore (`runs/pilot_v2/rescore_metrics-v2/`, labelled `metrics_version: "2"`) was **not** rerun. The audit found no pilot answer with an AFFIRMED old-value mention and no malformed, duplicated or null re-probe record, so both v2.1 changes are expected to leave every pilot value as it is. That expectation has not been confirmed by a rescore.
- v1 and v2 SR and DR values are **not comparable** and must never share a table or an average.
- The pilot v2 runs were rescored offline under v2. The v1 values are kept unchanged in each `seed_*/scores.json`, indexed in `docs/rescore/pilot_v2_baseline_v1.json`.
- The comparison is in `docs/rescore/pilot_v2_v1_vs_v2.md`.
- No run needs to be repeated for v2: every input it uses (correction turn traces, `reprobe_result`, Snapshot A) is already in the logs.
