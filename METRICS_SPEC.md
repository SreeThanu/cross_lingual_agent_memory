# METRICS_SPEC.md — XLMem Metrics Specification

**Status:** Approved Specification  
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

#### A. Duplication Rate (DR)
Measures the failure of the consolidation mechanism to recognise that two turns (or parallel cross-lingual statements) express the same ground truth fact, resulting in redundant memory bloat.
$$\text{DR} = \frac{1}{|\mathcal{F}_{\text{planted}}|} \sum_{f \in \mathcal{F}_{\text{planted}}} \max(0, N_{\text{records}}(f, \mathcal{M}) - 1)$$
where $N_{\text{records}}(f, \mathcal{M})$ is the count of distinct memory records in `dump()` matching fact $f$.
- **Domain:** $[0.0, \infty)$ (ideal is $0.0$; $1.0$ means on average every fact is stored twice).
- **Operation Tested:** CONSOLIDATE.

#### B. False Merge Rate (FMR)
Measures over-eager consolidation where two semantically related but distinct facts (e.g. a base fact and its near-miss distractor) are incorrectly collapsed into a single memory entry.
$$\text{FMR} = \frac{|\{(f, f') \in \mathcal{D}_{\text{distractor\_pairs}} \mid \text{falsely\_merged}(f, f', \mathcal{M})\}|}{|\mathcal{D}_{\text{distractor\_pairs}}|}$$
where $\text{falsely\_merged}(f, f', \mathcal{M})$ is true if a single memory entry matches both canonical values while failing to separate distinct entities/relations.
- **Domain:** $[0.0, 1.0]$ (ideal is $0.0$).
- **Operation Tested:** CONSOLIDATE.

---

### 2.3 Operation 3: RETRIEVE

#### A. XL-Recall@k
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

#### A. Staleness Rate (SR)
The fraction of corrected facts where querying post-correction returns the obsolete value rather than the updated value.
$$\text{SR} = \frac{|\{f \in \mathcal{F}_{\text{corrected}} \mid \text{returns\_superseded}(f, \text{response}) \lor \text{conflicted}(f, \text{response})\}|}{|\mathcal{F}_{\text{corrected}}|}$$
- **Domain:** $[0.0, 1.0]$ (ideal is $0.0$; high means updates fail to clear old cross-lingual memories).
- **Operation Tested:** UPDATE.

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

Both Strict and Lenient scores must be reported side-by-side in all final evaluation tables.

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
- **Staleness Rate (SR):** $1 / 1 = 1.00$ ($100\%$).

---

## 5. Seed Aggregation and Variance Reporting

To ensure statistical significance and prevent cherry-picking:
1. Every experimental configuration is executed across $\ge 3$ random seeds (default: $\{11, 22, 33\}$).
2. For each metric $M$, compute sample mean $\bar{M}$ and sample standard deviation $s$:
   $$\bar{M} = \frac{1}{S} \sum_{s=1}^S M_s, \quad s = \sqrt{\frac{1}{S-1}\sum_{s=1}^S (M_s - \bar{M})^2}$$
3. All values in `results/` are formatted as:
   $$\bar{M} \pm s$$
4. **Single-seed reporting is strictly prohibited.** Any cell in a table without mean and variance over $\ge 3$ seeds is invalid.
