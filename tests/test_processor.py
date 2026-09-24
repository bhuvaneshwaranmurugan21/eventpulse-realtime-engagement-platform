import pytest

from eventpulse import EngagementEvent, StreamProcessor
from eventpulse.processor import IdentityConflict, InjectedFailure


def event(event_id: str, user: str, kind: str, at: int, value: int = 0) -> EngagementEvent:
    return EngagementEvent(event_id, user, kind, at, at, value)  # type: ignore[arg-type]


def test_deduplication_event_time_and_late_policy() -> None:
    processor = StreamProcessor(allowed_lateness=10)
    first = event("e1", "u1", "view", 100)
    assert processor.process_batch([first]).accepted == 1
    assert processor.process_batch([first]).duplicates == 1
    processor.process_batch([event("e2", "u2", "view", 200)])
    assert processor.process_batch([event("e3", "u1", "click", 150)]).late == 1
    with pytest.raises(IdentityConflict):
        processor.process_batch([event("e1", "u1", "click", 100)])


def test_atomic_checkpoint_and_restore() -> None:
    processor = StreamProcessor()
    processor.process_batch([event("e1", "u1", "view", 100)])
    checkpoint = processor.checkpoint()
    with pytest.raises(InjectedFailure):
        processor.process_batch([event("e2", "u1", "purchase", 101, 500)], fail_before_checkpoint=True)
    assert processor.checkpoint() == checkpoint
    restored = StreamProcessor.restore(checkpoint)
    assert restored.checkpoint() == checkpoint


def test_poison_and_partition_metrics() -> None:
    processor = StreamProcessor(partitions=2)
    poison = EngagementEvent("bad", "", "view", 1, 1)
    assert processor.process_batch([poison]).quarantined == 1
    processor.process_batch([event(f"e{i}", "same", "view", i + 1) for i in range(5)])
    assert processor.hottest_partition_ratio() == 1.0


def test_sessions_and_purchase_value() -> None:
    processor = StreamProcessor(session_gap=10)
    processor.process_batch([event("e1", "u", "view", 1), event("e2", "u", "purchase", 20, 100)])
    assert processor.sessions["u"][2] == 2
    assert processor.purchases["u"] == 100

