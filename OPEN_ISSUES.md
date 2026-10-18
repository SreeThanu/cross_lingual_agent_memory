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

- **Live check (2026-10-18):** Letta 0.13.0 server + Ollama qwen2.5:7b-instruct + bge-m3:latest.
  - **Server needs Postgres.** Letta 0.13.0's async DB layer always builds a Postgres URI and ignores SQLite, so the server cannot start without Postgres + pgvector. Uses the existing Docker container `xlmem-letta-pg` (pgvector/pgvector:pg16, `127.0.0.1:55432`, no auto-restart, data in a Docker volume; created by the Sep session). Start it with `docker start xlmem-letta-pg`, then the server in tmux:
    `cd ~/.letta && OLLAMA_BASE_URL=http://localhost:11434 LETTA_PG_URI=postgresql+pg8000://letta:letta@localhost:55432/letta letta server --host localhost --port 8283`
    The database holds leftover agents from earlier test runs; contract tests do not delete theirs.
  - **Temperature was 0.7.** That's Letta's default for new agents; the adapter never set it. Fixed: the adapter sets the harness temperature on every agent and reads the agent back. It raises unless the server runs the requested handles, temperature and Ollama endpoint. It also refuses `letta/letta-free`, a Letta-hosted model the server offers alongside Ollama.
  - **Contract tests: 5/6 pass.** `test_write_and_dump_roundtrip` fails 3/3. It writes a Hindi turn then an English turn to one agent, and the second write fails with Letta's 502 "No tool calls found in response, model must make a tool call".
  - **Probe of that failure (2 trials each, fresh agent):** en→en both writes succeed 2/2. hi→en: the 2nd (English) write fails 2/2. en→hi: the 2nd (Hindi) write fails 1/2. A single Hindi turn alone succeeds 3/3. So **Letta+Qwen's tool calling breaks when a conversation mixes languages**, and the turn is lost. This is a real cross-lingual WRITE failure (scored by WF via `dump()`), not a harness fault. Do not retry it away.
  - **Contract suite made English-only (2026-10-18).** The round-trip test now checks that each written fact's content is in `dump()` instead of one record per write with a `fact_id` tag: Letta stores several facts in one core block, and the scorer only matches text. With that, **all 24 contract tests pass live for mock, Mem0, Letta and A-MEM.** Mixed-language behaviour moved to `tests/test_mixed_language_probe.py` (gpu), which requires only soft failure and a dumpable store.
  - **Probe run (2026-10-18), single trial each:**
    - Mem0, en then hi: both writes reported ok, but the store held only "Have an allergy to moong dal"; the English Google fact was gone.
    - Letta, en then hi: the Hindi write was reported FAILED, yet "I have a peanut allergy." was stored.
    - A-MEM stored everything verbatim.
    So the write success flag is unreliable in both directions. WF must keep reading `dump()`.
  - **Smoke run (2026-10-18), `runs/smoke_letta_hi2en_20261018-160029`, 28 s, hi→en, 5 facts, seed 11.** Completes end to end. Everything went into one core `human` block:
    - 3 Hindi facts translated correctly to English (Pune, Infosys, biryani).
    - The peanut fact was stored in Chinese as mung beans; its write was flagged FAILED although stored. The probe answer: "You are allergic to绿豆 (mung beans)."
    - The pet-dog fact was lost; its write was flagged FAILED and nothing was stored.
    - Scored with the smoke facts: WF 0.6 (correct: 3 right, 1 corrupted, 1 lost), R@1 1.0, SR 0.0 (no corrections in the smoke set, so not measured).
    - **Recall is not meaningful for Letta core memory:** `retrieve()` returns the whole core block (1 record) for every query, so every written core fact counts as retrieved. See ARCHITECTURE §16.
  - **Hindi stored as Chinese, with the wrong value.** Every successful Hindi write of "मुझे मूंगफली से एलर्जी है।" (peanut allergy) was stored as "用户对绿豆过敏。" (Chinese: "the user is allergic to *mung beans*"), 3/3 identical. That is a third language, and the same peanut→mung-bean error Mem0 made in the Sep pilot ("moong dal"). Two frameworks making the same error points to the **backbone** (Qwen2.5-7B) mistranslating मूंगफली, so the Llama backbone runs should test it.

### 1.3 A-MEM (Active Memory - Xu et al., 2025)
- **Correction (2026-10-18):** the original entry below the line described a graph file (`memory_network.json`) and an `AMEMAdapter` that do not exist. Verified against the source of `agiresearch/A-mem` at commit `ceffb86` (the library, as opposed to the paper-reproduction repo `WujiangXu/AgenticMemory`), with the LLM stubbed and CPU only:
  - **Store:** every note is held in the in-process dict `AgenticMemorySystem.memories` and mirrored in an in-memory ChromaDB collection. 12 notes added gave 12 in `memories` and 12 in Chroma. A full `dump()` is possible.
  - **No deduplication:** `add_note()` stores the turn text verbatim as a new note, even an identical one. "Evolution" only edits neighbours' tags and context and links notes. So for A-MEM, WF is ~1.0 by construction and DR measures no merging at all. This is a framework property to report, not a bug.
  - **Isolation:** the constructor calls `client.reset()` on the process-wide Chroma client, and every instance uses the collection name `"memories"`. Creating a second instance deletes the first one's vector store. On chromadb 1.5.9 the first instance then raises `NotFoundError`. On chromadb 0.4.24 it fails **silently**: its Chroma collection holds 0 documents while `memories` still holds every note, so `dump()` would report the facts as written while search returns nothing. That would be scored as a retrieval failure, not a write failure. The adapter must prevent it (one instance per process, or a per-user collection created without the reset), and its contract test must check that search still works after a second user is created.
  - **Defaults that would break hard rules:** `llm_backend="openai"` with `gpt-4o-mini` (paid API, rule 1), so the adapter must pass `llm_backend="ollama"` and refuse otherwise. The default embedder is `all-MiniLM-L6-v2`, which is English-only and would confound every cross-lingual comparison with Mem0 (BGE-M3), so the adapter must set a multilingual embedder.
  - **Temperature:** `OllamaController.get_completion` accepts `temperature` but never passes it to litellm, so Ollama's default (0.8) applies, not the harness's 0.0. Shim it in the adapter, as `Mem0Adapter` does for its LLM, and record it in ARCHITECTURE.md §16 if it can't be fully controlled.
  - **Environment (tested 2026-10-18):** A-MEM **can share the harness env**. In a clone of `xlmem` (`xlmem-amemtest`), installing its three missing runtime deps (rank_bm25 0.2.2, nltk 3.10.3, litellm 1.80.0, plus 9 transitive packages) under constraints pinning all 155 existing packages changed none of them. With A-MEM installed `--no-deps`, the offline dump check passed on xlmem's chromadb 0.4.24, torch 2.2.1 and sentence-transformers 2.5.1, and the offline suite passed (47 passed, 8 deselected). So the adapter can import A-MEM in-process; no bridge is needed. The deps are pinned in `environment.lock.yml`. They are not yet installed in `xlmem` itself. Not covered: the real Ollama path (the LLM was stubbed).
- **Adapter (2026-10-18):** `xlmem/adapters/amem_adapter.py` handles each item above: per-user Chroma collections with A-MEM's reset neutralised, the Ollama backend enforced, the temperature and base-URL shim, BGE-M3 by default, and `retrieve()`/`dump()` raising when the index and note store disagree or when search returns nothing for a non-empty store. Offline tests (`tests/test_amem_adapter.py`: real A-MEM and Chroma, LLM stubbed) pass, including a mutation check showing the isolation test fails without the fix. **Live contract tests (2026-10-18): 4/4 passed** (write/dump round trip, retrieve, reset isolation, update) against Ollama 0.34.2 on the A4000 (qwen2.5:7b-instruct, all 29 layers on GPU) with BGE-M3 (`BAAI/bge-m3` snapshot `5617a9f`, PyTorch weights only). The Ollama log shows exactly the 2 chat calls the code predicts.
  - **Smoke run (2026-10-18), `runs/smoke_amem_hi2en_20261018-153558`, 16 s:** hi→en, 5 facts, seed 11. All 5 Hindi notes stored verbatim; every probe retrieved the right note first and answered correctly in English. Scored with the smoke facts: WF 1.0, R@1 1.0, DR 0.0. **Caveats:**
    - WF and recall are 1.0 partly because the current strict matcher accepts the full authored sentence as an alias, which a verbatim store always contains. Mem0 paraphrases and cannot match the same way, so A-MEM vs Mem0 on Hindi under the current scorer would partly measure the scorer (decision D1).
    - SR printed 0.0 with no correction in the run (smoke facts have none); it should be undefined (D6).
    - The smoke set never exercises update/re-probe.
  - **Env bug found and fixed in the adapter:** a bare `import chromadb` fails in `xlmem` ("CXXABI_1.3.15 not found"). onnxruntime's native module loads the system libstdc++ before sqlite3/ICU need conda's newer one. Pre-existing (all involved packages date from 2026-09-18), unseen until now because nothing imported chromadb. The adapter imports sqlite3 first; a fresh-interpreter test guards it.
  - **Another A-MEM property:** at this commit `add_note()` does **not** call the LLM to extract keywords/context/tags (`analyze_content()` is never invoked on write), and evolution only runs once the store already holds a note. Notes therefore carry empty semantic metadata unless evolution fills it, and a user's first note never triggers an LLM call.
- **Inspectability Verdict:** **APPROVED**, with the isolation and environment caveats above.

<details><summary>Original entry (2026-09-17, inaccurate)</summary>

- **Mechanism:** Interactive memory network graph backed by ChromaDB and local JSON graphs.
- **Spike Finding:** A-MEM stores active memories as nodes in a graph index (`memory_network.json`) and indexes representations in ChromaDB. ChromaDB collections support `collection.get()`, which retrieves all stored embeddings and text documents when called without a `limit` or with `include=['documents', 'metadatas']`.
- **Resolution:** [`AMEMAdapter`](xlmem/adapters/amem_adapter.py) will query `collection.get()` and read the graph node state directly from disk.
- **Inspectability Verdict:** **APPROVED.** Complete store dump is supported.

</details>

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

### 2.4 Mem0 Update Staleness Observed in Phase 0 — ⚠️ INVALIDATED, see correction below
- **Observation (historical, preserved as originally recorded):** In the Phase 0 Mem0 pilot, fact `f_001` was corrected from a serious moong-dal allergy to a cashew allergy. The adapter reported `update_success: true`, but the subsequent English reprobe still retrieved the superseded memory `"Has a serious allergy to moong dal"` and the model responded `"You are allergic to moong dal."`
- **Metric Impact (as originally recorded):** The resulting Staleness Rate (SR) was `1.00` for the single corrected fact, consistent with the metric definition: the post-correction response returned the obsolete value.
- **Interpretation (as originally recorded):** This was recorded as an observed UPDATE failure in the Phase 0 pilot, not as a scoring or harness failure. The result was limited to this single-seed, 20-fact Hindi→English pilot and was not to be generalized to Mem0 without further experiments.
- **Follow-up (as originally recorded):** Investigate Mem0's native update/reconciliation behavior and quantify update staleness across the full multi-seed benchmark. Do not alter the scorer to suppress this observation.

- **Correction (post-fix):** The "subsequent English reprobe" above was not a genuine re-probe. The runner did not implement the RE-PROBE phase (BENCHMARK_SPEC.md Session K+2): it fed the Session-K probe — taken *before* the correction turn was ever issued — into `compute_staleness_rate` as if it were a post-correction re-probe. Every correction was therefore guaranteed to score as stale (SR = 1.00) regardless of what the framework actually did, since it had no opportunity to see the update. This was a harness bug, not a Mem0 defect; the bug has since been fixed (RE-PROBE now runs after CORRECTION, as its own `reprobe_result` record).
- **Do not treat this as evidence that Mem0 handles updates correctly, either.** A single post-fix re-run of this same single-seed, 20-fact `hi→en` pilot now measures `SR = 0.00`, with Mem0 performing a genuine in-place `UPDATE` and the re-probe correctly retrieving the corrected value — but one re-run of one seed is not evidence of general correctness any more than the original single run was evidence of failure (AGENTS.md Hard Rule 5: never report a single seed).
- **Status:** Update staleness for Mem0 (and any other framework) is **unresolved** and requires the full multi-seed evaluation called for in the original follow-up above, run against the fixed harness.
