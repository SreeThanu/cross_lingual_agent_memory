# XLMem — Architecture Essentials

> **Read this first.** One page. Everything else is detail.
> Full design: [`ARCHITECTURE.md`](ARCHITECTURE.md) · Requirements: [`PRD.md`](PRD.md)

---

## What this is

A **measurement instrument**, not a memory system.

We drive existing agent-memory frameworks (Mem0, Letta, A-MEM) through scripted bilingual conversations and measure what breaks when the user switches language.

## The one question

> A user tells the agent something **in Hindi** on Monday.
> On Wednesday they ask about it **in English**.
> Does the agent remember?

## The four operations (never conflate them)

Memory is a lifecycle, and every metric names which step failed:

| | Operation | Failure looks like |
|---|---|---|
| 1 | **Write** | Fact never entered the store at all |
| 2 | **Consolidate** | Same fact stored twice, or two facts wrongly merged |
| 3 | **Retrieve** | Fact is in the store but isn't found |
| 4 | **Update** | Correction in one language leaves the other language stale |

**Consolidate and Update are the novel contribution.** Retrieval alone is close to known cross-lingual IR — do not lead with it.

---

## The core abstraction

Everything hangs off one interface. Add a framework = add one file.

```python
class MemoryAdapter(ABC):
    def reset(user_id)                        -> None
    def write(user_id, turn)                  -> WriteResult
    def consolidate(user_id)                  -> ConsolidationResult
    def retrieve(user_id, query, lang, k)     -> list[Memory]
    def update(user_id, correction)           -> UpdateResult
    def dump(user_id)                         -> list[Memory]   # ← non-negotiable
```

**`dump()` is a hard requirement.** Duplication and false merges are invisible from outside the store. A framework that cannot be dumped cannot be included in the study.

---

## Why the results are trustworthy

**Ground truth by construction.** We inject every fact ourselves, so the correct answer is always known — no human annotation, no LLM judge required, no ambiguity about what "remembered" means.

Every fact is a **language-neutral record** with per-language surface forms:

```python
Fact(entity="user", relation="allergic_to", value="peanuts",
     surface={"hi": "मुझे मूंगफली से एलर्जी है",
              "en": "I'm allergic to peanuts"})
```

Plant the Hindi surface form, probe with the English one — same record, so scoring is exact.

---

## The four probe directions

| Store → Probe | Purpose |
|---|---|
| hi → hi | Baseline: does memory work at all? |
| en → en | Baseline: the case everyone already tests |
| **hi → en** | **The real question** |
| **en → hi** | Reverse direction — detects English bias |

---

## Non-negotiable invariants

1. **Language is the only variable.** Same facts, same sessions, same seeds across conditions.
2. **The runner never judges.** It records raw responses; all interpretation happens in scoring, offline.
3. **Logs are immutable and complete.** Re-scoring must never require re-running the GPU.
4. **Never report a single seed.** Minimum 3 seeds, always mean ± std.
5. **All model calls go through `llm/client.py`.** One chokepoint — no scattered inference calls.
6. **No paid APIs. Ever.** Local open models only.
7. **Check Write Fidelity first.** A "retrieval failure" for a fact that was never written is a write failure.

---

## Data flow

```
config.yaml
   ↓
benchmark  →  session script (plant / filler / probe / correct)
   ↓
runner  →  MemoryAdapter  →  framework  →  LLM + embedder (local, 4-bit)
   ↓
run log (JSONL)  +  store snapshots
   ↓
scoring (offline, no GPU)  →  metrics
   ↓
analysis  →  tables & figures
```

**GPU is needed only for the middle.** Building the benchmark and scoring results run on a laptop.

---

## Metrics cheat-sheet

- **XL-Recall@k** — cross-language retrieval hit rate
- **LTG** — Language Transfer Gap = same-lang recall − cross-lang recall
- **DR** — Duplication Rate (consolidation failure)
- **FMR** — False Merge Rate (over-eager consolidation)
- **SR** — Staleness Rate (update failure)
- **EA** — Encoding Asymmetry: recall(stored-hi) − recall(stored-en)

LTG, DR, FMR and EA don't exist in prior benchmarks — they can't, because no prior benchmark varies language.

---

## Hardware reality

| | |
|---|---|
| Peak VRAM | **~11 GB of 16 GB** (7B backbone 4-bit + embedder + NLI judge) |
| One configuration | ~1.5–3 GPU-hours |
| Full matrix | ~60–100 GPU-hours |
| Total budget | **250–350 GPU-hours over 5 months** |
| Cost | **₹0** — no cloud, no APIs, no licences |

---

## Where to start reading code

1. `xlmem/adapters/base.py` — the abstraction everything depends on
2. `xlmem/benchmark/facts.py` — the data model
3. `xlmem/runner/experiment.py` — how one experiment executes
4. `xlmem/scoring/duplication.py` — the novel measurement

---

## The three things most likely to sink this

1. **`huggingface.co` blocked on the lab network** → verify in Week 1, before anything else.
2. **A framework won't expose its store** → verify `dump()` in the Week-1 spike; drop the framework if it can't.
3. **Scoring rule disputes** → always report strict *and* lenient (NLI) matching, so results can't be dismissed as an artifact of the matcher.
