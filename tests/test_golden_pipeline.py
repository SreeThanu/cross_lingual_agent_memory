"""Golden 10-fact mini-benchmark running end-to-end with a stubbed LLM.

Produces known, deterministic metric values without GPU or network access.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from xlmem.adapters.mock_adapter import MockAdapter
from xlmem.benchmark.facts import Fact
from xlmem.config import BenchmarkConfig, ExperimentConfig, LanguageConfig, ModelConfig
from xlmem.llm.client import LLMClient
from xlmem.runner.experiment import ExperimentRunner
from xlmem.scripts.score import score_single_seed_dir

GOLDEN_FACTS = [
    Fact(
        id="g_01",
        domain="health",
        entity="user",
        relation="allergic_to",
        value="peanuts",
        surface={"en": "I am allergic to peanuts.", "hi": "मुझे मूंगफली से एलर्जी है।"},
        probe_questions={"en": "What food am I allergic to?", "hi": "मुझे किस चीज़ से एलर्जी है?"},
        update_data={"updated_value": "cashews", "surface": {"en": "Correction: I am allergic to cashews, not peanuts."}},
    ),
    Fact(
        id="g_02",
        domain="travel",
        entity="user",
        relation="lives_in",
        value="pune",
        surface={"en": "I live in Pune.", "hi": "मैं पुणे में रहता हूँ।"},
        probe_questions={"en": "Where do I live?", "hi": "मैं कहाँ रहता हूँ?"},
    ),
    Fact(
        id="g_03",
        domain="work",
        entity="user",
        relation="works_at",
        value="infosys",
        surface={"en": "I work at Infosys in Pune.", "hi": "मैं पुणे में इंफोसिस में काम करता हूँ।"},
        probe_questions={"en": "Where do I work?", "hi": "मैं कहाँ काम करता हूँ?"},
    ),
    Fact(
        id="g_04",
        domain="languages",
        entity="user",
        relation="speaks_language",
        value="marathi",
        surface={"en": "I speak fluent Marathi.", "hi": "मैं धाराप्रवाह मराठी बोलता हूँ।"},
        probe_questions={"en": "What local language do I speak?", "hi": "मैं कौन सी स्थानीय भाषा बोलता हूँ?"},
    ),
    Fact(
        id="g_05",
        domain="family",
        entity="user",
        relation="owns_pet",
        value="dog",
        surface={"en": "I have a pet dog named Max.", "hi": "मेरे पास मैक्स नाम का एक पालतू कुत्ता है।"},
        probe_questions={"en": "What pet do I have?", "hi": "मेरे पास कौन सा पालतू जानवर है?"},
    ),
    Fact(
        id="g_06",
        domain="dining",
        entity="user",
        relation="favorite_beverage",
        value="filter_coffee",
        surface={"en": "My favorite beverage is filter coffee.", "hi": "मेरा पसंदीदा पेय फ़िल्टर कॉफ़ी है।"},
        probe_questions={"en": "What is my favorite beverage?", "hi": "मेरा पसंदीदा पेय क्या है?"},
    ),
    Fact(
        id="g_07",
        domain="finance",
        entity="user",
        relation="primary_bank",
        value="hdfc",
        surface={"en": "My salary account is with HDFC Bank.", "hi": "मेरा वेतन खाता एचडीएफसी बैंक में है।"},
        probe_questions={"en": "Which bank holds my salary account?", "hi": "मेरा वेतन खाता किस बैंक में है?"},
    ),
    Fact(
        id="g_08",
        domain="tech",
        entity="user",
        relation="primary_os",
        value="linux",
        surface={"en": "I use Linux Ubuntu on my workstation.", "hi": "मैं अपने वर्कस्टेशन पर लिनक्स उबंटू का उपयोग करता हूँ।"},
        probe_questions={"en": "What operating system do I use?", "hi": "मैं कौन सा ऑपरेटिंग सिस्टम उपयोग करता हूँ?"},
    ),
    Fact(
        id="g_09",
        domain="hobbies",
        entity="user",
        relation="plays_instrument",
        value="guitar",
        surface={"en": "I play the acoustic guitar.", "hi": "मैं अकौस्टिक गिटार बजाता हूँ।"},
        probe_questions={"en": "What musical instrument do I play?", "hi": "मैं कौन सा वाद्य यंत्र बजाता हूँ?"},
    ),
    Fact(
        id="g_10",
        domain="travel",
        entity="user",
        relation="planned_trip",
        value="manali",
        surface={"en": "I have a vacation planned for Manali next month.", "hi": "अगले महीने मेरी मनाली की छुट्टी की योजना है।"},
        probe_questions={"en": "Where am I traveling next month?", "hi": "अगले महीने मैं कहाँ यात्रा कर रहा हूँ?"},
    ),
]


def test_golden_mini_benchmark_end_to_end(tmp_path: Path) -> None:
    """Run full 10-fact pipeline through MockAdapter with stubbed LLM.

    Asserts:
      - Write Fidelity = 1.0 (all 10 facts stored)
      - Probes executed without error
      - Runs offline without GPU
    """
    out_dir = tmp_path / "golden_run"
    cfg = ExperimentConfig(
        experiment="golden_test",
        framework="mock",
        model=ModelConfig(name="qwen2.5:7b-instruct", backend="ollama"),
        languages=LanguageConfig(store="en", probe="en"),
        benchmark=BenchmarkConfig(fact_bank="dummy", n_facts=10, filler_sessions=1),
        seeds=[11],
        output_dir=str(out_dir),
    )

    llm_client = LLMClient(mock_mode=True)
    runner = ExperimentRunner(config=cfg, llm_client=llm_client)

    seed_dir = runner.run_single_seed(facts=GOLDEN_FACTS, seed=11)
    assert seed_dir.exists()
    assert (seed_dir / "store_after_plant.json").exists()
    assert (seed_dir / "store_final.json").exists()
    assert (seed_dir / "run_log.jsonl").exists()

    # Score the golden run
    scores = score_single_seed_dir(seed_dir, facts=GOLDEN_FACTS)

    # In MockAdapter, all 10 English plant turns are written directly
    assert scores["write_fidelity"] == pytest.approx(1.0, abs=1e-4)
    assert "recall_at_1_strict" in scores
    assert "duplication_rate" in scores
    assert "false_merge_rate" in scores


def test_reprobe_runs_after_correction(tmp_path: Path) -> None:
    """RE-PROBE (Session K+2) must read the POST-correction store.

    Regression test for the bug where the runner fed the Session-K probe_result
    (taken BEFORE the correction turn was ever issued) into Staleness Rate as if
    it were a re-probe -- which trivially scores every correction as stale,
    regardless of whether the framework actually applied it. g_01 is the only
    GOLDEN_FACTS entry with update_data (peanuts -> cashews), so this asserts
    directly on what each phase's retrieval actually saw in the store.
    """
    out_dir = tmp_path / "reprobe_run"
    cfg = ExperimentConfig(
        experiment="reprobe_test",
        framework="mock",
        model=ModelConfig(name="qwen2.5:7b-instruct", backend="ollama"),
        languages=LanguageConfig(store="en", probe="en"),
        benchmark=BenchmarkConfig(fact_bank="dummy", n_facts=10, filler_sessions=1),
        seeds=[11],
        output_dir=str(out_dir),
    )
    llm_client = LLMClient(mock_mode=True)
    runner = ExperimentRunner(config=cfg, llm_client=llm_client)
    seed_dir = runner.run_single_seed(facts=GOLDEN_FACTS, seed=11)

    probe_records = []
    reprobe_records = []
    with open(seed_dir / "run_log.jsonl", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec["record_type"] == "probe_result":
                probe_records.append(rec["data"])
            elif rec["record_type"] == "reprobe_result":
                reprobe_records.append(rec["data"])

    # Exactly one fact (g_01) has update_data -> exactly one re-probe, and it
    # must be logged as its own record type, not folded into probe_result.
    assert len(reprobe_records) == 1
    assert reprobe_records[0]["fact_id"] == "g_01"

    # Pre-correction probe for g_01 must NOT have seen the corrected value --
    # the correction had not happened yet when this probe ran.
    pre_correction = next(r for r in probe_records if r["fact_id"] == "g_01")
    pre_text = " ".join(m["text"] for m in pre_correction["retrieved"]).lower()
    assert "cashews" not in pre_text

    # The re-probe, running strictly after the correction turn, must see it.
    post_text = " ".join(m["text"] for m in reprobe_records[0]["retrieved"]).lower()
    assert "cashews" in post_text

    # Scoring must read reprobe_result (not probe_result) for staleness, and
    # must not error now that a real post-correction reprobe is available.
    # NOTE: this does not assert a specific staleness_rate value -- in mock_mode
    # the LLM response is a fixed truncated echo of the prompt, not a real
    # answer, so compute_staleness_rate's own judgment of that text is out of
    # scope here (it has its own unit tests). What this test verifies is that
    # the re-probe phase runs after correction and its results reach the scorer.
    scores = score_single_seed_dir(seed_dir, facts=GOLDEN_FACTS)
    assert 0.0 <= scores["staleness_rate"] <= 1.0
