#!/usr/bin/env python3
"""Independent standard-library oracle for Part 2 Stage 2 crash evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

TABLE_QUERIES = {
    "closure_work": "SELECT * FROM closure_work ORDER BY 1",
    "failure_destination": "SELECT * FROM failure_destination ORDER BY 1",
    "identity_ledger": "SELECT * FROM identity_ledger ORDER BY 1",
    "metric": "SELECT * FROM metric ORDER BY 1",
    "open_event": "SELECT * FROM open_event ORDER BY 1",
    "outbox": "SELECT * FROM outbox ORDER BY 1",
    "processing_commit": "SELECT * FROM processing_commit ORDER BY 1",
    "quarantine": "SELECT * FROM quarantine ORDER BY 1",
    "session_component": "SELECT * FROM session_component ORDER BY 1",
    "session_output": "SELECT * FROM session_output ORDER BY 1",
    "shard_state": "SELECT * FROM shard_state ORDER BY 1",
    "user_aggregate": "SELECT * FROM user_aggregate ORDER BY 1",
}
DEDUPE_HORIZON_MS = 604_800_000


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _files(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    result = []
    for path in sorted(value for value in root.rglob("*") if value.is_file()):
        body = path.read_bytes()
        result.append(
            {
                "body_sha256": sha256_bytes(body),
                "path": path.relative_to(root).as_posix(),
                "size": len(body),
            }
        )
    return result


def read_journal(root: Path) -> list[dict[str, Any]]:
    path = root / "crash-journal.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def validate_journal(rows: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    previous = "GENESIS"
    for expected_ordinal, row in enumerate(rows, start=1):
        if row.get("ordinal") != expected_ordinal:
            errors.append(f"journal ordinal mismatch at {expected_ordinal}")
        if row.get("previous_sha256") != previous:
            errors.append(f"journal predecessor mismatch at {expected_ordinal}")
        candidate = dict(row)
        actual = candidate.pop("entry_sha256", None)
        expected = sha256_bytes(canonical_bytes(candidate))
        if actual != expected:
            errors.append(f"journal entry digest mismatch at {expected_ordinal}")
        previous = str(actual)
    phases = {str(row.get("phase")): row.get("process_id") for row in rows}
    if "crash" in phases and "restart" in phases:
        if phases["crash"] == phases["restart"]:
            errors.append("restart reused the crash process")
    return errors


def _normalized_journal(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        value = dict(row)
        ordinal = int(value["ordinal"])
        value["process_id"] = f"<{value['phase']}-process>"
        value["entry_sha256"] = f"<entry-{ordinal}>"
        value["previous_sha256"] = "GENESIS" if ordinal == 1 else f"<entry-{ordinal - 1}>"
        normalized.append(value)
    return normalized


def export(root: Path) -> dict[str, Any]:
    database = root / "state.sqlite3"
    tables: dict[str, list[dict[str, Any]]] = {name: [] for name in TABLE_QUERIES}
    if database.exists():
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        try:
            for table, query in TABLE_QUERIES.items():
                tables[table] = [dict(row) for row in connection.execute(query).fetchall()]
        finally:
            connection.close()
    journal = read_journal(root)
    return {
        "archive": _files(root / "archive"),
        "failure_destination_objects": _files(root / "failure-destination"),
        "journal": _normalized_journal(journal),
        "journal_chain_errors": validate_journal(journal),
        "notifications": _files(root / "notifications"),
        "tables": tables,
    }


def digest(value: object) -> str:
    return sha256_bytes(canonical_bytes(value))


def logical_identity_disposition(
    *, existing_digest: str | None, incoming_digest: str, first_ingest_ms: int, ingest_ms: int
) -> str:
    if existing_digest is None:
        return "NEW_IDENTITY"
    if ingest_ms - first_ingest_ms > DEDUPE_HORIZON_MS:
        return "EXPIRED_IDENTITY"
    return "IDENTICAL_DUPLICATE" if existing_digest == incoming_digest else "IDENTITY_CONFLICT"


def validate_ttl_boundary(equality: str, plus_one: str) -> list[str]:
    errors = []
    if equality != "IDENTICAL_DUPLICATE":
        errors.append("dedupe equality boundary changed")
    if plus_one != "EXPIRED_IDENTITY":
        errors.append("dedupe plus-one boundary changed")
    return errors


def validate_claim_levels(levels: dict[str, str]) -> list[str]:
    expected = {
        "application_effect_crash_restart": "LOCAL_VERIFIED",
        "aws_adapter_request_shapes": "DESIGN_ONLY",
        "durable_aws_recovery": "UNCLAIMED",
        "managed_consumer": "UNCLAIMED",
    }
    return [] if levels == expected else ["Stage 2 claim levels exceed or differ from ceiling"]


def validate_recovery_state(state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    tables = state["tables"]
    for row in tables["shard_state"]:
        if int(row["version"]) < 1:
            errors.append("shard optimistic version is non-positive")
    identities = [(row["generation_id"], row["event_id"]) for row in tables["identity_ledger"]]
    if any(not generation for generation, _ in identities):
        errors.append("identity is missing replay generation")
    if len(identities) != len(set(identities)):
        errors.append("generation-scoped identity is duplicated")
    for row in tables["session_output"]:
        if int(row["output_version"]) != 1:
            errors.append("materialized output version is not exactly one")
    output_ids = [row["session_id"] for row in tables["session_output"]]
    if len(output_ids) != len(set(output_ids)):
        errors.append("materialized output identity is duplicated")
    for row in tables["outbox"]:
        quarantine_id = row["quarantine_id"]
        expected = digest(["1.0.0", "outbox", quarantine_id])
        if row["outbox_id"] != expected:
            errors.append("stable outbox identity mismatch")
    return errors


def _ids(state: dict[str, Any], table: str, field: str) -> list[Any]:
    return [row[field] for row in state["tables"][table]]


def verify_frozen_result(
    result: dict[str, Any], golden: dict[str, Any]
) -> list[str]:
    case_id = str(result.get("case_id"))
    expected = golden.get("cases", {}).get(case_id)
    if not isinstance(expected, dict):
        return [f"missing frozen golden for {case_id}"]
    errors = []
    for field in ("after_crash_sha256", "after_restart_sha256", "response_sha256"):
        if result.get(field) != expected.get(field):
            errors.append(f"{case_id} frozen {field} mismatch")
    return errors


def verify(
    case_id: str,
    after_crash: dict[str, Any],
    after_restart: dict[str, Any],
    response: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    before_tables = after_crash["tables"]
    after_tables = after_restart["tables"]
    selected = [
        row for row in after_restart["journal"] if row.get("boundary") == case_id
    ]
    if not selected:
        errors.append("selected crash boundary absent from journal")
    elif {row.get("phase") for row in selected} != {"crash", "restart"}:
        errors.append("selected boundary lacks distinct crash and restart observations")
    if after_restart["journal_chain_errors"]:
        errors.extend(after_restart["journal_chain_errors"])
    errors.extend(validate_recovery_state(after_restart))

    identities = _ids(after_restart, "identity_ledger", "event_id")
    commits = _ids(after_restart, "processing_commit", "event_id")
    if len(identities) != len(set(identities)):
        errors.append("identity applied more than once")
    if len(_ids(after_restart, "outbox", "outbox_id")) != len(
        set(_ids(after_restart, "outbox", "outbox_id"))
    ):
        errors.append("outbox authority repeated")

    if case_id == "EP-CRASH-01":
        if after_crash["archive"] or before_tables["identity_ledger"]:
            errors.append("EP-CRASH-01 exposed a durable effect")
    elif case_id == "EP-CRASH-02":
        if len(after_crash["archive"]) != 1 or before_tables["identity_ledger"]:
            errors.append("EP-CRASH-02 is not raw-only")
    elif case_id == "EP-CRASH-03":
        if len(after_crash["archive"]) != 1:
            errors.append("EP-CRASH-03 lost raw evidence")
        transactional_tables = ("identity_ledger", "open_event", "processing_commit")
        if any(before_tables[name] for name in transactional_tables):
            errors.append("EP-CRASH-03 exposed a partial transaction")
    elif case_id == "EP-CRASH-04":
        if _ids(after_crash, "identity_ledger", "event_id") != ["event-success"]:
            errors.append("EP-CRASH-04 did not retain committed identity")
        if len(before_tables["user_aggregate"]) != 1:
            errors.append("EP-CRASH-04 did not retain committed state")
    elif case_id == "EP-CRASH-05":
        if identities != ["event-prefix"] or commits != ["event-prefix"]:
            errors.append("EP-CRASH-05 prefix/later application is wrong")
        if response != {"batchItemFailures": [{"itemIdentifier": "2"}]}:
            errors.append("EP-CRASH-05 did not report earliest failed sequence")
        if len(after_restart["archive"]) != 2:
            errors.append("EP-CRASH-05 archive inventory is not prefix plus failed raw")
    elif case_id == "EP-CRASH-06":
        if len(before_tables["quarantine"]) != 1 or len(before_tables["outbox"]) != 1:
            errors.append("EP-CRASH-06 poison authority is not durable and singular")
    elif case_id == "EP-CRASH-07":
        if len(after_crash["notifications"]) != 1 or len(after_restart["notifications"]) != 2:
            errors.append("EP-CRASH-07 did not demonstrate repeatable notification")
        if len(after_tables["quarantine"]) != 1 or len(after_tables["outbox"]) != 1:
            errors.append("EP-CRASH-07 repeated authoritative quarantine/outbox state")
        if after_tables["outbox"] and after_tables["outbox"][0]["delivered"] != 1:
            errors.append("EP-CRASH-07 did not persist delivered marker after restart")
    elif case_id == "EP-CRASH-08":
        if len(after_crash["failure_destination_objects"]) != 1:
            errors.append("EP-CRASH-08 lacks durable failure object")
        if len(after_tables["failure_destination"]) != 1:
            errors.append("EP-CRASH-08 lacks singular failure authority")
        elif after_tables["failure_destination"][0]["status"] != "UNRESOLVED":
            errors.append("EP-CRASH-08 failure was silently adjudicated")
        if response != {"blocked": True, "unresolved_failures": 1}:
            errors.append("EP-CRASH-08 did not block success")
    else:
        errors.append("unknown crash boundary")

    if case_id in {"EP-CRASH-01", "EP-CRASH-02", "EP-CRASH-03", "EP-CRASH-04"}:
        if identities != ["event-success"] or commits != ["event-success"]:
            errors.append("successful retry did not converge to one application effect")
        if len(after_tables["user_aggregate"]) != 1:
            errors.append("successful retry aggregate count mismatch")
        elif after_tables["user_aggregate"][0]["views"] != 1:
            errors.append("successful retry double-applied aggregate")
        if response != {"batchItemFailures": []}:
            errors.append("successful retry did not acknowledge")

    return errors
