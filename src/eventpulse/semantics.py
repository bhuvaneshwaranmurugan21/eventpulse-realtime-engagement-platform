"""Pure EventPulse identity, watermark and session semantics."""

from __future__ import annotations

from dataclasses import dataclass

ALLOWED_LATENESS_MS = 1_800_000
INACTIVITY_GAP_MS = 1_800_000
DEDUPE_HORIZON_MS = 604_800_000
IDENTITY_TTL_MS = 691_200_000


@dataclass(frozen=True)
class TimeDecision:
    category: str
    watermark_before_ms: int | None
    watermark_after_ms: int
    maximum_after_ms: int


def classify_event_time(event_time_ms: int, previous_max_ms: int | None) -> TimeDecision:
    if previous_max_ms is None:
        return TimeDecision(
            "on_time",
            None,
            event_time_ms - ALLOWED_LATENESS_MS,
            event_time_ms,
        )
    watermark_before = previous_max_ms - ALLOWED_LATENESS_MS
    if event_time_ms >= previous_max_ms:
        category = "on_time"
    elif event_time_ms >= watermark_before:
        category = "accepted_late"
    else:
        category = "beyond_watermark"
    maximum_after = max(previous_max_ms, event_time_ms)
    return TimeDecision(
        category,
        watermark_before,
        maximum_after - ALLOWED_LATENESS_MS,
        maximum_after,
    )


def identity_disposition(
    *, existing_digest: str | None, incoming_digest: str, first_ingest_ms: int, ingest_ms: int
) -> str:
    if existing_digest is None:
        return "NEW_IDENTITY"
    if ingest_ms - first_ingest_ms > DEDUPE_HORIZON_MS:
        return "EXPIRED_IDENTITY"
    if existing_digest == incoming_digest:
        return "IDENTICAL_DUPLICATE"
    return "IDENTITY_CONFLICT"


def components(events: list[tuple[str, int]]) -> list[list[tuple[str, int]]]:
    ordered = sorted(events, key=lambda value: (value[1], value[0]))
    result: list[list[tuple[str, int]]] = []
    previous: int | None = None
    for event in ordered:
        if previous is None or event[1] - previous > INACTIVITY_GAP_MS:
            result.append([])
        result[-1].append(event)
        previous = event[1]
    return result


def is_closed(*, watermark_ms: int, session_end_ms: int) -> bool:
    return watermark_ms > session_end_ms + INACTIVITY_GAP_MS
