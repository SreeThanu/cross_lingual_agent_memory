# BENCHMARK_SPEC.md — XLMem Benchmark Specification

**Status:** Approved Specification  
**Purpose:** Defines the exact contract, data schema, domain structure, distractor logic, session generation, and linguistic rules for the XLMem benchmark dataset.

---

## 1. Overview and Design Objectives

XLMem evaluates whether long-term agent memory persists across language boundaries (Hindi ↔ English and code-switched Hinglish). To guarantee that measurement failures reflect memory limitations rather than annotation noise or model evaluation artifacts, the benchmark satisfies three core design principles:

1. **Ground Truth by Construction:** All facts, distractors, and updates are synthetically authored from structured templates with explicit canonical tuples `(entity, relation, value)`. Ground truth is deterministic.
2. **Template-Authored, Never Model-Generated:** Target facts are authored by human bilingual designers using templates. Language models under test never generate benchmark facts, preventing model capability confounds from leaking into ground truth.
3. **Semantic Invariance across Languages:** The English (`en`), Hindi (`hi`), and code-switched (`hi-en`) surface forms express identical semantic propositions, differing only in linguistic surface realization.

---

## 2. Fact Bank Schema

The fact bank is stored in YAML format (`data/facts_v1.yaml`). Every entry represents an atomic personal fact about the user or their immediate circle.

### 2.1 YAML Schema Definition

```yaml
version: "1.0"
facts:
  - id: str                      # Unique identifier: f_<3-digit-integer>, e.g. "f_042"
    domain: str                  # Domain name (one of 8 approved domains)
    entity: str                  # Canonical entity key, language-neutral snake_case
    relation: str                # Canonical relation predicate, language-neutral snake_case
    value: str                   # Canonical target value, language-neutral snake_case
    distractor_of: str | null    # Base fact ID if this fact is a near-miss distractor, else null
    surface:
      hi: str                    # Hindi surface form in Devanagari script
      en: str                    # English surface form
      hi-en: str                 # Code-switched Hinglish surface form (Latin script)
    probe_questions:
      hi: str                    # Direct probe question in Hindi
      en: str                    # Direct probe question in English
      hi-en: str                 # Direct probe question in Hinglish
    update:                      # Specification for Phase 4 correction test
      updated_value: str         # Superseding canonical value
      surface:
        hi: str                  # Correction turn in Hindi
        en: str                  # Correction turn in English
        hi-en: str               # Correction turn in Hinglish
      probe_questions:
        hi: str                  # Re-probe question in Hindi
        en: str                  # Re-probe question in English
```

### 2.2 Fully Worked Example Fact (Base Fact + Distractor)

#### Base Fact:
```yaml
id: "f_012"
domain: "health"
entity: "user"
relation: "allergic_to"
value: "peanuts"
distractor_of: null
surface:
  hi: "मुझे मूंगफली से गंभीर एलर्जी है।"
  en: "I have a severe allergy to peanuts."
  hi-en: "Mujhe peanuts se severe allergy hai."
probe_questions:
  hi: "मुझे किस खाने की चीज़ से एलर्जी है?"
  en: "What food am I allergic to?"
  hi-en: "Mujhe kis food se allergy hai?"
update:
  updated_value: "cashews"
  surface:
    hi: "एक सुधार है: मुझे मूंगफली से नहीं, बल्कि काजू से एलर्जी है।"
    en: "An update: I am not allergic to peanuts, but to cashews."
    hi-en: "Ek update hai: mujhe peanuts se nahi, cashews se allergy hai."
  probe_questions:
    hi: "मुझे अब किस चीज़ से एलर्जी है?"
    en: "What am I allergic to now?"
```

#### Corresponding Near-Miss Distractor Fact (for False Merge testing):
```yaml
id: "f_012_dist"
domain: "health"
entity: "user_sister"
relation: "allergic_to"
value: "peanuts"
distractor_of: "f_012"
surface:
  hi: "मेरी बहन को मूंगफली से एलर्जी है।"
  en: "My sister has an allergy to peanuts."
  hi-en: "Meri sister ko peanuts se allergy hai."
probe_questions:
  hi: "मेरी बहन को किस चीज़ से एलर्जी है?"
  en: "What food is my sister allergic to?"
  hi-en: "Meri sister ko kis cheez se allergy hai?"
update: null
```

---

## 3. The 8 Benchmark Domains

To provide diverse semantic structures, lexical borrowing patterns, and entity types, facts are drawn from 8 balanced domains (30–35 facts per domain, total target ~250 facts):

| Domain | Focus & Entity Types | Linguistic / Benchmark Justification |
|---|---|---|
| **1. Health & Medical** | Allergies, chronic conditions, prescriptions, dietary bans | Critical personal facts where false merges or retrieval failures have high consequence. Low ambiguity in ground truth. |
| **2. Food & Dining** | Dietary restrictions (vegan, jain), spice tolerance, favorite dishes | Frequent conversational domain; high prevalence of culturally specific vocabulary (e.g. *paneer*, *karela*). |
| **3. Professional & Work** | Job title, current employer, programming languages, work schedule | High rate of English loanwords in Hindi spoken contexts; tests code-switching handling in technical vocabulary. |
| **4. Travel & Geography** | Hometown, current residence, planned destinations, commute mode | Named entities (cities, countries); tests cross-lingual transliteration robustness (e.g., *वाराणसी* vs *Varanasi* / *Banaras*). |
| **5. Family & Relationships** | Kinship relations, pet names, spouse preferences | Complex Indic kinship terminology (e.g. *chachi*, *mami*, *bhabhi*) vs flat English terms ("aunt", "sister-in-law"). |
| **6. Financial & Administrative** | Billing dates, preferred payment methods, utility account types | Numbers, dates, structured entities; tests whether quantitative constraints survive translation. |
| **7. Hobbies & Entertainment** | Musical instruments, sports teams, author preferences | Cultural entities and leisure activities; tests retrieval across distinct lexical fields. |
| **8. Technology & Devices** | Smartphone model, primary OS, preferred cloud storage | Technical jargon with English borrowings embedded in Hindi syntax. |

---

## 4. Construction of Distractor Facts (Near-Miss Pairs)

Consolidation failures in agent memory include **False Merges** (collapsing two distinct real-world facts into one memory record). To measure this systematically, 30% of base facts are paired with an explicit near-miss distractor:

### Near-Miss Pairing Rules
1. **Entity-Shift Near Miss:** The distractor retains the same `relation` and `value` but changes the `entity`:
   - Base: `(user, born_in, lucknow)`
   - Distractor: `(user_father, born_in, lucknow)`
2. **Value-Shift Near Miss:** The distractor retains the same `entity` and `relation` within the same semantic category:
   - Base: `(user, allergic_to, peanuts)`
   - Distractor: `(user, allergic_to, walnuts)`

If an agent's memory consolidates cross-lingual inputs by fuzzy semantic similarity without resolving the exact entity-relation bounds, it will falsely merge these entries into a single conflated memory.

---

## 5. Session Script Structure

A benchmark run simulates a multi-session relationship between a user and an agent across distinct conversational phases:

```
Session 1: PLANT PHASE
  - Ingestion of target facts in language L_store
  - Consolidation trigger
  - Snapshot A: dump() -> store_after_plant.json

Session 2 to K-1: FILLER PHASE (Memory Decay & Interference)
  - Neutral conversational dialogue turns (chit-chat, general QA)
  - Injection of distractor facts in alternate languages
  - Intermediate consolidation trigger

Session K: PROBE PHASE
  - Direct retrieval probes in language L_probe
  - Capture top-k retrieved memories + generated assistant response
  - No memory updates in this phase

Session K+1: CORRECTION PHASE (Update Test)
  - Ingestion of explicit correction turns for a fixed 20% subset of facts in language L_update
  - Consolidation trigger

Session K+2: RE-PROBE PHASE (Staleness Test)
  - Querying updated facts in language L_probe to verify whether superseded values were cleared
  - Snapshot B: dump() -> store_final.json
```

### Turn Kinds and Schema
Every turn in the script conforms to the `Turn` dataclass:
- `plant`: User provides a novel ground truth fact.
- `filler`: Chit-chat or topical discussion unrelated to target facts, or distractor injection.
- `probe`: User queries memory without volunteering the answer.
- `correction`: User explicitly revokes or updates a previously planted fact.

---

## 6. Code-Switching (Hinglish) Construction Rules

Hinglish in XLMem models natural Hindi-English code-switching adhering to the linguistic **Matrix Language Frame (MLF)** model:

1. **Matrix Language:** The morphosyntactic frame is Hindi. Word order follows Hindi SOV (Subject-Object-Verb).
2. **Grammatical Morphemes:** Postpositions (*ko*, *se*, *ka*, *ke liye*), auxiliaries/copulas (*hai*, *tha*, *hoga*), and inflectional suffixes remain in Hindi.
3. **Embedded Vocabulary:** Content nouns (*allergy*, *flight*, *project*), adjectives (*severe*, *late*), and verbs paired with Hindi light verbs (*check karna*, *confirm hona*) appear in English.
4. **Script & Orthography:** Represented in standard Latin script using intuitive phonetic spelling without non-standard SMS shortcuts (e.g. write `"Mujhe peanuts se allergy hai"`, never `"plz note m allergic 2 pnuts"`).

---

## 7. Semantic Equivalence Guarantees

To ensure that performance differences across language directions are strictly due to memory framework behavior and not linguistic asymmetry in prompt difficulty:

1. **Tuple Invariance:** The canonical tuple `(entity, relation, value)` is identical across all three surface forms.
2. **Direct Declaratives:** All plant turns use direct declarative statements without modal ambiguity (*"I live in Pune"*, *"मैं पुणे में रहता हूँ"*, *"Main Pune me rehta hoon"*).
3. **No Information Leaks in Probes:** Probe questions are strictly open-ended wh-queries (*"Where do I live?"*), never confirmation queries containing candidate answers.
4. **Bilingual Review Verification:** Every authored fact is verified by two bilingual speakers for translation equivalence, idiomatic naturalness, and absence of semantic drift.
