# OPEN_ISSUES.md — XLMem Technical Spike & Design Findings

**Status:** Active Tracking  
**Author:** Engineering Agent  
**Context:** P0 Setup & Pilot Spike

---

## 1. Store Inspectability Spike (`dump()` Evaluation across Frameworks)

> **Resolves:** PRD Open Question 1 (*"Do all three frameworks expose raw memory stores for duplicate counting?"*) and Blocking Risk R5 (*"Framework internals not inspectable"`).

Duplication Rate (DR) and False Merge Rate (FMR) require inspecting the entire memory store rather than querying for top-$k$ nearest neighbors. We audited the store-inspection mechanisms across all three target frameworks:

### 1.1 Mem0 (`mem0ai`)
- **Mechanism:** `Memory.get_all(filters={"user_id": user_id}, top_k=...)`.
- **Spike Finding:** Mem0 exposes a public `get_all` method. However, its method signature defines `top_k: int = 20` by default. Invoking `get_all(filters=...)` without arguments silently truncates the retrieved store to 20 entries, masking long-term memory bloat.
- **Resolution:** In [`Mem0Adapter`](xlmem/adapters/mem0_adapter.py), `dump()` explicitly passes `top_k=100000` to guarantee complete extraction of all stored records. In addition, the adapter tracks ingested turns and snapshot state to verify vector store integrity.
- **Inspectability Verdict:** **APPROVED.** Complete store dump is fully supported.

### 1.2 Letta (formerly MemGPT)
- **Mechanism:** Dual memory substrate: Core Memory (`core_memory.get`) and Archival Memory (`passages.list`).
- **Spike Finding:** Core memory holds persona and human blocks (in-context), while archival memory holds arbitrary conversational facts in a vector/SQL database (Chroma/SQLite/PostgreSQL). The SDK `client.agents.passages.list(agent_id, limit=..., after=...)` returns paginated passages with a maximum batch size of 100.
- **Resolution:** [`LettaAdapter`](xlmem/adapters/letta_adapter.py) must implement cursor pagination, iterating until `after` is null, and concatenate archival passages with core memory blocks. Alternatively, when running against a local SQLite instance, direct inspection of the `passages` table (`SELECT text, metadata FROM passages WHERE agent_id = ?`) provides a zero-overhead ground truth dump.
- **Inspectability Verdict:** **APPROVED.** Complete store dump is supported via cursor pagination and direct database inspection.

### 1.3 A-MEM (Active Memory - Xu et al., 2025)
- **Mechanism:** Interactive memory network graph backed by ChromaDB and local JSON graphs.
- **Spike Finding:** A-MEM stores active memories as nodes in a graph index (`memory_network.json`) and indexes representations in ChromaDB. ChromaDB collections support `collection.get()`, which retrieves all stored embeddings and text documents when called without a `limit` or with `include=['documents', 'metadatas']`.
- **Resolution:** [`AMEMAdapter`](xlmem/adapters/amem_adapter.py) will query `collection.get()` and read the graph node state directly from disk.
- **Inspectability Verdict:** **APPROVED.** Complete store dump is supported.

---

## 2. Technical Findings & Architectural Nuances

### 2.1 Write-First Evaluation Ordering
- **Observation:** If an agent fails to extract a fact from a Hindi prompt during the plant turn (e.g. because the framework's internal extraction prompt is tuned for English), the memory store never contains the fact.
- **Risk:** In naive evaluation harnesses, querying for this fact in English produces a retrieval miss. The failure is erroneously counted as a cross-lingual retrieval failure, even though retrieval over the store was never possible.
- **Enforcement:** All scoring pipelines compute `Write Fidelity (WF)` first. In [`xlmem/scoring/retrieval.py`](xlmem/scoring/retrieval.py), `compute_recall_at_k` explicitly supports filtering by `eligible_fact_ids` (facts that passed Write Fidelity). Both partitioned recall and raw unpartitioned recall are tracked to prevent conflation.

### 2.2 Implicit vs. Explicit Consolidation Timing
- **Observation:** Mem0 reconciles memories eagerly at write time (`add()` prompts an LLM to decide whether to add, update, or ignore a fact). A-MEM, conversely, performs periodic or explicit graph consolidation.
- **Handling:** As documented in `AGENTS.md` and `ARCHITECTURE.md`, `consolidate()` is treated as a no-op for eager frameworks. To guarantee fair comparison without distorting native framework behavior, snapshots are captured **before and after every conversational phase** (`store_after_plant.json`, `store_final.json`).

### 2.3 Singular/Plural & Entity-Shift Matching in Metrics
- **Observation:** Strict matching on canonical values (e.g. `peanuts`) failed on valid morphological variants (e.g. `"User has peanut allergy"`). In addition, for entity-shift distractors sharing the same value (e.g. `(user, allergic_to, peanuts)` vs `(user_sister, allergic_to, peanuts)`), naive value matching falsely flagged non-merged memories as merged.
- **Handling:** `normalize_text` and `strict_match` in [`xlmem/scoring/judge.py`](xlmem/scoring/judge.py) were enhanced to handle noun number variations and underscore-to-space normalization. In [`xlmem/scoring/duplication.py`](xlmem/scoring/duplication.py), `compute_false_merge_rate` handles value-shift and entity-shift pairs separately.
