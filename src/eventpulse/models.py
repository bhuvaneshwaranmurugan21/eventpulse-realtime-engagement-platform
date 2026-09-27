"""Immutable transport and domain models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class SourceCoordinate:
    event_source_arn: str
    shard_id: str
    sequence_number: str
    partition_key: str


@dataclass(frozen=True)
class TransportRecord:
    coordinate: SourceCoordinate
    transport_text: str


@dataclass(frozen=True)
class AdmittedEvent:
    coordinate: SourceCoordinate
    event: dict[str, Any]
    canonical: bytes
    digest: str


@dataclass(frozen=True)
class RejectedEvent:
    coordinate: SourceCoordinate
    disposition: str
    detail: str
    archive_body: bytes
    archive_representation: Literal["decoded", "transport_text"]
    transport_text: str


@dataclass(frozen=True)
class ApplyResult:
    disposition: str
    mutated_live_state: bool
    watermark_before_ms: int | None = None
    watermark_after_ms: int | None = None


@dataclass(frozen=True)
class ArchiveObject:
    key: str
    body: bytes
    sha256: str
    metadata: dict[str, str]
