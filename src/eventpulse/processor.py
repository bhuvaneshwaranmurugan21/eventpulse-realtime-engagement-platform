from __future__ import annotations

from collections import Counter
from hashlib import sha256
from typing import Iterable

from .model import BatchResult, Checkpoint, EngagementEvent


class ContractViolation(ValueError):
    pass


class IdentityConflict(ValueError):
    pass


class InjectedFailure(RuntimeError):
    pass


class StreamProcessor:
    """Reference event-time processor with atomic micro-batches and checkpoints."""

    def __init__(self, *, allowed_lateness: int = 30, session_gap: int = 60, partitions: int = 4):
        if allowed_lateness < 0 or session_gap <= 0 or partitions <= 0:
            raise ValueError("stream configuration must be positive")
        self.allowed_lateness = allowed_lateness
        self.session_gap = session_gap
        self.partitions = partitions
        self.event_digests: dict[str, str] = {}
        self.counts: Counter[tuple[str, str]] = Counter()
        self.purchases: Counter[str] = Counter()
        self.sessions: dict[str, tuple[int, int, int]] = {}
        self.max_event_time = 0
        self.late_event_ids: list[str] = []
        self.quarantined_ids: list[str] = []
        self.partition_load: list[int] = [0] * partitions

    @property
    def watermark(self) -> int:
        return self.max_event_time - self.allowed_lateness

    def process_batch(
        self, events: Iterable[EngagementEvent], *, fail_before_checkpoint: bool = False
    ) -> BatchResult:
        event_digests = self.event_digests.copy()
        counts = self.counts.copy()
        purchases = self.purchases.copy()
        sessions = self.sessions.copy()
        max_event_time = self.max_event_time
        late_ids = self.late_event_ids.copy()
        quarantined = self.quarantined_ids.copy()
        partition_load = self.partition_load.copy()
        accepted = duplicates = late = quarantined_count = 0

        materialized = tuple(events)
        if materialized:
            max_event_time = max(max_event_time, max(event.event_time for event in materialized))
        batch_watermark = max_event_time - self.allowed_lateness

        for event in materialized:
            if not self._valid(event):
                quarantined.append(event.event_id)
                quarantined_count += 1
                continue
            known = event_digests.get(event.event_id)
            if known is not None:
                if known != event.payload_digest:
                    raise IdentityConflict(f"event {event.event_id} changed payload")
                duplicates += 1
                continue
            event_digests[event.event_id] = event.payload_digest
            if event.event_time < batch_watermark:
                late_ids.append(event.event_id)
                late += 1
                continue
            counts[(event.user_id, event.event_type)] += 1
            if event.event_type == "purchase":
                purchases[event.user_id] += event.value_cents
            self._update_session(event, sessions)
            partition_load[self.partition_for(event.user_id)] += 1
            accepted += 1

        if fail_before_checkpoint:
            raise InjectedFailure("consumer failed before checkpoint commit")

        self.event_digests = event_digests
        self.counts = counts
        self.purchases = purchases
        self.sessions = sessions
        self.max_event_time = max_event_time
        self.late_event_ids = late_ids
        self.quarantined_ids = quarantined
        self.partition_load = partition_load
        checkpoint = self.checkpoint()
        return BatchResult(
            accepted,
            duplicates,
            late,
            quarantined_count,
            self.watermark,
            checkpoint.checkpoint_digest,
        )

    def checkpoint(self) -> Checkpoint:
        return Checkpoint(
            tuple(sorted(self.event_digests.items())),
            tuple(sorted((user, kind, value) for (user, kind), value in self.counts.items())),
            tuple(sorted(self.purchases.items())),
            tuple(sorted((user, *state) for user, state in self.sessions.items())),
            self.max_event_time,
            tuple(self.late_event_ids),
            tuple(self.quarantined_ids),
            tuple(self.partition_load),
        )

    @classmethod
    def restore(
        cls,
        checkpoint: Checkpoint,
        *,
        allowed_lateness: int = 30,
        session_gap: int = 60,
    ) -> "StreamProcessor":
        processor = cls(
            allowed_lateness=allowed_lateness,
            session_gap=session_gap,
            partitions=len(checkpoint.partition_load),
        )
        processor.event_digests = dict(checkpoint.event_digests)
        processor.counts = Counter({(user, kind): value for user, kind, value in checkpoint.counts})
        processor.purchases = Counter(dict(checkpoint.purchases))
        processor.sessions = {user: (start, last, count) for user, start, last, count in checkpoint.sessions}
        processor.max_event_time = checkpoint.max_event_time
        processor.late_event_ids = list(checkpoint.late_event_ids)
        processor.quarantined_ids = list(checkpoint.quarantined_ids)
        processor.partition_load = list(checkpoint.partition_load)
        return processor

    def partition_for(self, user_id: str) -> int:
        return int.from_bytes(sha256(user_id.encode()).digest()[:4], "big") % self.partitions

    def hottest_partition_ratio(self) -> float:
        total = sum(self.partition_load)
        return 0.0 if total == 0 else max(self.partition_load) / total

    def _valid(self, event: EngagementEvent) -> bool:
        return bool(
            event.event_id
            and event.user_id
            and event.event_type in {"view", "click", "purchase"}
            and event.event_time >= 0
            and event.ingested_at >= event.event_time
            and event.value_cents >= 0
            and (event.event_type == "purchase" or event.value_cents == 0)
        )

    def _update_session(
        self, event: EngagementEvent, sessions: dict[str, tuple[int, int, int]]
    ) -> None:
        state = sessions.get(event.user_id)
        if state is None:
            sessions[event.user_id] = (event.event_time, event.event_time, 1)
            return
        start, last, count = state
        if event.event_time - last > self.session_gap:
            sessions[event.user_id] = (event.event_time, event.event_time, count + 1)
        else:
            sessions[event.user_id] = (min(start, event.event_time), max(last, event.event_time), count)

