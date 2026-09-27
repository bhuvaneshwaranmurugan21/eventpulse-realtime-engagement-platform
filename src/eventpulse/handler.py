"""The single production Lambda/Kinesis entry path."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from eventpulse.admission import admit
from eventpulse.canonical import (
    rejected_raw_key,
    sha256_bytes,
    valid_raw_key,
)
from eventpulse.errors import InvariantViolation, RetryableDependencyError
from eventpulse.models import AdmittedEvent, ArchiveObject, RejectedEvent, TransportRecord
from eventpulse.ports import Runtime
from eventpulse.transport import parse_source

CLOSURE_PAGE_SIZE = 20
MAX_CLOSURE_PAGES_PER_RECORD = 100


def _sequence_key(sequence: str) -> tuple[int, int | str]:
    return (0, int(sequence)) if sequence.isdigit() else (1, sequence)


def _archive_rejected(runtime: Runtime, rejected: RejectedEvent) -> str:
    key = rejected_raw_key(
        event_source_arn=rejected.coordinate.event_source_arn,
        shard_id=rejected.coordinate.shard_id,
        sequence_number=rejected.coordinate.sequence_number,
        transport_text=rejected.transport_text,
    )
    runtime.archive.put_if_absent(
        ArchiveObject(
            key=key,
            body=rejected.archive_body,
            sha256=sha256_bytes(rejected.archive_body),
            metadata={
                "disposition": rejected.disposition,
                "representation": rejected.archive_representation,
            },
        )
    )
    return key


def _archive_admitted(runtime: Runtime, admitted: AdmittedEvent) -> str:
    key = valid_raw_key(admitted.event, admitted.digest)
    runtime.archive.put_if_absent(
        ArchiveObject(
            key=key,
            body=admitted.canonical,
            sha256=sha256_bytes(admitted.canonical),
            metadata={"event-digest": admitted.digest, "schema-version": "1.0.0"},
        )
    )
    return key


def _process_record(runtime: Runtime, record: TransportRecord) -> None:
    decision = admit(record)
    if isinstance(decision, RejectedEvent):
        raw_key = _archive_rejected(runtime, decision)
        result = runtime.store.isolate_rejected(decision, raw_key)
    else:
        raw_key = _archive_admitted(runtime, decision)
        result = runtime.store.apply_event(decision, raw_key, runtime.generation_id)
        for _ in range(MAX_CLOSURE_PAGES_PER_RECORD):
            if not runtime.store.drain_closures(
                decision.coordinate.shard_id, runtime.generation_id, CLOSURE_PAGE_SIZE
            ):
                break
        else:
            raise RetryableDependencyError("closure drain exceeded bounded invocation budget")

    runtime.metrics.increment("EventDisposition", dimensions={"disposition": result.disposition})
    runtime.logger.emit(
        {
            "disposition": result.disposition,
            "mutated_live_state": result.mutated_live_state,
            "sequence_number": record.coordinate.sequence_number,
            "shard_hash": sha256_bytes(record.coordinate.shard_id.encode("utf-8"))[:16],
        }
    )


def create_handler(runtime: Runtime) -> Callable[[dict[str, Any], Any], dict[str, Any]]:
    """Return the deployable handler bound to a concrete runtime."""

    def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
        del context
        records = event.get("Records")
        if not isinstance(records, list):
            raise InvariantViolation("Lambda event Records must be a list")

        grouped: dict[str, list[TransportRecord]] = defaultdict(list)
        for value in records:
            if not isinstance(value, dict):
                raise InvariantViolation("each Lambda record must be an object")
            try:
                record = parse_source(value)
            except (TypeError, ValueError) as error:
                raise InvariantViolation("invalid Kinesis wrapper") from error
            grouped[record.coordinate.shard_id].append(record)

        failures: list[tuple[str, str]] = []
        for shard_id in sorted(grouped):
            ordered = sorted(
                grouped[shard_id],
                key=lambda item: _sequence_key(item.coordinate.sequence_number),
            )
            for record in ordered:
                try:
                    _process_record(runtime, record)
                except RetryableDependencyError:
                    failures.append((shard_id, record.coordinate.sequence_number))
                    break

        ordered_failures = [
            sequence
            for _, sequence in sorted(
                failures, key=lambda value: (value[0], _sequence_key(value[1]))
            )
        ]
        return runtime.responder.response(ordered_failures)

    return handler
