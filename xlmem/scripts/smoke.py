"""Smoke run script for XLMem: runs 5 facts end-to-end to verify pipeline."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys
from xlmem.benchmark.facts import Fact
from xlmem.config import BenchmarkConfig, ExperimentConfig, LanguageConfig, ModelConfig
from xlmem.runner.experiment import ExperimentRunner

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("smoke")

SMOKE_FACTS = [
    Fact(
        id="smoke_1",
        domain="health",
        entity="user",
        relation="allergic_to",
        value="peanuts",
        surface={"en": "I am allergic to peanuts.", "hi": "मुझे मूंगफली से एलर्जी है।"},
        probe_questions={"en": "What food am I allergic to?", "hi": "मुझे किस चीज़ से एलर्जी है?"},
    ),
    Fact(
        id="smoke_2",
        domain="travel",
        entity="user",
        relation="lives_in",
        value="pune",
        surface={"en": "I live in Pune.", "hi": "मैं पुणे में रहता हूँ।"},
        probe_questions={"en": "Where do I live?", "hi": "मैं कहाँ रहता हूँ?"},
    ),
    Fact(
        id="smoke_3",
        domain="work",
        entity="user",
        relation="works_at",
        value="infosys",
        surface={"en": "I work at Infosys.", "hi": "मैं इंफोसिस में काम करता हूँ।"},
        probe_questions={"en": "Where do I work?", "hi": "मैं कहाँ काम करता हूँ?"},
    ),
    Fact(
        id="smoke_4",
        domain="preferences",
        entity="user",
        relation="favorite_food",
        value="biryani",
        surface={"en": "My favorite food is biryani.", "hi": "मेरा पसंदीदा खाना बिरयानी है।"},
        probe_questions={"en": "What is my favorite food?", "hi": "मेरा पसंदीदा खाना क्या है?"},
    ),
    Fact(
        id="smoke_5",
        domain="family",
        entity="user",
        relation="owns_pet",
        value="dog",
        surface={"en": "I have a pet dog.", "hi": "मेरे पास एक पालतू कुत्ता है।"},
        probe_questions={"en": "What pet do I have?", "hi": "मेरे पास कौन सा पालतू जानवर है?"},
    ),
]


def run_smoke(framework: str = "mem0", store_lang: str = "hi", probe_lang: str = "en") -> int:
    logger.info("=== Starting XLMem Smoke Run (5 facts) ===")
    logger.info("Framework: %s | Store: %s -> Probe: %s", framework, store_lang, probe_lang)

    output_dir = Path("runs") / f"smoke_{framework}_{store_lang}2{probe_lang}"
    cfg = ExperimentConfig(
        experiment=f"smoke_{framework}",
        framework=framework,  # type: ignore[arg-type]
        model=ModelConfig(name="qwen2.5:7b-instruct", backend="ollama"),
        languages=LanguageConfig(store=store_lang, probe=probe_lang),  # type: ignore[arg-type]
        benchmark=BenchmarkConfig(fact_bank="smoke", n_facts=5, filler_sessions=1),
        seeds=[11],
        output_dir=str(output_dir),
    )

    try:
        runner = ExperimentRunner(config=cfg)
        run_dir = runner.run_single_seed(facts=SMOKE_FACTS, seed=11)
        logger.info("Smoke run completed successfully. Outputs at: %s", run_dir)
        return 0
    except Exception as e:
        logger.error("Smoke run FAILED: %s", e, exc_info=True)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="XLMem Smoke Test (5 facts)")
    parser.add_argument("--framework", default="mock", help="Framework to test (mock, mem0, etc.)")
    parser.add_argument("--store-lang", default="hi", help="Plant language (hi/en)")
    parser.add_argument("--probe-lang", default="en", help="Probe language (hi/en)")
    args = parser.parse_args()
    return run_smoke(framework=args.framework, store_lang=args.store_lang, probe_lang=args.probe_lang)


if __name__ == "__main__":
    sys.exit(main())
