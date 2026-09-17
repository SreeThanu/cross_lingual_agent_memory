# EXPERIMENT_PLAN.md — XLMem Experiment Plan & Execution Protocol

**Status:** Approved Specification  
**Purpose:** Enumerates the complete experimental run matrix, GPU execution budget, stage-by-stage execution sequence, the Week-3 pilot gate criteria, and contingency pivot policies.

---

## 1. Full Experimental Run Matrix

The experimental space systematically varies across:
- **3 Memory Frameworks:** Mem0, Letta (MemGPT), A-MEM
- **2 Backbone LLMs (4-bit local):** Qwen2.5-7B-Instruct, Llama-3.2-3B-Instruct
- **4 Directional Conditions:** `en->en`, `hi->hi` (baselines), `hi->en`, `en->hi` (cross-lingual evaluation)
- **3 Random Seeds:** 11, 22, 33 per condition
- **2 Mitigations (evaluated on cross-lingual runs):** `normalize` (pivot-language normalization at write), `xling_er` (cross-lingual entity resolution)

### 1.1 Enumerated Primary Matrix (72 Runs)

| Run ID Range | Framework | Backbone Model | Direction | Mitigation | Seeds | Total Runs |
|---|---|---|---|---|---|---|
| **R01–R03** | Mem0 | Qwen2.5-7B-Instruct | `en->en` | none | 11, 22, 33 | 3 |
| **R04–R06** | Mem0 | Qwen2.5-7B-Instruct | `hi->hi` | none | 11, 22, 33 | 3 |
| **R07–R09** | Mem0 | Qwen2.5-7B-Instruct | `hi->en` | none | 11, 22, 33 | 3 |
| **R10–R12** | Mem0 | Qwen2.5-7B-Instruct | `en->hi` | none | 11, 22, 33 | 3 |
| **R13–R15** | Mem0 | Llama-3.2-3B-Instruct | `en->en` | none | 11, 22, 33 | 3 |
| **R16–R18** | Mem0 | Llama-3.2-3B-Instruct | `hi->hi` | none | 11, 22, 33 | 3 |
| **R19–R21** | Mem0 | Llama-3.2-3B-Instruct | `hi->en` | none | 11, 22, 33 | 3 |
| **R22–R24** | Mem0 | Llama-3.2-3B-Instruct | `en->hi` | none | 11, 22, 33 | 3 |
| **R25–R27** | Letta | Qwen2.5-7B-Instruct | `en->en` | none | 11, 22, 33 | 3 |
| **R28–R30** | Letta | Qwen2.5-7B-Instruct | `hi->hi` | none | 11, 22, 33 | 3 |
| **R31–R33** | Letta | Qwen2.5-7B-Instruct | `hi->en` | none | 11, 22, 33 | 3 |
| **R34–R36** | Letta | Qwen2.5-7B-Instruct | `en->hi` | none | 11, 22, 33 | 3 |
| **R37–R39** | Letta | Llama-3.2-3B-Instruct | `en->en` | none | 11, 22, 33 | 3 |
| **R40–R42** | Letta | Llama-3.2-3B-Instruct | `hi->hi` | none | 11, 22, 33 | 3 |
| **R43–R45** | Letta | Llama-3.2-3B-Instruct | `hi->en` | none | 11, 22, 33 | 3 |
| **R46–R48** | Letta | Llama-3.2-3B-Instruct | `en->hi` | none | 11, 22, 33 | 3 |
| **R49–R51** | A-MEM | Qwen2.5-7B-Instruct | `en->en` | none | 11, 22, 33 | 3 |
| **R52–R54** | A-MEM | Qwen2.5-7B-Instruct | `hi->hi` | none | 11, 22, 33 | 3 |
| **R55–R57** | A-MEM | Qwen2.5-7B-Instruct | `hi->en` | none | 11, 22, 33 | 3 |
| **R58–R60** | A-MEM | Qwen2.5-7B-Instruct | `en->hi` | none | 11, 22, 33 | 3 |
| **R61–R63** | A-MEM | Llama-3.2-3B-Instruct | `en->en` | none | 11, 22, 33 | 3 |
| **R64–R66** | A-MEM | Llama-3.2-3B-Instruct | `hi->hi` | none | 11, 22, 33 | 3 |
| **R67–R69** | A-MEM | Llama-3.2-3B-Instruct | `hi->en` | none | 11, 22, 33 | 3 |
| **R70–R72** | A-MEM | Llama-3.2-3B-Instruct | `en->hi` | none | 11, 22, 33 | 3 |

*Subtotal Primary Runs:* 24 configurations × 3 seeds = **72 runs**.

### 1.2 Mitigation Evaluation Matrix (72 Runs)
Evaluating 2 mitigations on the cross-lingual directions (`hi->en` and `en->hi`):
- 3 Frameworks × 2 Models × 2 Directions (`hi->en`, `en->hi`) × 2 Mitigations (`normalize`, `xling_er`) × 3 Seeds = **72 mitigation runs**.

*Grand Total Matrix:* **144 runs**.

---

## 2. GPU Time & Resource Budgeting

Hardware Profile: 1 × NVIDIA RTX A4000 (16 GB VRAM). Local inference only.

### 2.1 Per-Configuration Workload Breakdown
For an experiment of $N=250$ facts:
- **Phase 1 (Plant):** 250 memory write operations + consolidation $\approx 250$ LLM calls
- **Phase 2 (Filler):** 50 distractor turns $\approx 50$ LLM calls
- **Phase 3 (Probe):** 250 retrieval queries + 250 generation calls $\approx 250$ LLM calls
- **Phase 4 (Update & Re-probe):** 50 update turns + 50 re-probes $\approx 100$ LLM calls
- **Total per run:** $\approx 650$ LLM/embedder calls.
- **Latency:** ~2.5 seconds average per call on RTX A4000 (4-bit AWQ/GGUF).
- **Time per run:** $\approx 1625\text{ s} \approx 27\text{ minutes}$ (0.45 to 0.75 GPU-hours, capped at 1.0 GPU-hour).

### 2.2 Total GPU Time Budget

| Activity | Number of Runs | Hours / Run | Total GPU Hours |
|---|---|---|---|
| **Smoke & Conformance Testing** | ~30 test runs | 0.08 h (5 min) | 2.5 h |
| **P0 Pilot (20 facts)** | 4 directions × 1 seed | 0.15 h | 0.6 h |
| **P3 Primary Matrix (72 runs)** | 72 runs | ~0.8 h | ~58 h |
| **P4 Mitigations Matrix (72 runs)** | 72 runs | ~0.8 h | ~58 h |
| **Re-runs / Buffer / Checkpoints** | — | — | ~30 h |
| **Total Experiment Allocation** | — | — | **~150 GPU-hours** |
| **Allocated Lab Budget Window** | 5 months | 12–15 h/week | **250–350 GPU-hours** |

*Budget Feasibility:* Total required GPU time is well within the 250–350 hour allocation. All scoring and aggregation run on CPU (laptop), requiring 0 additional GPU-hours.

---

## 3. Execution Order (Cheapest Informative First)

To minimize wasted compute and detect failures early, runs are ordered from lowest cost to highest complexity:

1. **Step 0: Conformance & Fast Tests (0 GPU-hrs)**
   Run `pytest tests/ -m "not gpu"` and adapter contract tests with mock adapters.
2. **Step 1: Smoke Verification (0.1 GPU-hrs)**
   Run `python -m xlmem.scripts.smoke --framework mem0` (5 facts) to verify real Ollama / vLLM connectivity and CUDA VRAM.
3. **Step 2: Phase 0 Pilot (1.0 GPU-hrs)**
   Execute 20 facts across Mem0 with Qwen2.5-7B-Instruct across all 4 directions on seed 11.
   *Evaluate Week-3 Pilot Gate.*
4. **Step 3: English Monolingual Baseline (`en->en`) (18 GPU-hrs)**
   Run all 3 frameworks × 2 models on `en->en` across 3 seeds. This establishes the performance ceiling of single-language agent memory.
5. **Step 4: Hindi Monolingual Baseline (`hi->hi`) (18 GPU-hrs)**
   Run all configurations on `hi->hi`. Detects intrinsic Hindi degradation independent of language switching.
6. **Step 5: Cross-Lingual Evaluation (`hi->en` & `en->hi`) (36 GPU-hrs)**
   Execute the core cross-lingual study. Compute LTG, DR, FMR, SR, and EA.
7. **Step 6: Mitigations Evaluation (58 GPU-hrs)**
   Execute `normalize` and `xling_er` on the cross-lingual configurations.

---

## 4. The Week-3 Pilot Gate: Numerical Criteria

At Week 3, the Phase 0 pilot (20 facts, Mem0 + Qwen2.5-7B, 4 directions) is evaluated against explicit numerical thresholds:

### Numerical "Signal Visible" Definition:
The pilot is declared to exhibit visible cross-lingual degradation signal if **at least one** of the following criteria is met:
1. **Language Transfer Gap (LTG) $\ge 0.05$:** Cross-lingual retrieval recall (`hi->en` or `en->hi`) is at least 5 percentage points lower than same-language recall (`en->en` / `hi->hi`).
2. **Duplication Rate (DR) $\ge 0.10$:** At least 10% of planted facts produce duplicate records in the store snapshot.
3. **False Merge Rate (FMR) $\ge 0.05$:** Distractor pairs are falsely collapsed in at least 5% of opportunities.
4. **Staleness Rate (SR) $\ge 0.10$:** Cross-lingual corrections fail to overwrite old values in $\ge 10\%$ of test cases.
5. **Write Fidelity Gap $\ge 0.05$:** Hindi write fidelity is noticeably lower than English write fidelity.

---

## 5. Contingency Pivot Plan

### What if the Pilot Shows No Effect ($LTG < 0.05$ and $DR < 0.10$)?

If modern multilingual embeddings (BGE-M3) make single-turn direct retrieval (`XL-Recall@k`) near-lossless across languages:
1. **Do not force or fake retrieval failure.** Surprising robustness is a valid and publishable empirical finding.
2. **Pivot Emphasis to RQ2 (Consolidation & Duplication) and RQ3 (Update & Staleness):**
   - Direct retrieval over clean text is easiest for dense embeddings.
   - Consolidation and memory reconciliation, however, require the LLM backbone to reason over bilingual memory snippets.
   - Increase session count ($K=5$) and filler conversational density to measure long-term compound store bloat and drift over extended multi-session histories.
3. **Document in PRD and Paper:** Frame the finding as: *"While dense bilingual embeddings bridge simple cross-lingual retrieval, memory consolidation and reconciliation remain severely impaired across multi-session dialogues."*
