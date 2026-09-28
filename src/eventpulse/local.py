"""Durable filesystem and SQLite adapters used by the local production path."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eventpulse.canonical import canonical_bytes, session_id, sha256_bytes, stable_id
from eventpulse.errors import InvariantViolation, RetryableDependencyError
from eventpulse.models import AdmittedEvent, ApplyResult, ArchiveObject, RejectedEvent
from eventpulse.ports import CrashProbe
from eventpulse.recovery import NoopCrashProbe, PendingOutbox
from eventpulse.semantics import (
    IDENTITY_TTL_MS,
    INACTIVITY_GAP_MS,
    classify_event_time,
    components,
    identity_disposition,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS identity_ledger (
  event_id TEXT NOT NULL, digest TEXT NOT NULL, first_ingest_ms INTEGER NOT NULL,
  expiry_ms INTEGER NOT NULL, generation_id TEXT NOT NULL, disposition TEXT NOT NULL,
  PRIMARY KEY (generation_id, event_id)
);
CREATE TABLE IF NOT EXISTS shard_state (
  shard_id TEXT NOT NULL, generation_id TEXT NOT NULL, max_event_time_ms INTEGER NOT NULL,
  version INTEGER NOT NULL, PRIMARY KEY (shard_id, generation_id)
);
CREATE TABLE IF NOT EXISTS open_event (
  shard_id TEXT NOT NULL, generation_id TEXT NOT NULL, user_id TEXT NOT NULL,
  event_id TEXT NOT NULL, event_time_ms INTEGER NOT NULL, event_type TEXT NOT NULL,
  value_cents INTEGER, digest TEXT NOT NULL,
  PRIMARY KEY (generation_id, event_id)
);
CREATE INDEX IF NOT EXISTS open_event_user_time
ON open_event(shard_id, generation_id, user_id, event_time_ms, event_id);
CREATE TABLE IF NOT EXISTS session_component (
  component_id TEXT PRIMARY KEY, shard_id TEXT NOT NULL, generation_id TEXT NOT NULL,
  user_id TEXT NOT NULL, start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
  version INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS component_closure
ON session_component(shard_id, generation_id, end_ms);
CREATE TABLE IF NOT EXISTS session_output (
  session_id TEXT PRIMARY KEY, generation_id TEXT NOT NULL, user_id TEXT NOT NULL,
  start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL, member_count INTEGER NOT NULL,
  member_ids_json TEXT NOT NULL, views INTEGER NOT NULL, clicks INTEGER NOT NULL,
  purchases INTEGER NOT NULL, value_cents INTEGER NOT NULL, output_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS user_aggregate (
  generation_id TEXT NOT NULL, user_id TEXT NOT NULL, views INTEGER NOT NULL,
  clicks INTEGER NOT NULL, purchases INTEGER NOT NULL, value_cents INTEGER NOT NULL,
  PRIMARY KEY (generation_id, user_id)
);
CREATE TABLE IF NOT EXISTS quarantine (
  quarantine_id TEXT PRIMARY KEY, disposition TEXT NOT NULL, raw_key TEXT NOT NULL,
  source_hash TEXT NOT NULL, sequence_number TEXT NOT NULL, payload_digest TEXT
);
CREATE TABLE IF NOT EXISTS outbox (
  outbox_id TEXT PRIMARY KEY, quarantine_id TEXT NOT NULL UNIQUE, body_json TEXT NOT NULL,
  delivered INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS closure_work (
  work_id TEXT PRIMARY KEY, shard_id TEXT NOT NULL, generation_id TEXT NOT NULL,
  watermark_ms INTEGER NOT NULL, status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS closure_work_pending
ON closure_work(shard_id, generation_id, status, watermark_ms);
CREATE TABLE IF NOT EXISTS metric (
  name TEXT NOT NULL, dimensions_json TEXT NOT NULL, value INTEGER NOT NULL,
  PRIMARY KEY (name, dimensions_json)
);
CREATE TABLE IF NOT EXISTS processing_commit (
  commit_id TEXT PRIMARY KEY, generation_id TEXT NOT NULL, event_id TEXT NOT NULL,
  source_hash TEXT NOT NULL, sequence_number TEXT NOT NULL, raw_key TEXT NOT NULL,
  disposition TEXT NOT NULL, payload_digest TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS failure_destination (
  invocation_id TEXT PRIMARY KEY, object_key TEXT NOT NULL UNIQUE,
  body_sha256 TEXT NOT NULL, earliest_sequence TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('UNRESOLVED', 'ADJUDICATED'))
);
"""


class FilesystemRawArchive:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        target = (self.root / key).resolve()
        if self.root not in target.parents:
            raise InvariantViolation("archive key escapes root")
        return target

    def put_if_absent(self, obj: ArchiveObject) -> None:
        if sha256_bytes(obj.body) != obj.sha256:
            raise InvariantViolation("archive body digest mismatch")
        target = self._path(obj.key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if sha256_bytes(target.read_bytes()) != obj.sha256:
                raise InvariantViolation("existing archive object has different digest")
            return
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(obj.body)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError as error:
                if sha256_bytes(target.read_bytes()) != obj.sha256:
                    raise InvariantViolation("archive conditional-create conflict") from error
        except OSError as error:
            raise RetryableDependencyError("filesystem raw archive failed") from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def read(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except OSError as error:
            raise RetryableDependencyError("filesystem raw read failed") from error


class FilesystemFailureDestination:
    """Conditional local equivalent of the Lambda failure S3 destination."""

    def __init__(self, root: Path) -> None:
        self.archive = FilesystemRawArchive(root)

    def put_if_absent(self, key: str, body: bytes, digest: str) -> None:
        self.archive.put_if_absent(
            ArchiveObject(
                key=key,
                body=body,
                sha256=digest,
                metadata={"disposition": "RETRY_EXHAUSTED"},
            )
        )


class FilesystemOutboxPublisher:
    """Durable local at-least-once channel with stable outbox identity."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def publish(self, outbox_id: str, body: bytes) -> None:
        directory = self.root / sha256_bytes(outbox_id.encode("utf-8"))
        directory.mkdir(parents=True, exist_ok=True)
        for attempt in range(1, 1_000_001):
            target = directory / f"attempt-{attempt:06d}.json"
            try:
                with target.open("xb") as stream:
                    stream.write(body)
                    stream.flush()
                    os.fsync(stream.fileno())
                return
            except FileExistsError:
                continue
            except OSError as error:
                raise RetryableDependencyError("filesystem outbox publish failed") from error
        raise InvariantViolation("outbox attempt space exhausted")


class SQLiteApplicationStore:
    def __init__(self, path: Path, crash_probe: CrashProbe | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.crash_probe = crash_probe or NoopCrashProbe()
        connection = self._connect()
        try:
            connection.executescript(SCHEMA)
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except sqlite3.Error as error:
            connection.rollback()
            raise RetryableDependencyError("SQLite transaction failed") from error
        finally:
            connection.close()

    @staticmethod
    def _quarantine(
        connection: sqlite3.Connection,
        *,
        disposition: str,
        raw_key: str,
        source_hash: str,
        sequence: str,
        payload_digest: str | None,
    ) -> None:
        quarantine_id = stable_id(
            "quarantine", disposition, source_hash, sequence, payload_digest or ""
        )
        outbox_id = stable_id("outbox", quarantine_id)
        body = canonical_bytes(
            {"disposition": disposition, "outbox_id": outbox_id, "quarantine_id": quarantine_id}
        ).decode("utf-8")
        connection.execute(
            "INSERT OR IGNORE INTO quarantine VALUES (?, ?, ?, ?, ?, ?)",
            (quarantine_id, disposition, raw_key, source_hash, sequence, payload_digest),
        )
        connection.execute(
            "INSERT OR IGNORE INTO outbox(outbox_id, quarantine_id, body_json) VALUES (?, ?, ?)",
            (outbox_id, quarantine_id, body),
        )

    def isolate_rejected(self, rejected: RejectedEvent, raw_key: str) -> ApplyResult:
        source_hash = sha256_bytes(rejected.coordinate.event_source_arn.encode("utf-8"))
        digest = sha256_bytes(rejected.archive_body)
        with self._transaction() as connection:
            self._quarantine(
                connection,
                disposition=rejected.disposition,
                raw_key=raw_key,
                source_hash=source_hash,
                sequence=rejected.coordinate.sequence_number,
                payload_digest=digest,
            )
            commit_id = stable_id(
                "commit", "transport", source_hash, rejected.coordinate.sequence_number, digest
            )
            connection.execute(
                "INSERT OR IGNORE INTO processing_commit VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    commit_id,
                    "transport",
                    commit_id,
                    source_hash,
                    rejected.coordinate.sequence_number,
                    raw_key,
                    rejected.disposition,
                    digest,
                ),
            )
        return ApplyResult(rejected.disposition, False)

    def _rebuild_components(
        self, connection: sqlite3.Connection, *, shard_id: str, generation_id: str, user_id: str
    ) -> None:
        rows = connection.execute(
            "SELECT event_id, event_time_ms FROM open_event "
            "WHERE shard_id=? AND generation_id=? AND user_id=?",
            (shard_id, generation_id, user_id),
        ).fetchall()
        connection.execute(
            "DELETE FROM session_component WHERE shard_id=? AND generation_id=? AND user_id=?",
            (shard_id, generation_id, user_id),
        )
        for component in components([(str(row[0]), int(row[1])) for row in rows]):
            member_ids = [event_id for event_id, _ in component]
            component_id = stable_id("component", generation_id, user_id, sorted(member_ids))
            times = [event_time for _, event_time in component]
            connection.execute(
                "INSERT INTO session_component VALUES (?, ?, ?, ?, ?, ?, 1)",
                (component_id, shard_id, generation_id, user_id, min(times), max(times)),
            )

    def apply_event(self, admitted: AdmittedEvent, raw_key: str, generation_id: str) -> ApplyResult:
        event = admitted.event
        shard_id = admitted.coordinate.shard_id
        with self._transaction() as connection:
            identity = connection.execute(
                "SELECT digest, first_ingest_ms FROM identity_ledger "
                "WHERE generation_id=? AND event_id=?",
                (generation_id, event["event_id"]),
            ).fetchone()
            disposition = identity_disposition(
                existing_digest=None if identity is None else str(identity["digest"]),
                incoming_digest=admitted.digest,
                first_ingest_ms=0 if identity is None else int(identity["first_ingest_ms"]),
                ingest_ms=int(event["ingest_time_ms"]),
            )
            if disposition != "NEW_IDENTITY":
                if disposition in {"IDENTITY_CONFLICT", "EXPIRED_IDENTITY"}:
                    self._quarantine(
                        connection,
                        disposition=disposition,
                        raw_key=raw_key,
                        source_hash=sha256_bytes(
                            admitted.coordinate.event_source_arn.encode("utf-8")
                        ),
                        sequence=admitted.coordinate.sequence_number,
                        payload_digest=admitted.digest,
                    )
                return ApplyResult(disposition, False)

            shard = connection.execute(
                "SELECT max_event_time_ms, version FROM shard_state "
                "WHERE shard_id=? AND generation_id=?",
                (shard_id, generation_id),
            ).fetchone()
            previous_max = None if shard is None else int(shard["max_event_time_ms"])
            decision = classify_event_time(int(event["event_time_ms"]), previous_max)
            connection.execute(
                "INSERT INTO identity_ledger VALUES (?, ?, ?, ?, ?, ?)",
                (
                    event["event_id"],
                    admitted.digest,
                    event["ingest_time_ms"],
                    int(event["ingest_time_ms"]) + IDENTITY_TTL_MS,
                    generation_id,
                    decision.category,
                ),
            )
            if decision.category == "beyond_watermark":
                self._quarantine(
                    connection,
                    disposition="LATE_BEYOND_WATERMARK",
                    raw_key=raw_key,
                    source_hash=sha256_bytes(admitted.coordinate.event_source_arn.encode("utf-8")),
                    sequence=admitted.coordinate.sequence_number,
                    payload_digest=admitted.digest,
                )
                self._record_processing_commit(
                    connection,
                    admitted=admitted,
                    raw_key=raw_key,
                    generation_id=generation_id,
                    disposition="LATE_BEYOND_WATERMARK",
                )
                self.crash_probe.reach(
                    "EP-CRASH-03",
                    detail={
                        "event_id": str(event["event_id"]),
                        "sequence_number": admitted.coordinate.sequence_number,
                        "step": "transaction_before_commit",
                    },
                )
                return ApplyResult(
                    "LATE_BEYOND_WATERMARK",
                    False,
                    decision.watermark_before_ms,
                    decision.watermark_after_ms,
                )

            if shard is None:
                connection.execute(
                    "INSERT INTO shard_state VALUES (?, ?, ?, 1)",
                    (shard_id, generation_id, decision.maximum_after_ms),
                )
            else:
                cursor = connection.execute(
                    "UPDATE shard_state SET max_event_time_ms=?, version=version+1 "
                    "WHERE shard_id=? AND generation_id=? AND version=?",
                    (decision.maximum_after_ms, shard_id, generation_id, int(shard["version"])),
                )
                if cursor.rowcount != 1:
                    raise RetryableDependencyError("shard state optimistic version conflict")
            payload = event["payload"]
            value_cents = payload.get("value_cents")
            connection.execute(
                "INSERT INTO open_event VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    shard_id,
                    generation_id,
                    event["user_id"],
                    event["event_id"],
                    event["event_time_ms"],
                    event["event_type"],
                    value_cents,
                    admitted.digest,
                ),
            )
            counts = {
                "view": (1, 0, 0),
                "click": (0, 1, 0),
                "purchase": (0, 0, 1),
            }[str(event["event_type"])]
            connection.execute(
                "INSERT INTO user_aggregate VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(generation_id, user_id) DO UPDATE SET "
                "views=views+excluded.views, clicks=clicks+excluded.clicks, "
                "purchases=purchases+excluded.purchases, "
                "value_cents=value_cents+excluded.value_cents",
                (
                    generation_id,
                    event["user_id"],
                    *counts,
                    int(value_cents or 0),
                ),
            )
            self._rebuild_components(
                connection,
                shard_id=shard_id,
                generation_id=generation_id,
                user_id=str(event["user_id"]),
            )
            work_id = stable_id(
                "closure-work", shard_id, generation_id, decision.watermark_after_ms
            )
            connection.execute(
                "INSERT OR IGNORE INTO closure_work VALUES (?, ?, ?, ?, 'PENDING')",
                (work_id, shard_id, generation_id, decision.watermark_after_ms),
            )
            self._record_processing_commit(
                connection,
                admitted=admitted,
                raw_key=raw_key,
                generation_id=generation_id,
                disposition=decision.category,
            )
            self.crash_probe.reach(
                "EP-CRASH-03",
                detail={
                    "event_id": str(event["event_id"]),
                    "sequence_number": admitted.coordinate.sequence_number,
                    "step": "transaction_before_commit",
                },
            )
            return ApplyResult(
                decision.category,
                True,
                decision.watermark_before_ms,
                decision.watermark_after_ms,
            )

    @staticmethod
    def _record_processing_commit(
        connection: sqlite3.Connection,
        *,
        admitted: AdmittedEvent,
        raw_key: str,
        generation_id: str,
        disposition: str,
    ) -> None:
        source_hash = sha256_bytes(admitted.coordinate.event_source_arn.encode("utf-8"))
        commit_id = stable_id(
            "commit", generation_id, str(admitted.event["event_id"]), admitted.digest
        )
        connection.execute(
            "INSERT OR IGNORE INTO processing_commit VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                commit_id,
                generation_id,
                admitted.event["event_id"],
                source_hash,
                admitted.coordinate.sequence_number,
                raw_key,
                disposition,
                admitted.digest,
            ),
        )

    def pending_outbox(self, limit: int) -> list[PendingOutbox]:
        if not 1 <= limit <= 20:
            raise InvariantViolation("outbox page limit must be between 1 and 20")
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT outbox_id, body_json FROM outbox WHERE delivered=0 "
                "ORDER BY outbox_id LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                PendingOutbox(str(row["outbox_id"]), str(row["body_json"]).encode("utf-8"))
                for row in rows
            ]
        finally:
            connection.close()

    def mark_outbox_delivered(self, outbox_id: str) -> None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT delivered FROM outbox WHERE outbox_id=?", (outbox_id,)
            ).fetchone()
            if row is None:
                raise InvariantViolation("cannot mark an unknown outbox row delivered")
            connection.execute(
                "UPDATE outbox SET delivered=1 WHERE outbox_id=?", (outbox_id,)
            )

    def register_failure_destination(
        self,
        *,
        invocation_id: str,
        object_key: str,
        body_sha256: str,
        earliest_sequence: str,
    ) -> None:
        with self._transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO failure_destination VALUES (?, ?, ?, ?, 'UNRESOLVED')",
                (invocation_id, object_key, body_sha256, earliest_sequence),
            )
            existing = connection.execute(
                "SELECT object_key, body_sha256, earliest_sequence "
                "FROM failure_destination WHERE invocation_id=?",
                (invocation_id,),
            ).fetchone()
            if existing is None or tuple(existing) != (
                object_key,
                body_sha256,
                earliest_sequence,
            ):
                raise InvariantViolation("failure destination identity conflict")

    def unresolved_failure_count(self) -> int:
        connection = self._connect()
        try:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM failure_destination WHERE status='UNRESOLVED'"
                ).fetchone()[0]
            )
        finally:
            connection.close()

    def drain_closures(self, shard_id: str, generation_id: str, limit: int) -> bool:
        if not 1 <= limit <= 20:
            raise InvariantViolation("closure page limit must be between 1 and 20")
        with self._transaction() as connection:
            shard = connection.execute(
                "SELECT max_event_time_ms FROM shard_state WHERE shard_id=? AND generation_id=?",
                (shard_id, generation_id),
            ).fetchone()
            if shard is None:
                return False
            watermark = int(shard["max_event_time_ms"]) - 1_800_000
            due = connection.execute(
                "SELECT * FROM session_component WHERE shard_id=? AND generation_id=? "
                "AND end_ms + ? < ? ORDER BY end_ms, component_id LIMIT ?",
                (shard_id, generation_id, INACTIVITY_GAP_MS, watermark, limit),
            ).fetchall()
            for component in due:
                members = connection.execute(
                    "SELECT event_id, event_time_ms, event_type, value_cents FROM open_event "
                    "WHERE shard_id=? AND generation_id=? AND user_id=? "
                    "AND event_time_ms BETWEEN ? AND ? ORDER BY event_time_ms, event_id",
                    (
                        shard_id,
                        generation_id,
                        component["user_id"],
                        component["start_ms"],
                        component["end_ms"],
                    ),
                ).fetchall()
                member_ids = [str(row["event_id"]) for row in members]
                output_id = session_id(
                    "1.0.0", generation_id, str(component["user_id"]), member_ids
                )
                counter = Counter(str(row["event_type"]) for row in members)
                total_value = sum(int(row["value_cents"] or 0) for row in members)
                connection.execute(
                    "INSERT OR IGNORE INTO session_output "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                    (
                        output_id,
                        generation_id,
                        component["user_id"],
                        component["start_ms"],
                        component["end_ms"],
                        len(member_ids),
                        canonical_bytes(sorted(member_ids)).decode("utf-8"),
                        counter["view"],
                        counter["click"],
                        counter["purchase"],
                        total_value,
                    ),
                )
                connection.execute(
                    "DELETE FROM open_event WHERE shard_id=? AND generation_id=? AND user_id=? "
                    "AND event_time_ms BETWEEN ? AND ?",
                    (
                        shard_id,
                        generation_id,
                        component["user_id"],
                        component["start_ms"],
                        component["end_ms"],
                    ),
                )
                connection.execute(
                    "DELETE FROM session_component WHERE component_id=?",
                    (component["component_id"],),
                )
            remaining = connection.execute(
                "SELECT 1 FROM session_component WHERE shard_id=? AND generation_id=? "
                "AND end_ms + ? < ? LIMIT 1",
                (shard_id, generation_id, INACTIVITY_GAP_MS, watermark),
            ).fetchone()
            if remaining is None:
                connection.execute(
                    "UPDATE closure_work SET status='DONE' WHERE shard_id=? AND generation_id=? "
                    "AND watermark_ms<=?",
                    (shard_id, generation_id, watermark),
                )
            return remaining is not None

    def export(self) -> dict[str, list[dict[str, Any]]]:
        connection = self._connect()
        try:
            result: dict[str, list[dict[str, Any]]] = {}
            queries = {
                "closure_work": "SELECT * FROM closure_work ORDER BY 1",
                "identity_ledger": "SELECT * FROM identity_ledger ORDER BY 1",
                "open_event": "SELECT * FROM open_event ORDER BY 1",
                "outbox": "SELECT * FROM outbox ORDER BY 1",
                "quarantine": "SELECT * FROM quarantine ORDER BY 1",
                "session_component": "SELECT * FROM session_component ORDER BY 1",
                "session_output": "SELECT * FROM session_output ORDER BY 1",
                "shard_state": "SELECT * FROM shard_state ORDER BY 1",
                "user_aggregate": "SELECT * FROM user_aggregate ORDER BY 1",
            }
            for table, query in queries.items():
                rows = connection.execute(query).fetchall()
                result[table] = [dict(row) for row in rows]
            return result
        finally:
            connection.close()

    def recovery_export(self) -> dict[str, list[dict[str, Any]]]:
        """Return deterministic Stage 2 state without changing Stage 1 exports."""

        result = self.export()
        connection = self._connect()
        try:
            recovery_queries = {
                "failure_destination": "SELECT * FROM failure_destination ORDER BY 1",
                "metric": "SELECT * FROM metric ORDER BY 1",
                "processing_commit": "SELECT * FROM processing_commit ORDER BY 1",
            }
            for table, query in recovery_queries.items():
                rows = connection.execute(query).fetchall()
                result[table] = [dict(row) for row in rows]
            return dict(sorted(result.items()))
        finally:
            connection.close()


class SQLiteMetricSink:
    def __init__(self, store: SQLiteApplicationStore) -> None:
        self.store = store

    def increment(self, name: str, *, dimensions: dict[str, str] | None = None) -> None:
        encoded = canonical_bytes(dimensions or {}).decode("utf-8")
        with self.store._transaction() as connection:
            connection.execute(
                "INSERT INTO metric VALUES (?, ?, 1) ON CONFLICT(name, dimensions_json) "
                "DO UPDATE SET value=value+1",
                (name, encoded),
            )


@dataclass
class CollectingLogger:
    events: list[dict[str, str | int | bool | None]] = field(default_factory=list)

    def emit(self, event: dict[str, str | int | bool | None]) -> None:
        self.events.append(dict(sorted(event.items())))


class LambdaBatchResponder:
    def response(self, failures: list[str]) -> dict[str, list[dict[str, str]]]:
        unique = list(dict.fromkeys(failures))
        return {"batchItemFailures": [{"itemIdentifier": sequence} for sequence in unique]}


@dataclass
class LocalRuntime:
    archive: FilesystemRawArchive
    store: SQLiteApplicationStore
    metrics: SQLiteMetricSink
    logger: CollectingLogger
    responder: LambdaBatchResponder = field(default_factory=LambdaBatchResponder)
    crash_probe: CrashProbe = field(default_factory=NoopCrashProbe)
    generation_id: str = "live-v1"


def create_local_runtime(
    root: Path,
    generation_id: str = "live-v1",
    crash_probe: CrashProbe | None = None,
) -> LocalRuntime:
    probe = crash_probe or NoopCrashProbe()
    store = SQLiteApplicationStore(root / "state.sqlite3", probe)
    return LocalRuntime(
        archive=FilesystemRawArchive(root / "archive"),
        store=store,
        metrics=SQLiteMetricSink(store),
        logger=CollectingLogger(),
        crash_probe=probe,
        generation_id=generation_id,
    )
