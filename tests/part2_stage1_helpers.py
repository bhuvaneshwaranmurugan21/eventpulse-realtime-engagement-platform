"""Literal Kinesis fixtures for Part 2 Stage 1 tests."""

from __future__ import annotations

import base64
import json
from copy import deepcopy
from typing import Any


def event(
    event_id: str,
    event_time_ms: int,
    *,
    ingest_time_ms: int | None = None,
    user_id: str = "user-a",
    event_type: str = "view",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "event_id": event_id,
        "source": "web",
        "user_id": user_id,
        "event_type": event_type,
        "event_time_ms": event_time_ms,
        "ingest_time_ms": event_time_ms if ingest_time_ms is None else ingest_time_ms,
        "partition_key": user_id,
        "payload": {} if payload is None else deepcopy(payload),
    }


def record(
    value: dict[str, Any] | bytes | str,
    sequence: str,
    *,
    shard: str = "shard-a",
    partition_key: str | None = None,
) -> dict[str, Any]:
    if isinstance(value, dict):
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        key = str(value.get("partition_key", "unknown")) if partition_key is None else partition_key
    elif isinstance(value, str):
        raw = value.encode("utf-8")
        key = "user-a" if partition_key is None else partition_key
    else:
        raw = value
        key = "user-a" if partition_key is None else partition_key
    return {
        "eventID": f"{shard}:{sequence}",
        "eventSourceARN": ("arn:aws:kinesis:ap-south-2:test-account:stream/eventpulse-test"),
        "eventSource": "aws:kinesis",
        "awsRegion": "ap-south-2",
        "kinesis": {
            "partitionKey": key,
            "sequenceNumber": sequence,
            "data": base64.b64encode(raw).decode("ascii"),
        },
    }


def batch(*records: dict[str, Any]) -> dict[str, Any]:
    return {"Records": list(records)}
