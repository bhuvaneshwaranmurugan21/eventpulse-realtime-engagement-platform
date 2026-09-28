"""Application-level recovery executors used by local crash proof.

The functions in this module are production code with explicit ports.  Stage 2
executes them against durable local adapters; that evidence does not claim that
AWS services behaved durably.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from eventpulse.admission import admit
from eventpulse.canonical import canonical_bytes, sha256_bytes
from eventpulse.errors import InvariantViolation, RetryableDependencyError
from eventpulse.models import (
    AdmittedEvent,
    ApplyResult,
    RejectedEvent,
    SourceCoordinate,
    TransportRecord,
)
from eventpulse.ports import CrashProbe, OutboxPublisher, RawArchive

CRASH_BOUNDARIES = tuple(f"EP-CRASH-{number:02d}" for number in range(1, 9))


class NoopCrashProbe:
    """Production default: the probe observes nothing and changes nothing."""

    def reach(self, boundary: str, *, detail: dict[str, str]) -> None:
        del detail
        if boundary not in CRASH_BOUNDARIES:
            raise InvariantViolation(f"unknown crash boundary: {boundary}")


@dataclass(frozen=True)
class PendingOutbox:
    outbox_id: str
    body: bytes


class RecoveryStore(Protocol):
    def pending_outbox(self, limit: int) -> Sequence[PendingOutbox]: ...

    def mark_outbox_delivered(self, outbox_id: str) -> None: ...

    def register_failure_destination(
        self,
        *,
        invocation_id: str,
        object_key: str,
        body_sha256: str,
        earliest_sequence: str,
    ) -> None: ...

    def unresolved_failure_count(self) -> int: ...


class ReplayStore(RecoveryStore, Protocol):
    def isolate_rejected(self, rejected: RejectedEvent, raw_key: str) -> ApplyResult: ...

    def apply_event(
        self, admitted: AdmittedEvent, raw_key: str, generation_id: str
    ) -> ApplyResult: ...

    def drain_closures(self, shard_id: str, generation_id: str, limit: int) -> bool: ...


class FailureDestination(Protocol):
    def put_if_absent(self, key: str, body: bytes, digest: str) -> None: ...


def drain_outbox(
    store: RecoveryStore,
    publisher: OutboxPublisher,
    crash_probe: CrashProbe,
    *,
    limit: int = 20,
) -> int:
    """Publish a bounded page and mark delivery only after the send returns."""

    if not 1 <= limit <= 20:
        raise InvariantViolation("outbox page limit must be between 1 and 20")
    delivered = 0
    for message in store.pending_outbox(limit):
        publisher.publish(message.outbox_id, message.body)
        crash_probe.reach(
            "EP-CRASH-07",
            detail={"outbox_id": message.outbox_id, "step": "sent_before_marker"},
        )
        store.mark_outbox_delivered(message.outbox_id)
        delivered += 1
    return delivered


def record_exhausted_failure(
    store: RecoveryStore,
    destination: FailureDestination,
    crash_probe: CrashProbe,
    *,
    invocation_id: str,
    earliest_sequence: str,
    body: bytes,
) -> str:
    """Persist an exhausted invocation and retain unresolved adjudication authority."""

    digest = sha256_bytes(body)
    object_key = f"failure/invocation_id={invocation_id}/{digest}.json"
    destination.put_if_absent(object_key, body, digest)
    store.register_failure_destination(
        invocation_id=invocation_id,
        object_key=object_key,
        body_sha256=digest,
        earliest_sequence=earliest_sequence,
    )
    crash_probe.reach(
        "EP-CRASH-08",
        detail={
            "invocation_id": invocation_id,
            "sequence_number": earliest_sequence,
            "step": "failure_destination_unresolved",
        },
    )
    return object_key


def require_no_unresolved_failures(store: RecoveryStore) -> None:
    if store.unresolved_failure_count() != 0:
        raise InvariantViolation("unresolved failure destination blocks success")


def replay_archived_event(
    *,
    archive: RawArchive,
    store: ReplayStore,
    destination: FailureDestination,
    crash_probe: CrashProbe,
    coordinate: SourceCoordinate,
    raw_key: str,
    expected_body_sha256: str,
    expected_event_digest: str,
    generation_id: str,
    invocation_id: str,
) -> ApplyResult:
    """Replay one admitted raw event, or retain a durable unresolved failure."""

    try:
        body = archive.read(raw_key)
        if sha256_bytes(body) != expected_body_sha256:
            raise InvariantViolation("replay raw body digest mismatch")
        try:
            transport_text = body.decode("utf-8")
        except UnicodeDecodeError as error:
            raise InvariantViolation("replay raw body is not UTF-8 JSON") from error
        encoded_transport = base64.b64encode(transport_text.encode("utf-8")).decode("ascii")
        decision = admit(TransportRecord(coordinate, encoded_transport))
        if not isinstance(decision, AdmittedEvent):
            raise InvariantViolation("replay raw body no longer admits")
        if decision.digest != expected_event_digest:
            raise InvariantViolation("replay semantic digest mismatch")
    except (InvariantViolation, RetryableDependencyError):
        failure_body = canonical_bytes(
            {
                "disposition": "RAW_REPLAY_UNAVAILABLE",
                "expected_body_sha256": expected_body_sha256,
                "expected_event_digest": expected_event_digest,
                "generation_id": generation_id,
                "raw_key": raw_key,
                "sequence_number": coordinate.sequence_number,
            }
        )
        record_exhausted_failure(
            store,
            destination,
            crash_probe,
            invocation_id=invocation_id,
            earliest_sequence=coordinate.sequence_number,
            body=failure_body,
        )
        raise

    result = store.apply_event(decision, raw_key, generation_id)
    for _ in range(100):
        if not store.drain_closures(coordinate.shard_id, generation_id, 20):
            return result
    raise RetryableDependencyError("replay closure drain exceeded bounded invocation budget")
