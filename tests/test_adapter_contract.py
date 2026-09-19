"""Adapter conformance test suite.

Every adapter (MockAdapter, Mem0Adapter, LettaAdapter, AMEMAdapter) must
pass this identical conformance suite unchanged.
"""

from __future__ import annotations

import pytest
from xlmem.adapters import get_adapter
from xlmem.adapters.base import MemoryAdapter
from xlmem.benchmark.facts import Turn


@pytest.fixture(params=["mock", "mem0"])
def adapter(request: pytest.FixtureRequest) -> MemoryAdapter:
    """Fixture providing instantiated adapters to be tested."""
    return get_adapter(request.param)


def test_supports_dump_is_true(adapter: MemoryAdapter) -> None:
    """Hard Rule 7: supports_dump must be True."""
    assert adapter.supports_dump is True, f"{adapter.name} must declare supports_dump = True"


def test_write_and_dump_roundtrip(adapter: MemoryAdapter) -> None:
    """Verify that turns written are returned by dump()."""
    user_id = "test_user_dump"
    adapter.reset(user_id)

    turn1 = Turn(
        session_id=1,
        role="user",
        lang="hi",
        text="मुझे मूंगफली से एलर्जी है।",
        kind="plant",
        fact_id="f_01",
    )
    turn2 = Turn(
        session_id=1,
        role="user",
        lang="en",
        text="I work at Google in Bangalore.",
        kind="plant",
        fact_id="f_02",
    )

    res1 = adapter.write(user_id, turn1)
    res2 = adapter.write(user_id, turn2)
    assert res1.success is True
    assert res2.success is True

    dumped = adapter.dump(user_id)
    assert len(dumped) >= 2, "dump() must return all written records, not a subset or top-k"

    fact_ids = {m.metadata.get("fact_id") for m in dumped}
    assert "f_01" in fact_ids
    assert "f_02" in fact_ids

def test_dump_completeness_not_top_k(adapter: MemoryAdapter) -> None:
    """Verify that dump() returns ALL memories even when count exceeds default top-k (5)."""
    user_id = "test_user_bulk"
    adapter.reset(user_id)

    facts = [
        "My favorite color is navy blue.",
        "I work at Google in Bangalore.",
        "I have a dog named Bruno.",
        "I studied computer science at university.",
        "My birthday is on June 14.",
        "I prefer tea over coffee.",
        "I live in Chennai.",
        "My favorite programming language is Python.",
        "I enjoy playing badminton on weekends.",
        "My favorite sport is cricket.",
        "I usually exercise in the morning.",
        "My favorite food is biryani.",
    ]

    for i, fact in enumerate(facts):
        turn = Turn(
            session_id=1,
            role="user",
            lang="en",
            text=fact,
            kind="plant",
            fact_id=f"f_{i}",
        )
        adapter.write(user_id, turn)

    dumped = adapter.dump(user_id)
    assert len(dumped) == 12, f"dump() returned {len(dumped)} entries instead of all 12"


def test_retrieve_roundtrip(adapter: MemoryAdapter) -> None:
    """Verify that stored memory can be retrieved via query."""
    user_id = "test_user_retrieve"
    adapter.reset(user_id)

    turn = Turn(
        session_id=1,
        role="user",
        lang="en",
        text="My favorite color is navy blue.",
        kind="plant",
        fact_id="f_color",
    )
    adapter.write(user_id, turn)

    retrieved = adapter.retrieve(user_id, query="What is my favorite color?", lang="en", k=3)
    assert len(retrieved) >= 1
    assert any("blue" in m.text.lower() for m in retrieved)


def test_reset_isolation(adapter: MemoryAdapter) -> None:
    """Verify reset() wipes target user memory without affecting another user."""
    user_a = "user_alpha"
    user_b = "user_beta"

    adapter.reset(user_a)
    adapter.reset(user_b)

    turn_a = Turn(session_id=1, role="user", lang="en", text="Alpha favorite color is blue.", kind="plant", fact_id="f_a")
    turn_b = Turn(session_id=1, role="user", lang="en", text="Beta favorite color is green.", kind="plant", fact_id="f_b")

    adapter.write(user_a, turn_a)
    adapter.write(user_b, turn_b)

    assert len(adapter.dump(user_a)) == 1
    assert len(adapter.dump(user_b)) == 1

    # Reset only user A
    adapter.reset(user_a)
    assert len(adapter.dump(user_a)) == 0
    assert len(adapter.dump(user_b)) == 1, "User B memory was corrupted by resetting User A"


def test_update_operation(adapter: MemoryAdapter) -> None:
    """Verify update ingestion via MemoryAdapter."""
    user_id = "test_user_update"
    adapter.reset(user_id)

    turn = Turn(session_id=1, role="user", lang="en", text="I live in Delhi.", kind="plant", fact_id="f_city")
    adapter.write(user_id, turn)

    corr = Turn(session_id=2, role="user", lang="en", text="Actually I moved to Mumbai.", kind="correction", fact_id="f_city")
    u_res = adapter.update(user_id, corr)
    assert u_res.success is True

    dumped = adapter.dump(user_id)
    assert any("Mumbai" in m.text for m in dumped)
