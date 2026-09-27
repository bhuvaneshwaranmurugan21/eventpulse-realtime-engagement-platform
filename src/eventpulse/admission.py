"""Frozen EventPulse envelope admission pipeline."""

from __future__ import annotations

import base64
import json
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator

from eventpulse.canonical import canonical_bytes, event_digest
from eventpulse.errors import InvariantViolation
from eventpulse.models import AdmittedEvent, RejectedEvent, TransportRecord
from eventpulse.transport import decode_json

MAX_ENCODED_BYTES = 16_384
MAX_FUTURE_MS = 60_000
MAX_AGE_MS = 604_800_000
PROHIBITED_PAYLOAD_FIELDS = {
    "address",
    "credential",
    "email",
    "free_text",
    "name",
    "password",
    "phone",
    "secret",
    "token",
}


def _schema() -> dict[str, Any]:
    resource = files("eventpulse").joinpath("resources/engagement-event-v1.schema.json")
    value = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("packaged schema must be an object")
    return value


VALIDATOR = Draft202012Validator(_schema())


def _rejected(
    record: TransportRecord,
    disposition: str,
    detail: str,
    body: bytes,
) -> RejectedEvent:
    return RejectedEvent(
        coordinate=record.coordinate,
        disposition=disposition,
        detail=detail,
        archive_body=body,
        archive_representation="decoded",
        transport_text=record.transport_text,
    )


def admit(record: TransportRecord) -> AdmittedEvent | RejectedEvent:
    decoded = decode_json(record)
    if isinstance(decoded, RejectedEvent):
        return decoded
    original = base64.b64decode(record.transport_text, validate=True)

    try:
        encoded = canonical_bytes(decoded)
    except InvariantViolation:
        # A JSON float is valid JSON but not valid EventPulse canonical data.
        return _rejected(record, "INVALID_SCHEMA", "floats are forbidden", original)

    if len(encoded) > MAX_ENCODED_BYTES:
        return _rejected(record, "EVENT_TOO_LARGE", "canonical event exceeds 16384 bytes", original)

    payload = decoded.get("payload")
    if isinstance(payload, dict) and set(payload) & PROHIBITED_PAYLOAD_FIELDS:
        return _rejected(record, "PRIVACY_VIOLATION", "payload contains prohibited key", original)

    errors = sorted(VALIDATOR.iter_errors(decoded), key=lambda error: list(error.absolute_path))
    if errors:
        return _rejected(record, "INVALID_SCHEMA", errors[0].message, original)

    # jsonschema considers bool an integer; the EventPulse authority does not.
    for field in ("event_time_ms", "ingest_time_ms"):
        if isinstance(decoded[field], bool):
            return _rejected(record, "INVALID_SCHEMA", f"{field} cannot be boolean", original)
    value_cents = decoded["payload"].get("value_cents")
    if isinstance(value_cents, bool):
        return _rejected(record, "INVALID_SCHEMA", "value_cents cannot be boolean", original)

    if decoded["partition_key"] != decoded["user_id"]:
        return _rejected(
            record, "PARTITION_MISMATCH", "envelope partition_key differs from user_id", original
        )
    if record.coordinate.partition_key != decoded["partition_key"]:
        return _rejected(
            record,
            "PARTITION_MISMATCH",
            "Kinesis partition key differs from envelope partition_key",
            original,
        )

    delta = int(decoded["event_time_ms"]) - int(decoded["ingest_time_ms"])
    if delta > MAX_FUTURE_MS:
        return _rejected(record, "FUTURE_CLOCK", "event clock is too far in the future", original)
    if -delta > MAX_AGE_MS:
        return _rejected(record, "TOO_OLD", "event exceeds maximum source age", original)

    return AdmittedEvent(record.coordinate, decoded, encoded, event_digest(decoded))
