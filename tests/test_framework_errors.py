"""Framework-internal errors that are logged, not raised, reach the run log per turn."""

from __future__ import annotations

import logging
import os

from xlmem.adapters.base import UpdateResult, WriteResult, capture_framework_errors
from xlmem.adapters.mock_adapter import MockAdapter
from xlmem.benchmark.facts import Turn
from xlmem.runner.session import SessionRunner


def _record(pathname: str, level: int, msg: str) -> logging.LogRecord:
    return logging.LogRecord("root", level, pathname, 1, msg, None, None)


def test_only_errors_from_the_named_package_are_collected() -> None:
    root = logging.getLogger()
    mem0_file = os.path.join(os.sep, "site-packages", "mem0", "memory", "main.py")
    other_file = os.path.join(os.sep, "site-packages", "chromadb", "api.py")
    with capture_framework_errors("mem0") as errors:
        msg = "Error in new_memories_with_actions: 'event'"
        root.handle(_record(mem0_file, logging.ERROR, msg))
        root.handle(_record(mem0_file, logging.WARNING, "a warning"))
        root.handle(_record(other_file, logging.ERROR, "someone else's error"))
        # A package whose name merely contains "mem0" is not mem0.
        root.handle(_record(os.path.join(os.sep, "x", "notmem0", "a.py"), logging.ERROR, "no"))
    root.handle(_record(mem0_file, logging.ERROR, "after the block"))
    assert errors == [msg]


class _SoftFailingAdapter(MockAdapter):
    def write(self, user_id: str, turn: Turn) -> WriteResult:
        super().write(user_id, turn)
        return WriteResult(success=True, metadata={"framework_errors": ["evolution failed"],
                                                   "response": object()})

    def update(self, user_id: str, correction: Turn) -> UpdateResult:
        return UpdateResult(success=False, metadata={"error": "502 Bad Gateway"})


def test_session_trace_records_errors_and_drops_other_metadata() -> None:
    runner = SessionRunner(adapter=_SoftFailingAdapter(), user_id="u")
    turns = [
        Turn(session_id=1, role="user", lang="hi", text="t1", kind="plant", fact_id="f_1"),
        Turn(session_id=2, role="user", lang="hi", text="t2", kind="correction", fact_id="f_1"),
    ]
    plant, correction = runner.run_session(turns)
    assert plant["framework_errors"] == ["evolution failed"] and plant["error"] is None
    assert "response" not in plant  # arbitrary framework objects never reach the log
    assert correction["error"] == "502 Bad Gateway" and correction["framework_errors"] == []

