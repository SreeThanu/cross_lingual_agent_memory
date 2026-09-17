# XLMem: Cross-Lingual Agent Memory Benchmark & Harness

XLMem is a **research measurement harness** that evaluates whether an LLM agent's long-term memory survives when a user switches languages between sessions (Hindi ↔ English, including code-switched "Hinglish").

XLMem is **not** a product and **not** a memory system. It drives existing open-source agent memory frameworks (**Mem0**, **Letta/MemGPT**, **A-MEM**) through structured bilingual dialogues and measures failure across four distinct memory lifecycle operations: **Write**, **Consolidate**, **Retrieve**, and **Update**.

---

## 1. Quickstart

### Environment Setup

```bash
# Create environment from pinned lockfile
conda env create -f environment.lock.yml
conda activate xlmem

# Install local package in editable mode
pip install -e .

# Start local model server (Ollama)
ollama serve &
ollama pull qwen2.5:7b-instruct
ollama pull llama3.2:3b-instruct

# Verify environment, GPU, and local models
python -m xlmem.scripts.check_env
```

### Running Tests

```bash
# Fast tests (no GPU, run on laptop)
pytest tests/ -m "not gpu"

# Conformance tests for memory adapters
pytest tests/test_adapter_contract.py

# Full test suite
pytest tests/
```

### Running Experiments

```bash
# Fast smoke run (5 facts, ~5 min)
python -m xlmem.scripts.smoke --framework mem0

# Execute experiment from configuration
python -m xlmem.scripts.run --config configs/mem0_qwen_hi2en.yaml

# Re-score run logs offline (CPU only, no GPU needed)
python -m xlmem.scripts.score --run runs/mem0_qwen_hi2en

# Aggregate results over multiple seeds
python -m xlmem.scripts.aggregate --runs runs/ --out results/
```

---

## 2. Core Specifications & Documentation

- [`ARCHITECTURE_ESSENTIALS.md`](ARCHITECTURE_ESSENTIALS.md) — One-page conceptual orientation
- [`PRD.md`](PRD.md) — Project requirements, research questions, hypotheses, deliverables
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — System architecture, interface contracts, data models
- [`AGENTS.md`](AGENTS.md) — Working conventions, hard rules, and testing standards
- [`BENCHMARK_SPEC.md`](BENCHMARK_SPEC.md) — Fact bank schema, domain rationale, distractor logic
- [`METRICS_SPEC.md`](METRICS_SPEC.md) — Mathematical formulas, write-first ordering, NLI matching
- [`EXPERIMENT_PLAN.md`](EXPERIMENT_PLAN.md) — Run matrix, GPU budget, Week-3 pilot gate criteria
- [`OPEN_ISSUES.md`](OPEN_ISSUES.md) — Framework inspectability spike findings and open questions

---

## 3. Hard Rules & Invariants

1. **No paid APIs:** Local open models only (via Ollama or vLLM). No OpenAI, Anthropic, Gemini, or Cohere.
2. **Single inference chokepoint:** Every LLM call must route strictly through `xlmem/llm/client.py`.
3. **Runner never judges:** The runner records raw responses. All metric calculation lives in `xlmem/scoring/`.
4. **Append-only logs:** Logs in `runs/` are immutable. Re-scoring never rewrites logs or requires re-running GPU inference.
5. **No single-seed reporting:** Every number in `results/` is reported as mean ± std over $\ge 3$ seeds.
6. **Language is the only variable:** Changing facts, session structure, or seeds between compared conditions voids the comparison.
7. **`dump()` is non-negotiable:** Any eligible framework must expose a complete store dump to enable consolidation and duplication measurement.
8. **Check Write Fidelity first:** A fact missing from the store is a WRITE failure, never a retrieval failure.
