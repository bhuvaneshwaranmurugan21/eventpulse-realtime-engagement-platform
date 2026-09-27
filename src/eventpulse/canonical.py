"""Canonical JSON and deterministic identifiers."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from eventpulse.errors import InvariantViolation


def _reject_floats(value: Any) -> None:
    if isinstance(value, float):
        raise InvariantViolation("canonical EventPulse values forbid floats")
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise InvariantViolation("canonical object keys must be strings")
            _reject_floats(child)
    elif isinstance(value, list):
        for child in value:
            _reject_floats(child)


def canonical_bytes(value: Any) -> bytes:
    _reject_floats(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def event_digest(event: dict[str, Any]) -> str:
    semantic = deepcopy(event)
    semantic.pop("ingest_time_ms", None)
    return canonical_sha256(semantic)


def session_id(
    contract_version: str, generation_id: str, user_id: str, member_event_ids: list[str]
) -> str:
    return canonical_sha256([contract_version, generation_id, user_id, sorted(member_event_ids)])


def valid_raw_key(event: dict[str, Any], digest: str) -> str:
    day = datetime.fromtimestamp(int(event["ingest_time_ms"]) / 1000, UTC).strftime("%Y-%m-%d")
    event_id = quote(str(event["event_id"]), safe="-_.:")
    return f"raw/schema=1.0.0/date={day}/event_id={event_id}/{digest}.json"


def rejected_raw_key(
    *, event_source_arn: str, shard_id: str, sequence_number: str, transport_text: str
) -> str:
    source_hash = sha256_bytes(event_source_arn.encode("utf-8"))
    transport_hash = sha256_bytes(transport_text.encode("ascii"))
    shard = quote(shard_id, safe="-_.")
    sequence = quote(sequence_number, safe="-_.")
    return (
        f"rejected/source={source_hash}/shard={shard}/sequence={sequence}/"
        f"transport={transport_hash}.bin"
    )


def stable_id(*parts: Any) -> str:
    return canonical_sha256(["1.0.0", *parts])


def transaction_token(*parts: Any) -> str:
    return stable_id(*parts)[:36]
