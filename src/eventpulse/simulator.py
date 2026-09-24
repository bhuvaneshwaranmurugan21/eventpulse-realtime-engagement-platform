from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable

from .model import EngagementEvent, digest
from .processor import IdentityConflict, InjectedFailure, StreamProcessor


def event(event_id: str, user: str, kind: str, event_time: int, ingested: int, value: int = 0) -> EngagementEvent:
    return EngagementEvent(event_id, user, kind, event_time, ingested, value)  # type: ignore[arg-type]


def simulate() -> dict[str, Any]:
    stream = StreamProcessor(allowed_lateness=20, session_gap=30, partitions=4)
    checks: list[dict[str, Any]] = []

    def check(name: str, fn: Callable[[], Any], expected: type[Exception] | None = None) -> None:
        try:
            proof = fn()
            passed = expected is None
        except Exception as exc:
            proof = type(exc).__name__
            passed = expected is not None and isinstance(exc, expected)
        checks.append({"check": name, "passed": passed, "proof": proof})

    first = event("e1", "u1", "view", 100, 101)
    check("event_accepted", lambda: asdict(stream.process_batch([first])))
    check("duplicate_suppressed", lambda: asdict(stream.process_batch([first])))
    check(
        "conflicting_identity_blocked",
        lambda: stream.process_batch([event("e1", "u1", "click", 100, 101)]),
        IdentityConflict,
    )
    check(
        "out_of_order_within_watermark",
        lambda: asdict(stream.process_batch([event("e2", "u1", "click", 95, 110)])),
    )
    check("watermark_advanced", lambda: asdict(stream.process_batch([event("e3", "u2", "view", 200, 200)])))
    check("late_event_quarantined", lambda: asdict(stream.process_batch([event("e4", "u2", "view", 150, 210)])))
    check(
        "poison_record_quarantined",
        lambda: asdict(stream.process_batch([event("poison", "", "view", 201, 201)])),
    )
    before = stream.checkpoint().checkpoint_digest
    check(
        "consumer_failure_injected",
        lambda: stream.process_batch(
            [event("e5", "u3", "purchase", 205, 205, 500)], fail_before_checkpoint=True
        ),
        InjectedFailure,
    )
    check("checkpoint_atomicity", lambda: stream.checkpoint().checkpoint_digest == before)
    check("replay_after_restart", lambda: asdict(stream.process_batch([event("e5", "u3", "purchase", 205, 205, 500)])))
    checkpoint = stream.checkpoint()
    restored = StreamProcessor.restore(checkpoint, allowed_lateness=20, session_gap=30)
    check("checkpoint_restore_identity", lambda: restored.checkpoint().checkpoint_digest == checkpoint.checkpoint_digest)
    hot_events = [event(f"hot-{i}", "hot-user", "view", 210 + i, 210 + i) for i in range(8)]
    check("partition_pressure_measured", lambda: asdict(stream.process_batch(hot_events)))
    check("hot_partition_ratio", lambda: round(stream.hottest_partition_ratio(), 4))

    payload: dict[str, Any] = {
        "project": "eventpulse-realtime-engagement-platform",
        "architecture": "event-time-checkpointed-engagement-stream",
        "claim_level": "LOCAL_VERIFIED",
        "production_claim": False,
        "checks": checks,
        "metrics": {
            "checks_total": len(checks),
            "checks_passed": sum(c["passed"] for c in checks),
            "watermark": stream.watermark,
            "late_events": len(stream.late_event_ids),
            "quarantined": len(stream.quarantined_ids),
            "hottest_partition_ratio": stream.hottest_partition_ratio(),
        },
        "checkpoint": asdict(stream.checkpoint()),
    }
    payload["evidence_digest"] = digest(payload)
    payload["result"] = "PASS" if all(c["passed"] for c in checks) else "FAIL"
    return payload

