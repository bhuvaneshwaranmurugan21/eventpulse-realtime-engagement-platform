"""Substitutable durability, telemetry and response ports."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from eventpulse.models import AdmittedEvent, ApplyResult, ArchiveObject, RejectedEvent


class RawArchive(Protocol):
    def put_if_absent(self, obj: ArchiveObject) -> None: ...

    def read(self, key: str) -> bytes: ...


class ApplicationUnitOfWork(Protocol):
    def isolate_rejected(self, rejected: RejectedEvent, raw_key: str) -> ApplyResult: ...

    def apply_event(
        self, admitted: AdmittedEvent, raw_key: str, generation_id: str
    ) -> ApplyResult: ...

    def drain_closures(self, shard_id: str, generation_id: str, limit: int) -> bool: ...


class ClosureIndex(Protocol):
    def due(
        self, shard_id: str, generation_id: str, watermark_ms: int, limit: int
    ) -> list[str]: ...


class OutboxPublisher(Protocol):
    def publish(self, outbox_id: str, body: bytes) -> None: ...


class MetricSink(Protocol):
    def increment(self, name: str, *, dimensions: dict[str, str] | None = None) -> None: ...


class StructuredLogger(Protocol):
    def emit(self, event: dict[str, str | int | bool | None]) -> None: ...


class RetryPolicy(Protocol):
    def run(self, operation: Callable[[], Any]) -> Any: ...


class BatchResponder(Protocol):
    def response(self, failures: list[str]) -> dict[str, list[dict[str, str]]]: ...


class Runtime(Protocol):
    @property
    def archive(self) -> RawArchive: ...

    @property
    def store(self) -> ApplicationUnitOfWork: ...

    @property
    def metrics(self) -> MetricSink: ...

    @property
    def logger(self) -> StructuredLogger: ...

    @property
    def responder(self) -> BatchResponder: ...

    @property
    def generation_id(self) -> str: ...
