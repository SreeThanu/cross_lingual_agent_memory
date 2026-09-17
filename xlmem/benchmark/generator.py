"""Session script generator for multi-session cross-lingual dialogues."""

from __future__ import annotations

import random
from typing import Sequence
from xlmem.benchmark.facts import Fact, Turn


DEFAULT_FILLER_TURNS = [
    {
        "en": "How is the weather looking today?",
        "hi": "आज मौसम कैसा लग रहा है?",
        "hi-en": "Aaj weather kaisa lag raha hai?",
    },
    {
        "en": "Can you recommend a good book to read on machine learning?",
        "hi": "क्या आप मशीन लर्निंग पर पढ़ने के लिए कोई अच्छी किताब सुझा सकते हैं?",
        "hi-en": "Kya aap machine learning par koi achhi book recommend kar sakte ho?",
    },
    {
        "en": "What is the capital city of Australia?",
        "hi": "ऑस्ट्रेलिया की राजधानी कौन सा शहर है?",
        "hi-en": "Australia ki capital city kaun si hai?",
    },
    {
        "en": "Let's review the schedule for our upcoming project sprint.",
        "hi": "आइए हमारे आगामी प्रोजेक्ट स्प्रिंट की समय सारणी की समीक्षा करें।",
        "hi-en": "Aao hamare upcoming project sprint ka schedule review karein.",
    },
]


def build_session_script(
    facts: Sequence[Fact],
    store_lang: str,
    probe_lang: str,
    filler_sessions: int = 1,
    update_subset_ratio: float = 0.2,
    seed: int = 42,
) -> list[Turn]:
    """Construct an end-to-end multi-session script for an experiment run.

    Sessions:
      - Session 1: Plant phase (inject ground truth facts in store_lang)
      - Sessions 2..(1 + filler_sessions): Filler phase (distractors and neutral turns)
      - Session (2 + filler_sessions): Probe phase (queries in probe_lang)
      - Session (3 + filler_sessions): Correction phase (updates for a subset of facts)
      - Session (4 + filler_sessions): Re-probe phase (queries for updated facts)

    Args:
        facts: List of target facts.
        store_lang: Language code for planting ("hi" | "en" | "hi-en").
        probe_lang: Language code for probing ("hi" | "en" | "hi-en").
        filler_sessions: Number of intermediate distractor sessions.
        update_subset_ratio: Fraction of facts to update (default 0.2 = 20%).
        seed: Random seed for deterministic script ordering.

    Returns:
        List of conversational Turn dataclasses.
    """
    rng = random.Random(seed)
    turns: list[Turn] = []

    # Filter base facts vs distractors
    base_facts = [f for f in facts if f.distractor_of is None]
    distractor_facts = [f for f in facts if f.distractor_of is not None]

    # 1. Session 1: Plant phase
    s_idx = 1
    for fact in base_facts:
        text = fact.surface.get(store_lang) or fact.surface.get("en", "")
        turns.append(
            Turn(
                session_id=s_idx,
                role="user",
                lang=store_lang,
                text=text,
                kind="plant",
                fact_id=fact.id,
            )
        )

    # 2. Filler Sessions: inject distractor facts and neutral conversational turns
    distractor_pool = list(distractor_facts)
    rng.shuffle(distractor_pool)

    for f_step in range(filler_sessions):
        s_idx += 1
        # Neutral filler turn
        filler_choice = rng.choice(DEFAULT_FILLER_TURNS)
        filler_text = filler_choice.get(store_lang) or filler_choice["en"]
        turns.append(
            Turn(
                session_id=s_idx,
                role="user",
                lang=store_lang,
                text=filler_text,
                kind="filler",
                fact_id=None,
            )
        )

        # Distractor injection if available
        if distractor_pool:
            d_fact = distractor_pool.pop(0)
            d_text = d_fact.surface.get(store_lang) or d_fact.surface.get("en", "")
            turns.append(
                Turn(
                    session_id=s_idx,
                    role="user",
                    lang=store_lang,
                    text=d_text,
                    kind="filler",
                    fact_id=d_fact.id,
                )
            )

    # 3. Probe Session: Probe all base facts in probe_lang
    s_idx += 1
    for fact in base_facts:
        q_text = ""
        if fact.probe_questions and probe_lang in fact.probe_questions:
            q_text = fact.probe_questions[probe_lang]
        else:
            # Fallback probe prompt if questions not pre-templated
            if probe_lang == "hi":
                q_text = f"यूज़र के {fact.relation} के बारे में क्या जानकारी है?"
            elif probe_lang == "hi-en":
                q_text = f"User ke {fact.relation} ke baare me kya pata hai?"
            else:
                q_text = f"What is the user's {fact.relation.replace('_', ' ')}?"

        turns.append(
            Turn(
                session_id=s_idx,
                role="user",
                lang=probe_lang,
                text=q_text,
                kind="probe",
                fact_id=fact.id,
            )
        )

    # 4. Correction Session: Subset of base facts updated
    updateable_facts = [f for f in base_facts if f.update_data is not None]
    n_update = max(1, int(len(updateable_facts) * update_subset_ratio)) if updateable_facts else 0
    selected_for_update = updateable_facts[:n_update]

    if selected_for_update:
        s_idx += 1
        for fact in selected_for_update:
            assert fact.update_data is not None
            update_surfaces = fact.update_data.get("surface", {})
            corr_text = update_surfaces.get(store_lang) or update_surfaces.get("en", "")
            if not corr_text:
                corr_text = f"Correction: the {fact.relation} is actually {fact.update_data.get('updated_value')}."
            turns.append(
                Turn(
                    session_id=s_idx,
                    role="user",
                    lang=store_lang,
                    text=corr_text,
                    kind="correction",
                    fact_id=fact.id,
                )
            )

        # 5. Re-probe Session: Check if corrections took effect
        s_idx += 1
        for fact in selected_for_update:
            assert fact.update_data is not None
            reprobe_qs = fact.update_data.get("probe_questions", {})
            reprobe_text = reprobe_qs.get(probe_lang) or fact.probe_questions.get(probe_lang, "")
            if not reprobe_text:
                if probe_lang == "hi":
                    reprobe_text = f"यूज़र के {fact.relation} के बारे में अब क्या जानकारी है?"
                else:
                    reprobe_text = f"What is the user's current {fact.relation.replace('_', ' ')}?"

            turns.append(
                Turn(
                    session_id=s_idx,
                    role="user",
                    lang=probe_lang,
                    text=reprobe_text,
                    kind="probe",
                    fact_id=fact.id,
                )
            )

    return turns
