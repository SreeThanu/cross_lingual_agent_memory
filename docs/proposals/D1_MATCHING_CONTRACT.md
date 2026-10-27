# D1: Matching contract (MC-1, to become metrics v3)

**Status:** ADOPTED 2026-10-27, with D2 = Hinglish in scope. Implemented as metrics v3 on branch `scoring/matching-v3` (uncommitted). The normative text is now METRICS_SPEC §3.5. This document keeps the rationale, the cases and the golden examples.

**Implementation refinements** (each one required for a golden row below; recorded in METRICS_SPEC §3.5.3 and §3.5.8):
1. **O5 scope:** O5 applies to contrast- and NOW-affirmed mentions only. The "Y, not X" forms are exempt (row G-SR-2).
2. **NOW affirms:** a NOW cue right next to a mention affirms it (G-SR-8 and G-SR-19).
3. **Cue consumption:** a cue used by one mention's pattern doesn't make another mention ambiguous (G-SR-9).
4. **Cue pairs:** only the first token of a cue pair counts as an ambiguity cue.
5. **FMR:** the population is the distractors actually injected (the generator injects one per filler session); categories are decided per sentence; a BASE_LOST category is added.

**Revision history:** PROPOSAL, revision 3 (2026-10-27).
- All of D1's own decisions are now **adopted** (§5). O4 is adopted *conditionally on D2*.
- Nothing is implemented. METRICS_SPEC, the benchmark data and the experiment outputs are unchanged until v3 is implemented (§8).

**Supersedes as the D1 starting point:** `docs/proposals/HINDI_MATCHING.md` (branch `proposal/hindi-matching`).

**Affects measurement semantics:** WF, XL-Recall@k, LTG and EA (via recall), plant DR, FMR, and SR/MR. Adopting it means metrics v3 and an offline rescore of every run. No GPU re-run is needed.

**Revision 3 changes:**
- **O1–O8 decided** (amended as instructed).
- **Subject default (O2):** now bound to a template guarantee.
- **Cues (O4):** negation, contrast, past-tense and "now" cues are separate categories, and past-tense cues apply only in context.
- **Affirmed-then-negated (O5):** a conservative rule.
- **Thresholds (O6):** unresolved and relation-unverified are reported separately, with an insufficient-validation flag.
- **Tier-A spans (O7):** specified.
- **Validation design (O8):** specified.
- **Golden tests:** new ones for O3 and O5.
- **Implementation plan:** in §8.

---

## 1. Current D1 wording and the ambiguity it leaves

**D1 as logged** (`docs/STATUS_2026-10-18.md`): "How WF and strict recall match Hindi text (value aliases / transliteration / NLI tier)."

**The spec it would have to settle** (METRICS_SPEC §3.1): "The canonical value string *v* … **or authorized surface alias** in the probe language must appear as an exact token/substring within the retrieved memory or generated answer."

What that leaves open (each point observed with the current code):
1. **"Token/substring".** The code does both: a `\b` regex, then a raw-substring fallback. So `pune` matches "Punekar", `visa` matches "advisable" and `tea` matches "team".
2. **"Authorized surface alias" is never defined.** The code uses whole authored sentences, which favours stores that keep turns verbatim (A-MEM).
3. **Devanagari normalisation is unspecified.** `normalize_text` deletes vowel signs (`काजू` → `क ज`).
4. **A match on the value counts as a match on the fact.** Relation and subject are ignored:
   - "Currently lives in Jaipur" counts as *hometown*;
   - "Works at the Infosys Pune office" counts as *residence*;
   - the sister's allergy is a recall hit for the user;
   - "Does not live in Pune" counts as written.
5. **Two matchers exist:** SR v2.1's tokenizer and frames, and `strict_match` for everything else.
6. **Hinglish:** there are no romanized cues, so Hinglish corrections score STALE whatever they say.
7. **Affirmed then negated:** "…, but cashews are not listed" scores UPDATED.
8. **The lenient tier is specified but dead:** `hit_*` is always `False`.

## 2. What depends on matching

| Metric | Evidence matched | Today's matcher |
|---|---|---|
| WF (§2.1) | Snapshot A records ↔ planted fact | `strict_match`, value + full sentences |
| XL-Recall@k, LTG, EA (§2.3) | top-k retrieved records ↔ probed fact | same, plus the dead `hit_*` fallback |
| SR / MR (§2.4) and the SR write gate | re-probe answer ↔ the fact's old and corrected value; gate = WF | SR v2.1 matcher; the gate uses `strict_match` |
| plant DR (§2.2) | Snapshot A records ↔ each base fact (count) | `strict_match` |
| FMR (§2.2) | final-store records ↔ base fact and its distractor | `strict_match` on values and on entity words |

**Must be preserved (already approved):**
- The write-first rule.
- The D6 eligibility rules and the UPDATED/STALE/MISS outcomes.
- The D7 population (Snapshot A, planted base facts).
- Aliases are never derived from model outputs.
- No paid APIs, no LLM judge in scoring. The runner records and never judges. All model calls go through `xlmem/llm/client.py`.
- At least 3 seeds.

## 3. Cases

"Now" is the observed result of the current code. "MC-1" is the result under this contract. "Human" marks cases routed to adjudication.

| # | Text (vs fact) | Expected | Now | MC-1 | Why | Metrics |
|---|---|---|---|---|---|---|
| 1 | "LIVES IN PUNE!!" (lives_in pune) | support | ✓ | ✓ | case and punctuation | WF, recall, DR |
| 2 | "Allergic to peanut" (peanuts) | support | ✓ | ✓ provisional (relation UNKNOWN) | plural ±s; "allergic" isn't the authored cue "allergy" | WF, DR |
| 3 | "Resides in the city of Pune" | support | ✓ | ✓ provisional | no cue either way | WF, recall |
| 4 | "He is a proud Punekar" | no | ✗ | ✓ no | whole tokens | WF, recall, DR |
| 5 | "advisable" (visa), "team" (tea) | no | ✗ | ✓ no | whole tokens | WF, recall, DR |
| 6 | Snapshot A "Does not live in Pune" | no | ✗ | ✓ no (NEGATED) | negation | WF, DR, SR gate |
| 7 | Mem0 Hindi "वर्तमान में पुणे में रहता हूँ" | support | ✗ | ✓ CONFIRMED | tier-A `पुणे`, cue `रहता` | WF (Hindi), recall |
| 8 | "कजरी" vs `काजू` | no | n/a | ✓ no | vowel signs kept | Hindi, all |
| 9 | "गोल्डन रिट्रवर" vs authored "रिट्रीवर" | support if reviewed | ✗ | tier B only | spelling variant | WF, recall |
| 10 | "कैश्वर" (model-made Devanagari of an English value) | human | no | no + Human; tier C for sensitivity | open-ended | SR/MR, WF |
| 11 | Hinglish "mujhe peanuts se allergy hai" | support | ✓ | ✓ | English value token | all |
| 12 | Hinglish romanized value ("kaju") | support if in the `hi-en` surface | no | tier A from `hi-en` (needs D2) | romanized Hindi is its own target language | all, hi-en |
| 13 | "Currently lives in Jaipur" (hometown) | no | ✗ | ✓ no (CONFLICTING: `live` is lives_in's cue) | another fact's cue, not this fact's | WF |
| 13b | "Jaipur is where I stay now" (hometown) | no | ✗ | ✗ provisional (UNKNOWN) → Human | no cue either way | WF |
| 14 | "Works at the Infosys Pune office" (lives_in pune) | no | ✗ | ✓ no (CONFLICTING: `work`) | as 13 | WF, DR |
| 14b | "Pune office, near home" (lives_in pune) | no | ✗ | ✗ provisional → Human | as 13b | WF, DR |
| 15 | "My sister has an allergy to peanuts" (user's allergy) | no | ✗ hit | ✓ no (subject = DISTRACTOR) | subject cue | recall, FMR |
| 16 | "My sister and I are both allergic to peanuts" | joint | — | subject AMBIGUOUS → no credit; FMR JOINT | two subjects | recall, FMR |
| 17 | "She is allergic to peanuts" | unknown subject | ✓ | subject UNKNOWN → Human | pronoun | WF, recall |
| 18 | Final store, new subjectless "Allergic to peanuts" (fact with a sister distractor) | unknown | ✓ | subject UNKNOWN → UNRESOLVED | no template guarantee after the distractor turns (O2) | recall, FMR |
| 19 | Snapshot A "Lives in Pune" + "Currently resides in Pune" | 2 records | 2 | 2 | real duplicate | DR |
| 20 | "non-vegetarian" vs `vegetarian` | no | ✗ | ✓ no | longest match wins | all |
| 21 | "फ़िल्टर कॉफ़ी" vs "फिल्टर कॉफी" | support | inconsistent | ✓ | nukta folding | Hindi, all |
| 22 | A-MEM raw turn "मुझे मूंगफली से गंभीर एलर्जी है।" | support | ✓ via the whole sentence | ✓ via `मूंगफली` + `एलर्जी` | no extra credit for storing verbatim | WF |
| 23 | Abstract value `flu_shot_pending` | support for "flu shot" | verbatim only | ✓ via tier A | a key isn't text | WF, recall |

## 4. The contract

### 4.1 Layers and principle
1. **Foundation (shared):** normalisation, tokens, sentences, cue categories, targets, and mentions with frames.
2. **Value match:** a mention of one of the fact's value targets. A match alone never earns credit.
3. **Support evidence:** `Support = {status: SUPPORTED | NOT_SUPPORTED | UNRESOLVED, provisional: bool, value_mention, frame, subject, relation, reasons}`.
4. **Metric policies (§4.8).**

**Principle.** Insufficient evidence earns neither credit nor penalty. UNRESOLVED evidence is never counted as a write, a hit, a duplicate, a merge or a staleness event. It is counted and reported (§4.9).

The module is `xlmem/scoring/matching.py`. It replaces `judge.strict_match` for v3, and SR's tokenizer and frames move into it. `judge.strict_match` stays only so v1, v2 and v2.1 numbers can be reproduced.

### 4.2 Foundation
- **Normalisation:** NFC, `casefold()`, `_` → space, nukta (U+093C) folded.
- **Tokens:** maximal runs of letters, combining marks and digits (L\*, M\*, Nd).
- **Sentences:** break on `. ! ? । ॥ ;` and newline.
- **Matching:** **no substring matching anywhere**. A target matches only as contiguous whole tokens.
  - English plural: ±`s` on the last ASCII token of a target. No other stemming.
  - Mixed-script tokens match nothing.
- **Longest match wins:** a mention contained in a longer mention of any other bank target, in the same sentence, is displaced.
- **Cue categories.** Cues are separate categories, scoped by language. A cue only acts within its language's lexicon. `hi-en` is active only if D2 puts Hinglish in scope.

  | Category | en | hi | hi-en (conditional on D2) |
  |---|---|---|---|
  | NEG (negation) | not, no, never | नहीं, मत | nahi, nahin |
  | NEG pair before | instead of, rather than | न कि | na ki |
  | CONTRAST | but | बल्कि | balki |
  | PAST | used to, was, were, previously, earlier, formerly | पहले, था, थी, थे | pehle, tha, thi (`the` excluded: it clashes with the English article) |
  | NOW | now, currently | अब, फ़िलहाल | ab, abhi |
  | Other ambiguity cues | nor, neither, however, although, though, longer, t | लेकिन, परंतु, किंतु | lekin, magar |

### 4.3 Frames (the four frames are kept; how they are assigned is refined)
The checks run in this order, within one sentence.

1. **AFFIRMED:**
   - a CONTRAST cue among the 2 tokens before the mention, with no NEG cue between it and the mention; **or**
   - `instead`, or `not` / `न कि` / `na ki`, after the mention (the v2.1 forms).
   - **O5:** an AFFIRMED candidate becomes **AMBIGUOUS** if a NEG cue occurs within the 3 tokens *after* the mention, in the same sentence. Example: "but cashews are **not** listed". Then the statement doesn't establish the current value.
2. **NEGATED:**
   - a NEG cue among the 3 tokens before (en);
   - `नहीं` / `nahi` among the 2 tokens after (hi, hi-en);
   - a NEG pair right before;
   - `बजाय` among the 2 tokens after.
3. **PAST, resolved in context (O4).** A PAST cue in the v2.1 window does **not** negate on its own. The mention is NEGATED (superseded) only if the same text unit (the record, or the re-probe answer) also contains a NOW cue, or an ASSERTED/AFFIRMED mention of a *different* value of the same fact. Otherwise it is **AMBIGUOUS**.
   - "Pehle peanuts se allergy thi, ab cashews se hai" → peanuts NEGATED.
   - "You were allergic to peanuts." → AMBIGUOUS.
4. **AMBIGUOUS:** the sentence holds any cue from the language's lexicon, but no rule above covers the mention.
5. **ASSERTED:** everything else.

**Effect on en/hi compared with v2.1:** SR outcomes are unchanged in every golden case. A PAST-only mention moves from NEGATED to AMBIGUOUS. In stores, this changes NOT_SUPPORTED into UNRESOLVED, which is reported.

### 4.4 Alias and cue spans (tiers; O7)
A fact's targets in language L are its canonical value plus its aliases for L. Full authored sentences are never targets by default; a sentence can only be a tier-B entry, reviewed and justified.

| Tier | Definition | How it's produced | Used in |
|---|---|---|---|
| **A, mechanically derived** | a token span extracted by the loader from authored text | span references in the sidecar (below) | primary |
| **B, reviewed variant** | spelling variants and conventional transliterations | two bilingual annotators, from fact cards that show only authored text, **before** they see any model output. Adjudicated, then frozen with provenance | primary |
| **C, post hoc** | anything added after model outputs were seen | logged | sensitivity analysis only, never primary |

**Tier-A span reference (O7):** `{fact_id, field: surface | update.surface, lang, role: value | updated_value | relation_cue | subject_cue, token_start, token_end, expect}`.
- **Normalisation:** the loader tokenizes the authored string with the §4.2 tokenizer (NFC, casefold, nukta fold, L/M/Nd runs) and extracts tokens `[token_start, token_end)`, joined by single spaces.
- **Validation (the loader refuses if any check fails):**
  - the fact-bank sha256 matches the sidecar's;
  - the indices are in range, with `start < end` and a length ≤ 4 tokens;
  - the span lies within one sentence;
  - the extracted text equals `expect`, which catches index drift if the tokenizer changes;
  - the sidecar's `tokenizer_version` matches the code. A tokenizer change requires regenerating the spans and bumping the metrics version.
- The span is whole tokens by construction, so part-word aliases are impossible.

**Bank validator:**
- every base fact has a tier-A `value` span, and a `relation_cue` span, in each surface language;
- every entity-shift distractor has a `subject_cue` span;
- no two base facts share a value target;
- **filler turns contain no fact value target.** This is required by the template guarantee (§4.5).

### 4.5 Subject attribution (O2)
**User subject cues** are a fixed, versioned list:
- in records: `i`, `user`, `मैं`, `मुझे`, `मुझको`, `main`, `mujhe`;
- in answers: `you`, `आप`, `आपको`, `तुम`, `तुम्हें`, `aap`, `aapko`, `tum`, `tumhe`.

Possessives (`my`, `your`, `मेरी`, `आपकी`, `meri`, `aapki`) are excluded.

**Pronoun cues:** `he`, `she`, `they`, `him`, `her`, `वह`, `वो`, `उसे`, `उसको`, `woh`.

**Distractor subject cues:** tier-A spans (e.g. `sister`, `बहन`).

Per sentence, for fact f, checked in order:
1. **AMBIGUOUS:** a user cue together with a distractor cue (a joint statement).
2. **DISTRACTOR:** a distractor cue.
3. **USER:** an explicit user cue.
4. **UNKNOWN:** a pronoun cue.
5. **No subject word:** USER **only where the benchmark template guarantees it**. Otherwise UNKNOWN. The guarantee holds when one of these is true:
   - f has **no entity-shift distractor**. Then nothing in the session script attributes f's value to anyone else, because the validator checks filler turns;
   - the evidence is in **Snapshot A**, which precedes every distractor turn;
   - the sentence's normalised text also occurs, verbatim, as a sentence in Snapshot A. It existed before any distractor turn. This is a text comparison, never framework metadata;
   - the text is a **re-probe answer**, which answers an authored question about the user.

Subject AMBIGUOUS or UNKNOWN → the support is UNRESOLVED.

**False-positive tests required:**
- "My sister has an allergy to peanuts" → DISTRACTOR, never USER.
- "मेरी बहन को मूंगफली से एलर्जी है" → DISTRACTOR.
- "Sister visited me; I am allergic to peanuts" → the `;` splits it into two sentences, so the second is USER.
- An unrelated "sister" sentence doesn't affect a fact without an entity-shift distractor.
- A filler turn containing a value is caught by the validator.

### 4.6 Relation status (O1)
Each supporting sentence has a relation status:
- **CONFIRMED:** one of the fact's own authored relation cues is present.
- **CONFLICTING:** none of its own cues, but another base fact's relation cue is present.
- **UNKNOWN:** neither.

| Deterministic matcher can classify | Requires human adjudication |
|---|---|
| value present or absent (tiers A and B) | relation correctness when the status is UNKNOWN (cases 13b, 14b) |
| frames from the listed cue patterns | subject UNKNOWN or AMBIGUOUS (pronouns, subjectless text without the guarantee) |
| distractor subject cues, explicit user cues, the template guarantee | transliterations outside tier B |
| CONFLICTING, when the conflicting cue is authored | negation or tense outside the listed patterns |
| CONFIRMED | values with no value token ("the nut kind") |
| displacement | joint statements whose truth for each subject is unclear |

**Known limitations:**
- **Hometown vs current residence:** caught only when the record contains lives_in's authored cue (`live` / `रहता` / `rehta`). "Jaipur is where I stay now" stays UNKNOWN and earns provisional credit.
- **Office location vs residence:** caught only when the record contains works_at's cue (`work` / `काम` / `kaam`). "Pune office, near home" stays UNKNOWN.
- Both are measured by the relational audit (§6), not assumed away.

### 4.7 Support status
A sentence **SUPPORTS** fact f when all of these hold:
- it has a value mention of f that is ASSERTED or AFFIRMED and not displaced;
- the subject is USER (or DISTRACTOR, when scoring the distractor);
- the relation is not CONFLICTING.

**Provisional credit (O1):** the relation is UNKNOWN, and there is **no contradictory evidence anywhere in the same record**. Contradictory evidence means a NEGATED or AMBIGUOUS mention of f's value, a CONFLICTING sentence for the same value, or a DISTRACTOR or AMBIGUOUS subject for the same value.

**UNRESOLVED:**
- the mention frame is AMBIGUOUS; or
- the subject is AMBIGUOUS or UNKNOWN; or
- a provisional candidate has contradictory evidence elsewhere in the record; or
- the record's language has no target.

**NOT_SUPPORTED:** no value, NEGATED, displaced, DISTRACTOR subject (when scoring f), or CONFLICTING.

A record's status for f is the best status among its sentences, in the order SUPPORTED (confirmed) > SUPPORTED (provisional) > UNRESOLVED > NOT_SUPPORTED.

### 4.8 Metric policies (v3)
- **WF.**
  - Population: intended planted base facts (facts with a `plant` turn; distractors excluded).
  - f is written if a Snapshot A record SUPPORTS f.
  - Reported: WF; `wf_confirmed` (credit from CONFIRMED records only, a lower bound); `provisional_count`; the unresolved count and share.
- **XL-Recall@k (strict semantics kept).**
  - Eligible facts: the ones WF says were written. A hit if a top-k retrieved record SUPPORTS f, using the probe language's targets plus the English canonical values. Denominator = eligible facts. k ∈ {1, 3, 5}.
  - A record SUPPORTING f's distractor is not a hit; it counts toward `distractor_retrieval_rate`.
  - **No `hit_*` fallback.**
  - Reported: provisional hits and unresolved top-k, separately.
- **SR / MR.**
  - The outcome is judged relative to this fact's old and corrected values (v2.1 rules):
    1. old value ASSERTED or AFFIRMED → STALE;
    2. else old value AMBIGUOUS → MISS;
    3. else new value ASSERTED or AFFIRMED → UPDATED;
    4. else → MISS.
  - The frames come from §4.3, including O4 and O5.
  - The subject check is applied (the template guarantee holds for answers): an answer whose subject is the distractor → MISS.
  - The write gate uses v3 WF. Only full (non-provisional) or provisional credit opens the gate. Gating on provisional credit is reported.
  - **unresolved** = MISS outcomes caused by an AMBIGUOUS frame or subject (as opposed to a plain absence of the value).
- **plant DR.**
  - N(f) = distinct Snapshot A records that SUPPORT f (confirmed or provisional). Records that only contain the value don't count.
  - Reported: `unresolved_duplicate_candidates` and `provisional_duplicate_count`.
- **FMR (final store, per distractor pair; one category each, checked in this order):**

  | Category | Entity-shift (user vs sister, same value) | Value-shift (same subject, different value) | Event? |
  |---|---|---|---|
  | JOINT | a sentence states the value for both subjects (subject AMBIGUOUS) and no separate record SUPPORTS d | one record SUPPORTS both values | entity-shift: **yes**; value-shift: **no**, not automatically a false merge (O3) |
  | WRONG_PERSON | d is SUPPORTED nowhere and no sentence has d's subject cue with the value, **and** a sentence absent from Snapshot A SUPPORTS f with an **explicit** user cue | — | **yes** |
  | OVERWRITTEN | — | f was SUPPORTED in Snapshot A, is SUPPORTED nowhere in B, and d is SUPPORTED | **yes** |
  | SEPARATED | f and d each SUPPORTED by different records | f and d each SUPPORTED, separately or jointly | no |
  | UNRESOLVED | d not SUPPORTED, and a new subjectless or pronoun sentence with the value exists (subject UNKNOWN) | AMBIGUOUS frames | no; counted |
  | LOST | d never SUPPORTED, and nothing above applies | d never SUPPORTED, f intact | no; reported as the distractor write rate |

  - FMR = events / pairs.
  - A correct sister fact that is retrieved for, or used in, the user's question is a retrieval or answer error (`distractor_retrieval_rate`, or MISS), **not** FMR.
- **Ambiguity everywhere:** UNRESOLVED is excluded from numerators and reported (§4.9).

### 4.9 Unresolved and relation-unverified reporting (O6)
For each seed and metric, the unresolved share = unresolved items / that metric's denominator:

| Metric | Unresolved items | Denominator |
|---|---|---|
| WF | planted base facts whose best status is UNRESOLVED | planted base facts |
| Recall@k | eligible facts with no SUPPORTED top-k record but at least one UNRESOLVED one | eligible facts |
| SR | eligible corrections whose MISS is caused by AMBIGUOUS frame or subject | eligible corrections |
| DR | planted base facts with ≥ 1 UNRESOLVED duplicate candidate | planted base facts |
| FMR | pairs classified UNRESOLVED | distractor pairs |

- **Relation-unverified is reported separately:** provisional credits / credited items (WF writes, recall hits, DR records). It is never added to the unresolved share.
- **Threshold (provisional):** unresolved share > **10%** sets `insufficient_validation[metric] = "<share> unresolved > 10%"` for that seed. **The score is unchanged.**
- **Aggregates:** report the number of flagged seeds per run. A flagged run is marked insufficiently validated in every table.

### 4.10 Lenient tier
- The `hit_*` fallback is removed from the primary path.
- The lenient column is suspended until it has a defined purpose and has been validated independently. METRICS_SPEC §3's "report both" is suspended, and the reason is recorded.
- If one is adopted later, it is the local NLI judge, run offline with a pinned model, versioned separately, and reported beside strict. It is never an LLM judge, and never goes through the runner.

## 5. Decisions (all adopted by the student, 2026-10-27)

| # | Decision |
|---|---|
| D1.1 | One shared foundation (§4.2–§4.3), with explicit per-metric support policies (§4.8). Value matching ≠ support evidence. Insufficient evidence earns no credit and no penalty. It is counted. |
| D1.2 | Full authored sentences are not aliases by default. |
| D1.3 | Three alias tiers. A is mechanically extracted (§4.4). B is written blind to model outputs, then frozen. C is for sensitivity analysis only. |
| D1.4 | The four frames are kept. Outcomes are relative to the fact's old and corrected values. Cue categories are separate, and PAST applies only in context (O4). Affirmed-then-negated → AMBIGUOUS, which gives a conservative MISS (O5). |
| D1.5 | A unique value doesn't prove the relation. The tri-state relation status, with provisional credit only for UNKNOWN without contradiction (O1). Explicit subject cues; a subjectless sentence is USER only under the template guarantee, otherwise UNKNOWN (O2). Known limitations and the human-adjudicated cases are listed (§4.6). |
| D1.6 | WF scores the intended planted base facts; distractors are excluded from the denominator. |
| D1.7 | DR counts a record only when it SUPPORTS the same planted fact. |
| D1.8 | FMR uses authored subject cues. Wrong-person attribution (snapshot-based) is an event. A correct sister fact used for the user is not FMR. A value-shift JOINT is not automatically a false merge (O3). Ambiguous → UNRESOLVED. |
| D1.9 | No `hit_*` fallback. The lenient column is suspended. Strict recall semantics are kept. |
| D1.10 | Validation per §6. κ ≥ 0.70 and scorer recall ≥ 0.80 are **targets, not guarantees**. A metric that fails is flagged as insufficiently validated and isn't used for comparative claims until resolved. It is never silently replaced by a human estimate. The 10% unresolved flag (O6) works the same way. |
| O1 | Adopted: CONFIRMED / UNKNOWN / CONFLICTING. Provisional credit only for value match + UNKNOWN + no contradictory evidence. Reported separately. CONFLICTING earns no credit. |
| O2 | Adopted, amended: no subject word → USER only under the template guarantee (§4.5); otherwise UNKNOWN. |
| O3 | Adopted: value-shift JOINT is not automatically an event; WRONG_PERSON is snapshot-based; golden cases G-FMR-1 to G-FMR-7. |
| O4 | **Conditionally adopted (D2):** separate categories NEG, CONTRAST, PAST, NOW. `pehle`, `tha` and `thi` are PAST, never NEG, and resolved in context. PAST is in context for en/hi as well. |
| O5 | Adopted: an AFFIRMED mention followed within 3 tokens by a NEG cue → AMBIGUOUS → MISS, unless other evidence settles the outcome. Golden cases G-SR-12 to G-SR-17. |
| O6 | Adopted: 10% per-seed unresolved threshold (provisional); denominators in §4.9; relation-unverified reported separately; the flag never changes the score. |
| O7 | Adopted: token-span tier A, normalised and validated as in §4.4. |
| O8 | Adopted: §6. |

## 6. Independent Hindi/Hinglish validation (O8)
- **Direction classes** (store → probe):
  - EN-same (en→en)
  - HI-same (hi→hi)
  - EN→HI (en→hi)
  - HI→EN (hi→en)
  - **conditional on D2:** HIEN-same (hi-en→hi-en), and HIEN-cross (hi-en ↔ en/hi), pooled unless the population allows a split.
- **Metric families:** WF (record × fact), recall (top-k record × fact), SR (re-probe answer), DR (duplicate candidates), FMR (pairs).
- **Pilot:** a full review of every Hindi and Hinglish pilot item. That's the 36 re-probe answers, all Snapshot A records of the 24 Hindi-stored seeds, the 8 known disagreements, and the FMR pairs of those seeds.
- **Main runs:** a target of ≥ 300 items per family per direction class. If the population is smaller, take all of it and report that. Note that DR and FMR positives may be scarce: see D8 (§8.4).
- **Sampling:**
  - stratified random sampling within each (family, class) cell;
  - strata = framework × scorer status (SUPPORTED-confirmed, SUPPORTED-provisional, UNRESOLVED, NOT_SUPPORTED; or UPDATED / STALE / MISS; or the FMR category);
  - SUPPORTED, UNRESOLVED and minority outcomes are oversampled;
  - the sampling weights are recorded so precision and recall can be weighted by population;
  - the sampling script is deterministic (fixed seed), committed, and run once, before labelling.
- **Annotation:**
  - two bilingual annotators (native Hindi, fluent English; Hinglish experience required for the hi-en classes), working independently;
  - not authors of the matcher, and blind to framework, condition and scorer output;
  - written guidelines mirror §4: subject, relation, frame and outcome labels;
  - tier-B elicitation and freezing come first, from fact cards only.
- **Adjudication:**
  - κ (or Krippendorff's α) is computed on the raw independent labels;
  - disagreements go to a third adjudicator, whose label is the reference;
  - all raw labels and adjudication notes are kept.
- **Reported for each cell:**
  - population size, sampled, labelled, excluded (with reasons), adjudicated;
  - κ with a bootstrap 95% CI;
  - scorer precision and recall against the reference, with Wilson 95% CIs (population-weighted);
  - the relation-error rate (provisional credits labelled wrong-relation; also among CONFIRMED);
  - the unresolved share.
- **Targets, not guarantees:** κ ≥ 0.70 and scorer recall ≥ 0.80. A cell below target is flagged as insufficiently validated, is not used for comparative claims, and its cause is fixed (guidelines, tier-B gap, or a contract rule with a version bump and full rescore) before it is re-validated. Human estimates are reported as evidence only.
- **Freeze:** v3, tier B and the cue lexicons are frozen before P3.

## 7. Golden examples (hand-computed; these become `tests/golden/test_matching_v3.py`)

**Bank G (base facts):**

| Fact | Subject | Relation | Value | Relation cue (en / hi / hi-en) |
|---|---|---|---|---|
| g1 | user | allergic_to | peanuts → corrected to cashews | `allergy` / `एलर्जी` / `allergy` |
| g2 | user | lives_in | pune | `live` / `रहता` / `rehta` |
| g3 | user | hometown | jaipur | `hometown` / `गृहनगर` / `hometown` |
| g4 | user | works_at | infosys → corrected to tcs | `work` / `काम` / `kaam` |
| v1 | user | diet | vegetarian | `diet` / `आहार` / `diet` |

**Distractors:**
- **g1d** (user_sister, allergic_to, peanuts): entity-shift distractor of g1, subject cues `sister` / `बहन`.
- **v1d** (user, diet, gluten_free): value-shift distractor of v1, alias `gluten free`.

**Tier-A hi aliases:** `मूंगफली`, `काजू`, `पुणे`, `जयपुर`, `इंफोसिस`, `टीसीएस`.

### G-WF / G-DR: Snapshot A (base facts g1–g4; v1 absent from this seed)
- A1 "Has a severe allergy to peanuts"
- A2 "Allergic to peanuts"
- A3 "Currently lives in Jaipur"
- A4 "Works at the Infosys Pune office"
- A5 "Does not live in Pune"

| Record → fact | Frame | Subject | Relation | Support |
|---|---|---|---|---|
| A1 → g1 | ASSERTED | USER (Snapshot A guarantee) | CONFIRMED | SUPPORTED |
| A2 → g1 | ASSERTED | USER | UNKNOWN; no contradiction in A2 | SUPPORTED, provisional |
| A3 → g3 | ASSERTED | USER | CONFLICTING (`live`) | NOT_SUPPORTED |
| A4 → g4 | ASSERTED | USER | CONFIRMED (`works`) | SUPPORTED |
| A4 → g2 | ASSERTED | USER | CONFLICTING (`work`) | NOT_SUPPORTED |
| A5 → g2 | NEGATED | — | — | NOT_SUPPORTED |

**Results:**
- **WF** = 2/4 = **0.50**; `wf_confirmed` = 2/4 (g1 also has A1); provisional credits = 1 (A2); unresolved 0/4.
- **plant DR** = (g1: 2−1) / 4 = **0.25**; provisional_duplicate_count = 1.
- **Current code:** WF 1.00, DR 0.50 (verified).

### G-R: recall (eligible = {g1, g4})
- g1, top-3:
  1. "My sister has an allergy to peanuts" → DISTRACTOR; counts toward distractor retrieval.
  2. "Has a severe allergy to peanuts" → also in Snapshot A, so the guarantee holds → SUPPORTED.
  3. "Lives in Pune".
- g4, top-1: "Works at the Infosys Pune office" → SUPPORTED.

**Results:**
- **R@1** = 1/2 = **0.50**; **R@3** = **1.00**; distractor_retrieval@1 = 1/2.
- **Current code:** R@1 = R@3 = 1.00 (verified).
- **Variant G-R-2:** g1's top-1 is a *new* subjectless "Allergic to peanuts" (not in Snapshot A). Subject UNKNOWN → UNRESOLVED. R@1 = 1/2, and recall's unresolved share = 1/2 → flagged under O6.

### G-SR: re-probe outcomes for g1 (old peanuts, new cashews)

| # | Language | Answer | Expected (MC-1) | Current v2.1 (run) |
|---|---|---|---|---|
| 1 | en | "You are allergic to cashews now." | UPDATED | UPDATED |
| 2 | en | "You are allergic to peanuts, not cashews." | STALE | STALE |
| 3 | en | "You used to be allergic to peanuts. Now you are allergic to cashews." | UPDATED (PAST + NOW in context) | UPDATED |
| 3b | en | "You used to be allergic to peanuts, but now it is cashews." | MISS (`cashews` AMBIGUOUS; conservative) | MISS |
| 4 | en | "You are allergic to carrots." | MISS | MISS |
| 5 | en | "Your sister is allergic to peanuts." | MISS (subject = distractor) | STALE |
| 6 | hi | "आपको मूंगफली से नहीं, बल्कि काजू से एलर्जी है।" | UPDATED | UPDATED |
| 7 | hi | "आपको मूंगफली से एलर्जी है, न कि काजू से।" | STALE | STALE |
| 8 | hi-en | "Aapko ab cashews se allergy hai, peanuts se nahi." | UPDATED (D2) | STALE |
| 9 | hi-en | "Aapko peanuts se allergy hai, cashews se nahi." | STALE | STALE |
| 10 | hi-en | "Peanuts nahi, balki cashews." | UPDATED (D2) | STALE |
| 11 | en | "Not peanuts — cashews." | MISS (known limitation: `not` is within 3 tokens before `cashews`) | MISS |
| 12 | en | "Not peanuts, but cashews." | UPDATED | UPDATED |
| 13 | en | "Not peanuts, but cashews are not confirmed either." | **MISS** (O5) | UPDATED |
| 14 | en | "I don't know, but cashews are not listed." | **MISS** (O5) | UPDATED |
| 15 | hi | "मूंगफली से नहीं, बल्कि काजू से एलर्जी है।" | UPDATED | UPDATED |
| 16 | hi | "मूंगफली से नहीं, बल्कि काजू से भी नहीं है।" | **MISS** (O5) | UPDATED |
| 17 | hi-en | "Peanuts nahi, balki cashews se allergy hai." | UPDATED (D2) | STALE |
| 17b | hi-en | "Peanuts nahi, balki cashews se bhi nahi." | **MISS** (O5, D2) | STALE |
| 18 | hi-en | "Pehle peanuts se allergy thi." | MISS (PAST without a NOW cue → AMBIGUOUS; never NEG) | STALE |
| 19 | hi-en | "Pehle peanuts se allergy thi, ab cashews se hai." | UPDATED (PAST + `ab`) | STALE |
| 20 | en | "You were allergic to peanuts." | MISS (PAST without context → AMBIGUOUS) | MISS (via NEGATED) |

- Every "Current v2.1" cell was produced by running `classify_reprobe` on 2026-10-27.
- The Hindi and Hinglish wordings (rows 6–10 and 15–19) need bilingual validation before they are frozen.

**Aggregate seed G-SR-agg** (corrections g1, g2, g4):
- **Answers:** row 2 for g1; "You now work at TCS." for g4 (UPDATED); "You live in Mumbai now." for g2.
- **MC-1:** g2 is write-ineligible (not written in G-WF). **SR = 1/2, MR = 0/2, write-ineligible rate = 1/3**, unresolved 0/2.
- **Current code:** SR = 1/3.

### G-FMR: final store (Snapshot A for g1 = {A1})

| # | Pair | Store B (sentences) | Category | Event | Current FMR |
|---|---|---|---|---|---|
| 1 | g1/g1d | A1 + "My sister has an allergy to peanuts" | SEPARATED (correct sister fact) | no | 0.0 |
| 2 | g1/g1d | A1 + "User and sister are both allergic to peanuts" | JOINT (entity-shift) | **yes** | 1.0 |
| 3 | g1/g1d | A1 + "I am allergic to peanuts" (new, explicit user cue), no sister sentence | WRONG_PERSON (sister's fact attributed to the user) | **yes** | 0.0 |
| 4 | g1/g1d | A1 + "Allergic to peanuts" (new, no subject word), no sister sentence | UNRESOLVED (subject UNKNOWN; no guarantee) | no; unresolved 1/1 → flagged | 0.0 |
| 5 | g1/g1d | A1 only | LOST | no; distractor write rate 0 | 0.0 |
| 6 | v1/v1d | Snapshot A "Is vegetarian"; B "Follows a vegetarian, gluten-free diet" | JOINT (value-shift) → SEPARATED-equivalent | **no** (O3) | 1.0 (value-shift: both values in one record) |
| 7 | v1/v1d | Snapshot A "Is vegetarian"; B "Follows a gluten-free diet" only | OVERWRITTEN | **yes** | 0.0 |

Every "Current FMR" cell was produced by running `compute_false_merge_rate` on 2026-10-27. Rows 6 and 7 show the two v2.1 errors that O3 fixes: a legitimate joint record counted as a merge, and a real overwrite missed.

## 8. Implementation plan (migration to metrics v3)

### 8.0 Before starting
- Commit the v2.1 work now in the working tree (with the user's approval), so v3 starts from a recorded baseline and v2.1 stays reproducible by commit.
- Then branch `scoring/matching-v3`.

### 8.1 Shared matching foundation: `xlmem/scoring/matching.py` (pure, no I/O)
1. `normalize`, `tokenize` (with nukta fold), `split_sentences`, and the `TOKENIZER_VERSION` constant.
2. `CueLexicon` per language (`en`, `hi`, `hi-en` gated by a config flag that follows D2), with categories NEG, NEG-pair, CONTRAST, PAST, NOW, ambiguity, user subject (record/answer), pronoun.
3. `targets()`, `mentions()`, displacement, and `frame()`: §4.3 including the O4 past-context rule and the O5 rule.
4. Move SR's v2.1 code into the module. `staleness.py` keeps `compute_staleness_v2` (frozen, for reproduction) and gains `compute_staleness_v3`.

### 8.2 Metric-specific support policies
1. `subject()` with the template-guarantee inputs: whether the fact has an entity-shift distractor, the evidence phase, and the set of Snapshot A sentences. `relation_status()`. `support()` → `Support`.
2. `wf_v3`, `recall_v3`, `sr_v3` (D6 eligibility unchanged), `plant_dr_v3`, `fmr_v3` (with categories), each returning a score, counts, unresolved, provisional and per-item evidence.
3. The §4.9 reporter: unresolved shares, relation-unverified shares, and `insufficient_validation` flags. Scores are never altered.

### 8.3 Schema and aliases
1. Sidecar v2: `data/aliases/facts_v1.aliases.v2.yaml`. The v1 sidecar is kept for v2.1.
   - Fields: `tokenizer_version`, `fact_bank_sha256`, tier-A span references (value, updated_value, relation_cue, subject_cue), tier-B and tier-C lists with provenance (annotators, date, frozen flag).
2. Loader validation (§4.4) and bank validator checks (§4.4, including "filler turns contain no value target").
3. Author tier-A spans for the 20 `facts_v1` facts in `en` and `hi` (and `hi-en` if D2 says so). The ~230 candidate facts get spans during the bilingual review.

### 8.4 Dependencies (not decided here)
- **D2 (Hinglish in scope?)**
  - gates the `hi-en` lexicon (O4), `hi-en` tier-A spans, the HIEN validation classes, and golden rows 8, 10, 17, 17b, 18 and 19 (marked `skip` until D2);
  - if Hinglish is out of scope, `hi-en` probes stay `missing_or_invalid` for SR, as in v2.1.
- **D6b (correct every fact with update data?)**
  - doesn't change any v3 rule;
  - it sets how many corrections exist: at a 20% subset, the SR family may fall short of 300 items per direction class in P3, and the shortfall is reported, not padded;
  - it also changes BENCHMARK_SPEC §5 and the generator, outside this plan.
- **D8 (restatement turns?)**
  - DR and FMR have structurally few positive candidates without restatements, so their ≥ 300 validation targets may be unreachable, and the shortfall would be reported;
  - if D8 adds restatements *after* Snapshot A, primary DR (Snapshot A by D7) won't see them. D8 would then also have to settle which snapshot DR uses, and how the template guarantee (§4.5) applies to restated text.

### 8.5 Golden and regression tests
1. `tests/golden/test_matching_v3.py`: every §3 case and every §7 row, with hand-computed values. D2-dependent rows are skipped.
2. Subject false-positive tests (§4.5), O7 loader-refusal tests (index drift, out-of-range, cross-sentence, sha mismatch), and validator tests.
3. The existing v2.1 tests stay green against the frozen v2 path.

### 8.6 Migration to metrics v3
1. `score.py`: `METRICS_VERSION = "3"`, with v3 fields and flags. The overwrite guard is unchanged.
2. `METRICS_SPEC` §2–§3 rewritten to this contract; §6 v3 row. ARCHITECTURE §8. EXPERIMENT_PLAN §4 (the gate uses v3 metrics; thresholds unchanged).
3. Rescore pilot v2 into `runs/pilot_v2/rescore_metrics-v3/` with a new baseline and report paths. v1, v2 and v2.1 outputs are kept.
4. Validation (§6): tier-B elicitation and freeze, pilot full review, κ, scorer precision and recall. Fix any cell that misses a target, with a version bump if a rule changes.
5. Freeze v3, tier B and the lexicons. Only then does P3 start.
