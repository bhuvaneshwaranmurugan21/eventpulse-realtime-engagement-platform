"""Kinesis/Lambda transport parsing with exact-byte preservation."""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from eventpulse.errors import DuplicateKeyError
from eventpulse.models import RejectedEvent, SourceCoordinate, TransportRecord


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise DuplicateKeyError(key)
        value[key] = child
    return value


def parse_source(record: dict[str, Any]) -> TransportRecord:
    kinesis = record.get("kinesis")
    if not isinstance(kinesis, dict):
        raise ValueError("record.kinesis must be an object")
    event_id = record.get("eventID")
    arn = record.get("eventSourceARN")
    sequence = kinesis.get("sequenceNumber")
    partition = kinesis.get("partitionKey")
    data = kinesis.get("data")
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("eventID must be a non-empty string")
    if not isinstance(arn, str) or not arn:
        raise ValueError("eventSourceARN must be a non-empty string")
    if not isinstance(sequence, str) or not sequence:
        raise ValueError("sequenceNumber must be a non-empty string")
    if not isinstance(partition, str) or not partition:
        raise ValueError("Kinesis source coordinates must be non-empty strings")
    if not isinstance(data, str):
        raise ValueError("kinesis.data must be a base64 string")
    shard_id = event_id.rsplit(":", 1)[0] if ":" in event_id else event_id
    return TransportRecord(SourceCoordinate(arn, shard_id, sequence, partition), data)


def decode_json(record: TransportRecord) -> dict[str, Any] | RejectedEvent:
    try:
        raw = base64.b64decode(record.transport_text, validate=True)
    except (binascii.Error, ValueError):
        return RejectedEvent(
            record.coordinate,
            "CORRUPT_BASE64",
            "base64 validation failed",
            record.transport_text.encode("ascii"),
            "transport_text",
            record.transport_text,
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return RejectedEvent(
            record.coordinate,
            "INVALID_UTF8",
            "decoded bytes are not UTF-8",
            raw,
            "decoded",
            record.transport_text,
        )
    try:
        value = json.loads(text, object_pairs_hook=_unique_object)
    except DuplicateKeyError:
        return RejectedEvent(
            record.coordinate,
            "DUPLICATE_JSON_KEY",
            "JSON object contains a duplicate key",
            raw,
            "decoded",
            record.transport_text,
        )
    except json.JSONDecodeError:
        return RejectedEvent(
            record.coordinate,
            "INVALID_JSON",
            "decoded UTF-8 is not valid JSON",
            raw,
            "decoded",
            record.transport_text,
        )
    if not isinstance(value, dict):
        return RejectedEvent(
            record.coordinate,
            "NON_OBJECT_JSON",
            "top-level JSON must be an object",
            raw,
            "decoded",
            record.transport_text,
        )
    return value
