"""Unit tests for the session script generator (xlmem/benchmark/generator.py)
and near-miss distractor pairing (xlmem/benchmark/distractors.py).

All fixtures are small, hand-constructed Fact objects. No GPU, no model calls,
no adapters -- this tests pure functions that only ever touch the Fact/Turn
dataclasses, per BENCHMARK_SPEC.md Section 5 (session structure) and Section 4
(near-miss distractor construction).
"""

from __future__ import annotations

from xlmem.benchmark.distractors import find_distractor_pairs
from xlmem.benchmark.facts import Fact
from xlmem.benchmark.generator import build_session_script


def _fact(
    id: str,
    entity: str = "user",
    relation: str = "lives_in",
    value: str = "pune",
    distractor_of: str | None = None,
    with_probe_questions: bool = True,
    with_update: bool = False,
) -> Fact:
    """Minimal valid Fact fixture with all three surface languages."""
    surface = {"en": f"en:{id}:{value}", "hi": f"hi:{id}:{value}", "hi-en": f"hien:{id}:{value}"}
    probe_questions = (
        {"en": f"en-q:{relation}", "hi": f"hi-q:{relation}", "hi-en": f"hien-q:{relation}"}
        if with_probe_questions
        else {}
    )
    update_data = None
    if with_update:
        update_data = {
            "updated_value": f"{value}_updated",
            "surface": {
                "en": f"en:{id}:UPDATE",
                "hi": f"hi:{id}:UPDATE",
                "hi-en": f"hien:{id}:UPDATE",
            },
            "probe_questions": {"en": f"en-q:{relation}:now", "hi": f"hi-q:{relation}:now"},
        }
    return Fact(
        id=id,
        domain="travel",
        entity=entity,
        relation=relation,
        value=value,
        surface=surface,
        distractor_of=distractor_of,
        probe_questions=probe_questions,
        update_data=update_data,
    )


# ---------------------------------------------------------------------------
# build_session_script: phase ordering
# ---------------------------------------------------------------------------


def test_phases_occur_in_strictly_increasing_session_ids() -> None:
    """PLANT -> FILLER -> PROBE -> CORRECTION -> RE-PROBE, per BENCHMARK_SPEC.md Section 5."""
    facts = [
        _fact("f_001", with_update=True),
        _fact("f_002", entity="user", relation="works_at", value="infosys"),
        _fact("f_001_dist", entity="user_sister", distractor_of="f_001"),
    ]
    turns = build_session_script(
        facts, store_lang="en", probe_lang="en", filler_sessions=2, seed=11
    )

    plant_ids = {t.session_id for t in turns if t.kind == "plant"}
    filler_ids = {t.session_id for t in turns if t.kind == "filler"}
    probe_ids = sorted({t.session_id for t in turns if t.kind == "probe"})
    correction_ids = {t.session_id for t in turns if t.kind == "correction"}

    assert plant_ids == {1}
    assert filler_ids == {2, 3}  # filler_sessions=2 -> sessions 2 and 3
    # Two probe sessions: the pre-correction probe and the re-probe.
    assert len(probe_ids) == 2
    pre_correction_session, reprobe_session = probe_ids
    assert correction_ids == {pre_correction_session + 1}
    assert reprobe_session == pre_correction_session + 2

    # Strict ordering across every phase.
    assert max(plant_ids) < min(filler_ids)
    assert max(filler_ids) < pre_correction_session
    assert pre_correction_session < min(correction_ids)
    assert max(correction_ids) < reprobe_session


def test_no_correction_or_reprobe_session_when_no_updateable_facts() -> None:
    """A fact bank with no update_data must not synthesize a correction/re-probe phase."""
    facts = [_fact("f_001", with_update=False), _fact("f_002", with_update=False)]
    turns = build_session_script(
        facts, store_lang="en", probe_lang="en", filler_sessions=1, seed=11
    )

    assert not any(t.kind == "correction" for t in turns)
    probe_sessions = {t.session_id for t in turns if t.kind == "probe"}
    assert len(probe_sessions) == 1, "no corrections means no re-probe session either"


# ---------------------------------------------------------------------------
# build_session_script: probe / re-probe placement and pairing
# ---------------------------------------------------------------------------


def test_probe_session_covers_every_base_fact_exactly_once() -> None:
    facts = [
        _fact("f_001", relation="allergic_to", value="peanuts"),
        _fact("f_002", relation="works_at", value="infosys"),
        _fact(
            "f_001_dist",
            entity="user_sister",
            relation="allergic_to",
            value="peanuts",
            distractor_of="f_001",
        ),
    ]
    turns = build_session_script(
        facts, store_lang="en", probe_lang="en", filler_sessions=1, seed=11
    )

    probe_ids = sorted({t.session_id for t in turns if t.kind == "probe"})
    pre_correction_session = probe_ids[0]
    pre_correction_probes = [
        t for t in turns if t.kind == "probe" and t.session_id == pre_correction_session
    ]

    # Exactly one probe per BASE fact (distractors are never probed directly).
    assert sorted(str(t.fact_id) for t in pre_correction_probes) == ["f_001", "f_002"]


def test_reprobe_covers_exactly_the_corrected_subset_and_nothing_else() -> None:
    """Correction/re-probe pairing: only facts selected for update get a correction
    turn AND a matching re-probe turn; facts without update_data get neither."""
    facts = [
        _fact("f_001", relation="allergic_to", value="peanuts", with_update=True),
        _fact("f_002", relation="works_at", value="infosys", with_update=False),
    ]
    turns = build_session_script(
        facts, store_lang="en", probe_lang="en", filler_sessions=1, update_subset_ratio=1.0, seed=11
    )

    correction_fact_ids = {t.fact_id for t in turns if t.kind == "correction"}
    probe_ids = sorted({t.session_id for t in turns if t.kind == "probe"})
    reprobe_fact_ids = {
        t.fact_id for t in turns if t.kind == "probe" and t.session_id == probe_ids[-1]
    }

    assert correction_fact_ids == {"f_001"}
    assert reprobe_fact_ids == {"f_001"}
    assert "f_002" not in correction_fact_ids
    assert "f_002" not in reprobe_fact_ids


def test_reprobe_uses_update_specific_question_with_fallback() -> None:
    """Re-probe text must come from update.probe_questions[probe_lang] when present,
    falling back to the base probe_questions[probe_lang] when the update block has
    no question for that language (BENCHMARK_SPEC.md Section 2.1: update.probe_questions
    is only documented with hi/en, never hi-en)."""
    fact_with_update_question = _fact(
        "f_001", with_update=True
    )  # has en/hi update question, no hi-en
    turns_en = build_session_script(
        [fact_with_update_question],
        store_lang="en",
        probe_lang="en",
        filler_sessions=0,
        update_subset_ratio=1.0,
        seed=11,
    )
    reprobe_ids = sorted({t.session_id for t in turns_en if t.kind == "probe"})
    reprobe_turn = next(
        t for t in turns_en if t.kind == "probe" and t.session_id == reprobe_ids[-1]
    )
    assert (
        reprobe_turn.text == "en-q:lives_in:now"
    )  # the update-specific question, not the base one

    # probe_lang="hi-en": update.probe_questions has no hi-en key -> must fall back
    # to the base fact's probe_questions["hi-en"], not silently produce an error
    # or empty text.
    turns_hien = build_session_script(
        [fact_with_update_question],
        store_lang="en",
        probe_lang="hi-en",
        filler_sessions=0,
        update_subset_ratio=1.0,
        seed=11,
    )
    reprobe_ids2 = sorted({t.session_id for t in turns_hien if t.kind == "probe"})
    reprobe_turn2 = next(
        t for t in turns_hien if t.kind == "probe" and t.session_id == reprobe_ids2[-1]
    )
    assert reprobe_turn2.text == "hien-q:lives_in"  # base probe_questions["hi-en"] fallback
    assert reprobe_turn2.text != ""


# ---------------------------------------------------------------------------
# build_session_script: determinism
# ---------------------------------------------------------------------------


def test_same_seed_produces_identical_output() -> None:
    facts = [
        _fact("f_001", with_update=True),
        _fact("f_002", relation="works_at", value="infosys"),
        _fact("f_003", relation="speaks_language", value="marathi"),
        _fact("f_001_dist", entity="user_sister", distractor_of="f_001"),
        _fact(
            "f_002_dist",
            entity="user_father",
            relation="works_at",
            value="google",
            distractor_of="f_002",
        ),
    ]
    turns_a = build_session_script(
        facts, store_lang="hi", probe_lang="en", filler_sessions=3, seed=7
    )
    turns_b = build_session_script(
        facts, store_lang="hi", probe_lang="en", filler_sessions=3, seed=7
    )

    assert turns_a == turns_b


def test_different_seeds_can_change_filler_distractor_order() -> None:
    """Not a strict requirement, but the seed exists specifically to control the
    filler/distractor shuffle -- confirm it actually has an effect, otherwise the
    'seed' parameter would be dead code masquerading as reproducibility control."""
    facts = [
        _fact("f_001"),
        _fact("f_002", relation="works_at", value="infosys"),
        _fact("f_001_dist", entity="user_sister", distractor_of="f_001"),
        _fact(
            "f_002_dist",
            entity="user_father",
            relation="works_at",
            value="google",
            distractor_of="f_002",
        ),
    ]
    turns_seed_a = build_session_script(
        facts, store_lang="en", probe_lang="en", filler_sessions=2, seed=1
    )
    turns_seed_b = build_session_script(
        facts, store_lang="en", probe_lang="en", filler_sessions=2, seed=99
    )

    filler_order_a = [t.fact_id for t in turns_seed_a if t.kind == "filler"]
    filler_order_b = [t.fact_id for t in turns_seed_b if t.kind == "filler"]
    assert filler_order_a != filler_order_b


# ---------------------------------------------------------------------------
# find_distractor_pairs: distractor identification
# ---------------------------------------------------------------------------


def test_find_distractor_pairs_matches_by_explicit_reference() -> None:
    base_a = _fact("f_001", relation="allergic_to", value="peanuts")
    dist_a = _fact(
        "f_001_dist",
        entity="user_sister",
        relation="allergic_to",
        value="peanuts",
        distractor_of="f_001",
    )
    base_b = _fact("f_002", relation="works_at", value="infosys")
    dist_b = _fact(
        "f_002_dist",
        entity="user_father",
        relation="works_at",
        value="google",
        distractor_of="f_002",
    )

    pairs = find_distractor_pairs([base_a, dist_a, base_b, dist_b])

    assert len(pairs) == 2
    assert (base_a, dist_a) in pairs
    assert (base_b, dist_b) in pairs


def test_find_distractor_pairs_does_not_cross_pair_when_interleaved_and_shuffled() -> None:
    """No accidental cross-fact pairing: with multiple base/distractor pairs given
    in a shuffled, interleaved order, each distractor must pair ONLY with the base
    fact its own distractor_of names -- never with a different base fact, even one
    that shares domain/relation/value characteristics."""
    base_a = _fact("f_001", entity="user", relation="allergic_to", value="peanuts")
    dist_a = _fact(
        "f_001_dist",
        entity="user_sister",
        relation="allergic_to",
        value="peanuts",
        distractor_of="f_001",
    )
    base_b = _fact(
        "f_002", entity="user", relation="allergic_to", value="peanuts"
    )  # same relation+value as f_001!
    dist_b = _fact(
        "f_002_dist",
        entity="user_mother",
        relation="allergic_to",
        value="peanuts",
        distractor_of="f_002",
    )

    # Deliberately interleaved order, not grouped by pair.
    pairs = find_distractor_pairs([dist_b, base_a, dist_a, base_b])

    assert len(pairs) == 2
    pairs_by_distractor_id = {d.id: (b, d) for b, d in pairs}
    assert pairs_by_distractor_id["f_001_dist"] == (base_a, dist_a)
    assert pairs_by_distractor_id["f_002_dist"] == (base_b, dist_b)
    # f_001_dist must never be paired with base_b, nor f_002_dist with base_a.
    assert pairs_by_distractor_id["f_001_dist"][0] is not base_b
    assert pairs_by_distractor_id["f_002_dist"][0] is not base_a


def test_find_distractor_pairs_ignores_dangling_reference() -> None:
    """A distractor whose distractor_of points at a fact_id not present in the
    given collection is silently excluded, not paired with an unrelated fact and
    not raising. Schema-level malformation (an unresolvable distractor_of) is
    xlmem/benchmark/validate.py's job to catch before this ever runs."""
    base_a = _fact("f_001")
    orphan_dist = _fact("f_999_dist", entity="user_sister", distractor_of="f_does_not_exist")

    pairs = find_distractor_pairs([base_a, orphan_dist])

    assert pairs == []


def test_find_distractor_pairs_handles_entity_shift_and_value_shift_forms() -> None:
    """Section 4 defines two near-miss forms. find_distractor_pairs itself is
    shift-type-agnostic (pairing is purely by distractor_of reference) -- this
    confirms both authored forms pair correctly and are not mishandled or
    conflated with each other."""
    base = _fact("f_001", entity="user", relation="allergic_to", value="peanuts")
    entity_shift = _fact(
        "f_001_dist_entity",
        entity="user_sister",
        relation="allergic_to",
        value="peanuts",
        distractor_of="f_001",
    )
    value_shift = _fact(
        "f_001_dist_value",
        entity="user",
        relation="allergic_to",
        value="walnuts",
        distractor_of="f_001",
    )

    pairs = find_distractor_pairs([base, entity_shift, value_shift])

    assert len(pairs) == 2
    paired_distractor_ids = {d.id for _, d in pairs}
    assert paired_distractor_ids == {"f_001_dist_entity", "f_001_dist_value"}
    for b, d in pairs:
        assert b is base  # both distractors correctly resolve back to the same base fact
