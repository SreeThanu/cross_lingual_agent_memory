# PRD — XLMem: Cross-Lingual Agent Memory Benchmark

| Field | Value |
|---|---|
| **Project** | XLMem — Does Long-Term Agent Memory Survive Language Switching? |
| **Course** | M.Tech (AI & ML) — Dissertation 1 |
| **Student** | Sree Thanu Bhuvanesh Ganesa Kumar (25MAI0019) |
| **Guide** | Baskaran P |
| **Status** | Approved |
| **Duration** | 5 months |
| **Target output** | Scopus-indexed conference paper + public benchmark dataset |

---

## 1. Summary

LLM agents increasingly rely on **long-term memory**: they write facts learned from conversation into an external store, consolidate them, retrieve them in later sessions, and update them when things change. Every deployed memory framework (Mem0, Letta/MemGPT, A-MEM) and every benchmark evaluating them (LoCoMo, MemBench, MemoryAgentBench) is built and tested **in a single language, almost always English**.

Real users are frequently bilingual. A user may tell an assistant something in Hindi on Monday and ask about it in English on Wednesday, often code-switching inside a single session. **Whether agent memory survives this language switch has never been measured.**

XLMem is a research harness and benchmark that measures it.

---

## 2. Problem Statement

Agent memory is not a single operation — it is a lifecycle of four:

1. **Write** — extract a fact from conversation and store it
2. **Consolidate** — decide whether a new fact is the same as an existing one (merge) or different (keep separate)
3. **Retrieve** — find relevant memories for the current query
4. **Update** — revise a stored memory when the user corrects it

Cross-lingual *retrieval* over static corpora is well studied. But an agent's memory store is **self-written and evolving**: the agent generates its own mixture of languages, and must make consolidation and update decisions that no static retrieval system faces.

When these fail, they fail **silently**. No error is raised. The agent simply behaves as though the user's history never existed — and writes duplicate memories that compound over sessions.

---

## 3. Research Questions and Hypotheses

| ID | Research question | Hypothesis |
|---|---|---|
| **RQ1** | Does an agent retrieve a memory written in language A when probed in language B? | **H1.** Cross-language recall is materially lower than same-language recall, even with a multilingual embedder. |
| **RQ2** | Does consolidation correctly merge the same fact expressed in two languages? | **H2.** Frameworks silently duplicate cross-language facts at a high rate, and duplication compounds across sessions. |
| **RQ3** | Does a correction issued in one language update a memory written in another? | **H3.** Cross-language updates frequently leave the original memory stale, producing contradictory stores. |
| **RQ4** | Does a memory's quality depend on the language it was written in? | **H4.** Facts encoded in Hindi are recalled less reliably than identical facts encoded in English (encoding-language asymmetry). |
| **RQ5** | Can lightweight, deployment-realistic mitigations close the gap? | **H5.** Language-normalised writing and cross-lingual entity resolution recover a substantial fraction of lost performance at negligible cost. |

---

## 4. Goals and Non-Goals

### Goals

- **G1.** Release the first **cross-lingual agent-memory benchmark** (Hindi–English, incl. code-switched sessions) with parallel fact injection and controlled probing.
- **G2.** Measure failure across **all four memory operations**, attributing failures to specific operations rather than reporting an aggregate score.
- **G3.** Evaluate **≥3 open-source memory frameworks** × **≥2 backbone models** with variance reported over ≥3 seeds.
- **G4.** Implement and evaluate **≥2 mitigations**.
- **G5.** Produce a reproducible, open-source harness others can extend to new language pairs.

### Non-Goals

- ✗ Training or fine-tuning a new language model (inference-only project).
- ✗ Building a new memory framework — we *measure* existing ones.
- ✗ Covering many languages. **One pair (Hindi–English) done rigorously** beats five done shallowly.
- ✗ Human-subject data collection. All conversations are synthetic and scripted.
- ✗ Using paid APIs or cloud compute.

---

## 5. Scope (v1)

### In scope

| Dimension | v1 choice |
|---|---|
| Language pair | Hindi ↔ English, plus code-switched (Hinglish) sessions |
| Memory frameworks | Mem0, Letta (MemGPT), A-MEM |
| Backbone models | Qwen2.5-7B-Instruct, Llama-3.2-3B-Instruct (4-bit) |
| Embedders | BGE-M3, multilingual-E5-base |
| Fact count | 200–300 parallel fact pairs across 6–8 domains |
| Probe directions | hi→hi, en→en, hi→en, en→hi |
| Seeds | 3 per configuration |

### Explicitly deferred

Additional Indic languages · multimodal memory · multi-agent shared memory · production latency benchmarking.

---

## 6. Deliverables

| # | Deliverable | Form |
|---|---|---|
| D1 | **XLMem benchmark** — fact bank, session scripts, probe sets | Public dataset (HuggingFace / GitHub) |
| D2 | **XLMem harness** — adapters, runner, scoring | Open-source repository |
| D3 | **Results** — metrics across frameworks/models/directions | Tables + figures, raw logs |
| D4 | **Mitigation study** | Code + comparative results |
| D5 | **Paper** | Scopus conference submission |
| D6 | **Reproducibility pack** | Configs, seeds, environment lockfile |

---

## 7. Success Criteria

**Minimum (project passes):**
- Benchmark constructed and released
- All four memory operations measured on ≥2 frameworks
- Findings written up and submitted

**Target:**
- ≥3 frameworks × ≥2 models, 3 seeds, with variance reported
- At least one mitigation showing measurable improvement
- Paper accepted at a Scopus-indexed venue

**Important:** the study yields a publishable result **regardless of direction**. If frameworks handle language switching well, that is the first evidence of cross-lingual robustness in agent memory — equally novel, equally publishable. There is no outcome in which the project produces nothing.

---

## 8. Experimental Design

**Core method — parallel fact injection with controlled probing.**

Because we inject every fact ourselves, ground truth is known exactly for every probe. This removes annotation cost and makes scoring deterministic.

```
For each fact f (with Hindi form f_hi and English form f_en):
  1. PLANT   f in language L_store during session 1
  2. FILLER  run N distractor turns / sessions
  3. PROBE   query about f in language L_query
  4. SCORE   was f recalled?  (4 directions: hi→hi, en→en, hi→en, en→hi)
  5. INSPECT dump raw memory store → count duplicates / false merges
  6. UPDATE  correct f in language L_update; re-probe → staleness
```

**Experimental matrix:** 3 frameworks × 2 models × 4 directions × ~250 facts × 3 seeds.

### Metrics

| Metric | Definition |
|---|---|
| **XL-Recall@k** | Fraction of planted facts retrieved when probed in the other language |
| **Language Transfer Gap (LTG)** | same-language recall − cross-language recall |
| **Duplication Rate (DR)** | Duplicate store entries per planted fact |
| **False Merge Rate (FMR)** | Distinct facts wrongly merged into one |
| **Staleness Rate (SR)** | Post-correction probes returning the superseded value |
| **Encoding Asymmetry (EA)** | recall(stored-hi) − recall(stored-en) |

LTG, DR, FMR and EA are **new metrics introduced by this work** — existing benchmarks have no equivalent because they never vary language.

---

## 9. Resource Requirements

### Hardware

| Resource | Requirement | Justification |
|---|---|---|
| **GPU** | 1 × RTX A4000 (16 GB VRAM) | 7B backbone in 4-bit ≈ 5 GB; BGE-M3 ≈ 2 GB. Fits with headroom. |
| **System RAM** | ≥ 32 GB | Vector store + framework orchestration |
| **Disk** | ~300 GB persistent | Model weights (~120 GB), memory stores, logs |
| **GPU time** | **~250–350 hours over 5 months** (≈12–15 h/week) | Inference-only; batched overnight runs |

### Software (all free and open-source)

Python 3.11 · PyTorch + CUDA · HuggingFace Transformers · Ollama or vLLM · Mem0 · Letta · A-MEM · sentence-transformers (BGE-M3) · multilingual NLI judge (mDeBERTa) · ChromaDB / Qdrant · pandas, matplotlib

### Access requirements

1. **Sustained lab access** to the A4000 workstation for ~5 months
2. **Package installation** via Conda/venv in the user directory — **no sudo required**
3. **Network access to `huggingface.co`** for model weights *(critical — if firewalled, the project cannot start)*
4. **Persistent storage** that is not wiped between sessions
5. **Long-running job support**, ideally **SSH access** for 4–8 hour overnight batches

### Cost

**₹0 recurring.** No paid APIs, no cloud, no licensed software, no proprietary data.

> **Note on lab load:** benchmark construction, harness development, and analysis all run on a personal laptop. The lab GPU is needed only for experiment execution.

---

## 10. Timeline

| Phase | Weeks | Output |
|---|---|---|
| **P0 — Setup & pilot** | 1–3 | Environment, one framework, 20 facts end-to-end. **Gate: signal visible.** |
| **P1 — Benchmark construction** | 3–6 | Full fact bank, session generator, probe sets |
| **P2 — Adapters** | 5–8 | Uniform adapter over all 3 frameworks + `dump()` |
| **P3 — Main experiments** | 8–13 | Full matrix, 3 seeds, all metrics |
| **P4 — Mitigations** | 12–15 | 2 mitigations implemented and evaluated |
| **P5 — Writing** | 14–18 | Paper drafted, internal review |
| **P6 — Submission & revision** | 18–20 | Submitted with revision buffer |

**Critical gate at Week 3:** if the pilot shows no measurable cross-lingual effect at all, scope pivots toward the consolidation/duplication axis (where the effect is most likely) rather than continuing blind.

---

## 11. Risks and Mitigations

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | **HuggingFace blocked on lab network** | 🔴 Blocking | Confirm before Week 1; fall back to offline weight transfer via personal machine |
| R2 | Framework APIs unstable / breaking changes | 🟠 High | Pin exact versions in lockfile; adapter layer isolates changes to one file |
| R3 | Effect size too small to be interesting | 🟠 High | Consolidation/duplication (RQ2) is the likeliest strong effect — prioritise it; negative results still publishable |
| R4 | Scooped by a concurrent paper | 🟠 High | Space is moving fast (PolyWorkBench, Jul 2026). Lock topic now; re-check arXiv monthly; emphasise consolidation/update angle which is furthest from existing work |
| R5 | Framework internals not inspectable (`dump()` unavailable) | 🟡 Medium | Verify store inspectability during Week 1 spike; drop any framework that cannot be inspected |
| R6 | Hindi generation quality poor from small models | 🟡 Medium | Facts are authored/templated, not model-generated; native-speaker spot-check |
| R7 | Lab access interruptions (exams, maintenance) | 🟡 Medium | 4-week buffer built into timeline; harness runs unattended |
| R8 | Scoring ambiguity (was the fact "recalled"?) | 🟡 Medium | Structured facts with exact-match keys + NLI fallback; report both strict and lenient scores |

---

## 12. Open Questions

1. Do all three frameworks expose raw memory stores for duplicate counting? *(resolve in Week 1)*
2. Should code-switched sessions be a third storage condition or a separate axis? *(resolve after pilot)*
3. Is a 3B backbone sufficient, or does memory behaviour require ≥7B to be meaningful? *(resolve in pilot)*

---

## 13. References

Key prior work positioning this project: MemGPT (Packer et al., 2023) · Mem0 (Chhikara et al., 2025) · A-MEM (Xu et al., 2025) · LoCoMo (Maharana et al., 2024) · MemoryAgentBench (Hu et al., 2026) · BGE-M3 (Chen et al., 2024) · Hindi-BEIR (Acharya et al., 2025) · GLUECoS (Khanuja et al., 2020) · MASSIVE-Agents (2026) · PolyWorkBench (arXiv:2607.06008, 2026).

*Full citations in the accompanying literature survey document.*
