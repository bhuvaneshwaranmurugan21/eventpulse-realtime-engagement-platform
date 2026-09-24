from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Literal

EventType = Literal["view", "click", "purchase"]


def digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class EngagementEvent:
    event_id: str
    user_id: str
    event_type: EventType
    event_time: int
    ingested_at: int
    value_cents: int = 0

    @property
    def payload_digest(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True, slots=True)
class BatchResult:
    accepted: int
    duplicates: int
    late: int
    quarantined: int
    watermark: int
    checkpoint_digest: str


@dataclass(frozen=True, slots=True)
class Checkpoint:
    event_digests: tuple[tuple[str, str], ...]
    counts: tuple[tuple[str, str, int], ...]
    purchases: tuple[tuple[str, int], ...]
    sessions: tuple[tuple[str, int, int, int], ...]
    max_event_time: int
    late_event_ids: tuple[str, ...]
    quarantined_ids: tuple[str, ...]
    partition_load: tuple[int, ...]

    @property
    def checkpoint_digest(self) -> str:
        return digest(asdict(self))

