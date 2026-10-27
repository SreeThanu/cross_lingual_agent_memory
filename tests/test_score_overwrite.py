"""score.py must never replace an existing scores.json unless explicitly told to.

All inputs are synthetic and live in pytest's tmp_path; no real run directory is touched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from xlmem.benchmark.facts import Fact
from xlmem.scripts import score as score_cli
from xlmem.scripts.score import score_single_seed_dir

FACT = Fact(
    id="f_1",
    domain="health",
    entity="user",
    relation="allergic_to",
    value="peanuts",
    surface={"en": "I have a severe allergy to peanuts."},
)
FACT_BANK_YAML = """facts:
  - id: "f_1"
    domain: "health"
    entity: "user"
    relation: "allergic_to"
    value: "peanuts"
    surface:
      en: "I have a severe allergy to peanuts."
"""
OLD_SCORES = b'{"metrics_version": "1", "staleness_rate": 0.333}\n'


def _seed(seed_dir: Path) -> Path:
    """Minimal seed dir: one plant turn, Snapshot A with one record, no correction."""
    seed_dir.mkdir(parents=True)
    lines = [
        {"record_type": "metadata", "seed": 11, "store_lang": "en", "probe_lang": "en"},
        {
            "record_type": "turn_trace",
            "data": {"session_id": 1, "kind": "plant", "fact_id": "f_1", "lang": "en",
                     "text": FACT.surface["en"]},
        },
    ]  # fmt: skip
    (seed_dir / "run_log.jsonl").write_text(
        "\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8"
    )
    (seed_dir / "store_after_plant.json").write_text(
        json.dumps([{"raw_id": "0", "text": "Allergic to peanuts"}]), encoding="utf-8"
    )
    (seed_dir / "store_final.json").write_text("[]", encoding="utf-8")
    return seed_dir


def test_fresh_seed_dir_is_scored_and_written(tmp_path: Path) -> None:
    seed = _seed(tmp_path / "seed_11")
    scores = score_single_seed_dir(seed, facts=[FACT])
    assert json.loads((seed / "scores.json").read_text(encoding="utf-8")) == scores
    assert scores["metrics_version"] == "2.1"


def test_existing_scores_json_is_refused_by_default_and_left_byte_identical(
    tmp_path: Path,
) -> None:
    seed = _seed(tmp_path / "seed_11")
    (seed / "scores.json").write_bytes(OLD_SCORES)
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        score_single_seed_dir(seed, facts=[FACT])
    assert (seed / "scores.json").read_bytes() == OLD_SCORES


def test_explicit_overwrite_replaces_scores_json(tmp_path: Path) -> None:
    seed = _seed(tmp_path / "seed_11")
    (seed / "scores.json").write_bytes(OLD_SCORES)
    scores = score_single_seed_dir(seed, facts=[FACT], overwrite=True)
    assert (seed / "scores.json").read_bytes() != OLD_SCORES
    assert json.loads((seed / "scores.json").read_text(encoding="utf-8")) == scores


def _run_cli(monkeypatch: pytest.MonkeyPatch, run: Path, bank: Path, *extra: str) -> int:
    argv = ["score", "--run", str(run), "--facts", str(bank), *extra]
    monkeypatch.setattr(sys, "argv", argv)
    return score_cli.main()


def test_cli_refuses_whole_run_before_writing_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One seed already scored: the CLI exits non-zero and writes nothing for any seed."""
    bank = tmp_path / "facts.yaml"
    bank.write_text(FACT_BANK_YAML, encoding="utf-8")
    run = tmp_path / "run"
    s11, s22 = _seed(run / "seed_11"), _seed(run / "seed_22")
    (s22 / "scores.json").write_bytes(OLD_SCORES)

    assert _run_cli(monkeypatch, run, bank) == 2
    assert not (s11 / "scores.json").exists()
    assert (s22 / "scores.json").read_bytes() == OLD_SCORES


def test_cli_overwrite_flag_rescores_every_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bank = tmp_path / "facts.yaml"
    bank.write_text(FACT_BANK_YAML, encoding="utf-8")
    run = tmp_path / "run"
    s11, s22 = _seed(run / "seed_11"), _seed(run / "seed_22")
    (s22 / "scores.json").write_bytes(OLD_SCORES)

    assert _run_cli(monkeypatch, run, bank, "--overwrite") == 0
    for seed in (s11, s22):
        assert (
            json.loads((seed / "scores.json").read_text(encoding="utf-8"))["metrics_version"]
            == "3"  # the CLI defaults to metrics v3
        )


def test_cli_can_still_score_with_v21(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """v2.1 stays reproducible: --metrics-version 2.1 selects the frozen path."""
    bank = tmp_path / "facts.yaml"
    bank.write_text(FACT_BANK_YAML, encoding="utf-8")
    s11 = _seed(tmp_path / "run" / "seed_11")
    assert _run_cli(monkeypatch, tmp_path / "run", bank, "--metrics-version", "2.1") == 0
    assert json.loads((s11 / "scores.json").read_text(encoding="utf-8"))["metrics_version"] == "2.1"


def test_cli_scores_a_fresh_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bank = tmp_path / "facts.yaml"
    bank.write_text(FACT_BANK_YAML, encoding="utf-8")
    run = tmp_path / "run"
    s11 = _seed(run / "seed_11")
    assert _run_cli(monkeypatch, run, bank) == 0
    assert (s11 / "scores.json").exists()
