"""Mixed-language writes against the live frameworks (OPEN_ISSUES §1.2).

Not part of the adapter contract: whether a framework *succeeds* on a mixed
Hindi/English conversation is what the experiments measure, so nothing here
requires success. It checks what the runner relies on: a failed write is
reported as WriteResult(success=False), not raised, and the store stays
dumpable.

The success flag is NOT ground truth, and the scorer rightly ignores it: Write
Fidelity reads dump(). On 2026-10-18 Letta reported a Hindi write as failed
although the fact was stored (its 502 comes after the memory tool call), and
Mem0 reported success while its reconciliation dropped an earlier fact.

Run with:  pytest tests/test_mixed_language_probe.py -m gpu -s
"""

from __future__ import annotations

import pytest

from xlmem.adapters import get_adapter
from xlmem.benchmark.facts import Turn

SEQUENCES = {
    "hi_then_en": [("hi", "मुझे मूंगफली से एलर्जी है।"), ("en", "I work at Google in Bangalore.")],
    "en_then_hi": [("en", "I work at Google in Bangalore."), ("hi", "मुझे मूंगफली से एलर्जी है।")],
}


@pytest.mark.gpu
@pytest.mark.parametrize("sequence", sorted(SEQUENCES))
@pytest.mark.parametrize("framework", ["mem0", "letta", "amem"])
def test_mixed_language_writes_fail_softly(framework: str, sequence: str) -> None:
    adapter = get_adapter(framework)
    user_id = f"mixed_probe_{sequence}"
    adapter.reset(user_id)

    outcomes = []
    for i, (lang, text) in enumerate(SEQUENCES[sequence]):
        turn = Turn(session_id=1, role="user", lang=lang, text=text, kind="plant",
                    fact_id=f"f_{i}")
        result = adapter.write(user_id, turn)  # must not raise
        outcomes.append(f"{lang}:{'ok' if result.success else 'FAILED'}")

    stored = [m.text.strip() for m in adapter.dump(user_id)]  # must stay dumpable
    print(f"\n[{framework} {sequence}] writes {outcomes} | stored {stored}")
    adapter.reset(user_id)
