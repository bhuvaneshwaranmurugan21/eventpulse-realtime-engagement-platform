"""Independent EventPulse reference evaluator for Part 1 Stage 3.

The evaluator is deliberately small, deterministic, and independent of the
future production consumer. It reads only versioned contracts and fixtures.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "fixtures/part1/stage3"
SEMANTICS_PATH = ROOT / "contracts/event-semantics-v1.json"
RECOVERY_PATH = ROOT / "contracts/recovery-protocol-v1.json"
ORACLE_SPEC_PATH = ROOT / "contracts/stage3-oracle-spec-v1.json"

FIXTURE_FILES = (
    "envelope.json",
    "identity.json",
    "time.json",
    "sessions.json",
    "recovery.json",
    "replay-and-skew.json",
)

REQUIRED_EVENT_FIELDS = {
    "schema_version",
    "event_id",
    "source",
    "user_id",
    "event_type",
    "event_time_ms",
    "ingest_time_ms",
    "partition_key",
    "payload",
}
ALLOWED_PAYLOAD_FIELDS = {"campaign_id", "page_id", "value_cents"}
PROHIBITED_PAYLOAD_FIELDS = {
    "address",
    "credential",
    "email",
    "free_text",
    "name",
    "password",
    "phone",
    "secret",
    "token",
}
EVENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
PARTITION_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
SOURCE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class OracleError(ValueError):
    """Raised when a fixture cannot be evaluated under the frozen authority."""


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise OracleError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return value


def _reject_floats(value: Any) -> None:
    if isinstance(value, float):
        raise OracleError("canonical EventPulse data forbids floating-point values")
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise OracleError("canonical JSON object keys must be strings")
            _reject_floats(child)
    elif isinstance(value, list):
        for child in value:
            _reject_floats(child)


def canonical_bytes(value: Any) -> bytes:
    _reject_floats(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def build_envelope_case(base_event: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    event = deepcopy(base_event)
    event.update(deepcopy(case.get("patch", {})))
    for field in case.get("remove", []):
        event.pop(field, None)
    if case.get("append_source_characters"):
        event["source"] = str(event.get("source", "")) + "x" * int(case["append_source_characters"])
    return event


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def schema_errors(event: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(event) != REQUIRED_EVENT_FIELDS:
        missing = sorted(REQUIRED_EVENT_FIELDS - set(event))
        extra = sorted(set(event) - REQUIRED_EVENT_FIELDS)
        if missing:
            errors.append(f"missing fields: {missing}")
        if extra:
            errors.append(f"unknown fields: {extra}")
        return errors
    if event["schema_version"] != "1.0.0":
        errors.append("schema_version must equal 1.0.0")
    if not isinstance(event["event_id"], str) or not EVENT_ID.fullmatch(event["event_id"]):
        errors.append("event_id invalid")
    if not isinstance(event["source"], str) or not SOURCE.fullmatch(event["source"]):
        errors.append("source invalid")
    if not isinstance(event["user_id"], str) or not EVENT_ID.fullmatch(event["user_id"]):
        errors.append("user_id invalid")
    if event["event_type"] not in {"view", "click", "purchase"}:
        errors.append("event_type invalid")
    if not _is_int(event["event_time_ms"]) or event["event_time_ms"] < 0:
        errors.append("event_time_ms invalid")
    if not _is_int(event["ingest_time_ms"]) or event["ingest_time_ms"] < 0:
        errors.append("ingest_time_ms invalid")
    if not isinstance(event["partition_key"], str) or not PARTITION_KEY.fullmatch(event["partition_key"]):
        errors.append("partition_key invalid")
    payload = event["payload"]
    if not isinstance(payload, dict):
        errors.append("payload must be an object")
        return errors
    if len(payload) > 3 or set(payload) - ALLOWED_PAYLOAD_FIELDS:
        errors.append("payload properties invalid")
    for field in ("campaign_id", "page_id"):
        if field in payload:
            limit = 128 if field == "campaign_id" else 256
            if not isinstance(payload[field], str) or not 1 <= len(payload[field]) <= limit:
                errors.append(f"{field} invalid")
    if "value_cents" in payload and (
        not _is_int(payload["value_cents"]) or not 0 <= payload["value_cents"] <= 100_000_000
    ):
        errors.append("value_cents invalid")
    if event["event_type"] == "purchase" and "value_cents" not in payload:
        errors.append("purchase requires value_cents")
    if event["event_type"] in {"view", "click"} and "value_cents" in payload:
        errors.append("view/click forbids value_cents")
    return errors


def event_disposition(event: dict[str, Any]) -> str:
    semantics = load_json(SEMANTICS_PATH)
    envelope = semantics["envelope"]
    encoded = canonical_bytes(event)
    if len(encoded) > int(envelope["max_encoded_bytes"]):
        return "EVENT_TOO_LARGE"
    payload = event.get("payload")
    if isinstance(payload, dict) and set(payload) & PROHIBITED_PAYLOAD_FIELDS:
        return "PRIVACY_VIOLATION"
    if schema_errors(event):
        return "INVALID_SCHEMA"
    if event["partition_key"] != event["user_id"]:
        return "PARTITION_MISMATCH"
    clock = envelope["clock_validity"]
    delta = int(event["event_time_ms"]) - int(event["ingest_time_ms"])
    if delta > int(clock["max_future_ms"]):
        return "FUTURE_CLOCK"
    if -delta > int(clock["max_age_ms"]):
        return "TOO_OLD"
    return "ACCEPTED"


def event_digest(event: dict[str, Any]) -> str:
    semantic_event = deepcopy(event)
    semantic_event.pop("ingest_time_ms", None)
    return canonical_sha256(semantic_event)


def identity_disposition(
    *, has_existing: bool, same_digest: bool, age_ms: int, horizon_ms: int
) -> str:
    if not has_existing:
        return "NEW_IDENTITY"
    if age_ms > horizon_ms:
        return "EXPIRED_IDENTITY_QUARANTINE"
    return "IDENTICAL_DUPLICATE" if same_digest else "IDENTITY_CONFLICT"


def classify_event_time(
    *, event_time_ms: int, previous_max_event_time_ms: int | None, allowed_lateness_ms: int
) -> dict[str, int | str | None]:
    if previous_max_event_time_ms is None:
        maximum_after = event_time_ms
        return {
            "category": "on_time",
            "watermark_after_ms": maximum_after - allowed_lateness_ms,
            "watermark_before_ms": None,
        }
    watermark_before = previous_max_event_time_ms - allowed_lateness_ms
    if event_time_ms >= previous_max_event_time_ms:
        category = "on_time"
    elif event_time_ms >= watermark_before:
        category = "accepted_late"
    else:
        category = "beyond_watermark"
    maximum_after = max(previous_max_event_time_ms, event_time_ms)
    return {
        "category": category,
        "watermark_after_ms": maximum_after - allowed_lateness_ms,
        "watermark_before_ms": watermark_before,
    }


def shard_watermarks(records: list[dict[str, Any]], *, allowed_lateness_ms: int) -> dict[str, int]:
    maxima: dict[str, int] = {}
    for record in records:
        shard = str(record["shard"])
        event_time = int(record["event_time_ms"])
        maxima[shard] = max(maxima.get(shard, event_time), event_time)
    return {shard: maximum - allowed_lateness_ms for shard, maximum in sorted(maxima.items())}


def session_components(
    events: list[dict[str, Any]], *, inactivity_gap_ms: int
) -> list[list[str]]:
    ordered = sorted(events, key=lambda row: (int(row["event_time_ms"]), str(row["event_id"])))
    components: list[list[str]] = []
    previous_time: int | None = None
    for event in ordered:
        event_time = int(event["event_time_ms"])
        if previous_time is None or event_time - previous_time > inactivity_gap_ms:
            components.append([])
        components[-1].append(str(event["event_id"]))
        previous_time = event_time
    return components


def stable_session_id(
    *, contract_version: str, generation_id: str, user_id: str, member_event_ids: list[str]
) -> str:
    preimage = [contract_version, generation_id, user_id, sorted(member_event_ids)]
    return canonical_sha256(preimage)


def session_closed(*, watermark_ms: int, session_end_ms: int, inactivity_gap_ms: int) -> bool:
    return watermark_ms > session_end_ms + inactivity_gap_ms


def validate_recovery_ids(recovery: dict[str, Any]) -> None:
    expected = {f"EP-CRASH-{number:02d}" for number in range(1, 9)}
    actual = {row.get("id") for row in recovery.get("boundaries", []) if isinstance(row, dict)}
    if actual != expected:
        raise OracleError(f"recovery boundary mismatch: expected={sorted(expected)} actual={sorted(actual)}")


def recovery_observation(crash_id: str) -> dict[str, Any]:
    recovery = load_json(RECOVERY_PATH)
    validate_recovery_ids(recovery)
    matches = [row for row in recovery["boundaries"] if row["id"] == crash_id]
    if len(matches) != 1:
        raise OracleError(f"unknown or duplicate crash boundary: {crash_id}")
    row = matches[0]
    return {
        "boundary": row["boundary"],
        "possible_durable_effects": row["possible_durable_effects"],
        "retry": row["retry"],
        "safety": row["safety"],
    }


def checkpoint_after_batch(sequence_numbers: list[int], failed: list[int]) -> int | None:
    if not sequence_numbers:
        return None
    if not failed:
        return max(sequence_numbers)
    earliest_failure = min(failed)
    acknowledged = [number for number in sequence_numbers if number < earliest_failure]
    return max(acknowledged) if acknowledged else None


def replay_keys(
    *, generation_id: str, event_ids: list[str], integrity_verified: bool
) -> list[str]:
    if not integrity_verified:
        raise OracleError("RAW_INTEGRITY_REQUIRED")
    return sorted({f"{generation_id}:{event_id}" for event_id in event_ids})


def skew_summary(keys: list[str]) -> dict[str, int | str]:
    if not keys:
        raise OracleError("skew input must not be empty")
    counts = Counter(keys)
    hottest_count = max(counts.values())
    return {
        "hottest_count": hottest_count,
        "hottest_ratio": str(Fraction(hottest_count, len(keys))),
    }


def evaluate_corpus() -> dict[str, Any]:
    semantics = load_json(SEMANTICS_PATH)
    recovery = load_json(RECOVERY_PATH)
    validate_recovery_ids(recovery)
    lateness = int(semantics["event_time"]["allowed_lateness_ms"])
    gap = int(semantics["sessions"]["inactivity_gap_ms"])
    horizon = int(semantics["identity"]["dedupe_horizon_ms"])
    results: list[dict[str, Any]] = []

    envelope = load_json(FIXTURE_ROOT / "envelope.json")
    for case in envelope["cases"]:
        event = build_envelope_case(envelope["base_event"], case)
        results.append({"id": case["id"], "actual": event_disposition(event), "expected": case["expected"]})

    identity = load_json(FIXTURE_ROOT / "identity.json")
    for case in identity["cases"]:
        actual = identity_disposition(
            has_existing=bool(case["has_existing"]),
            same_digest=bool(case["same_digest"]),
            age_ms=int(case["age_ms"]),
            horizon_ms=horizon,
        )
        results.append({"id": case["id"], "actual": actual, "expected": case["expected"]})
    for case in identity["digest_cases"]:
        actual = event_digest(case["event_a"]) == event_digest(case["event_b"])
        results.append({"id": case["id"], "actual": actual, "expected": case["expected_equal"]})

    time_cases = load_json(FIXTURE_ROOT / "time.json")
    for case in time_cases["cases"]:
        actual = classify_event_time(
            event_time_ms=int(case["event_time_ms"]),
            previous_max_event_time_ms=case["previous_max_event_time_ms"],
            allowed_lateness_ms=lateness,
        )
        results.append({"id": case["id"], "actual": actual, "expected": case["expected"]})
    for case in time_cases["shard_cases"]:
        actual = shard_watermarks(case["records"], allowed_lateness_ms=lateness)
        results.append({"id": case["id"], "actual": actual, "expected": case["expected"]})

    sessions = load_json(FIXTURE_ROOT / "sessions.json")
    for case in sessions["cases"]:
        actual = session_components(case["events"], inactivity_gap_ms=gap)
        results.append({"id": case["id"], "actual": actual, "expected": case["expected_components"]})
    for case in sessions["closure_cases"]:
        actual = session_closed(
            watermark_ms=int(case["watermark_ms"]),
            session_end_ms=int(case["session_end_ms"]),
            inactivity_gap_ms=gap,
        )
        results.append({"id": case["id"], "actual": actual, "expected": case["expected_closed"]})
    session_id_case = sessions["session_id_case"]
    session_id_actual = stable_session_id(
        contract_version=session_id_case["contract_version"],
        generation_id=session_id_case["generation_id"],
        user_id=session_id_case["user_id"],
        member_event_ids=session_id_case["member_event_ids"],
    )
    results.append(
        {
            "id": session_id_case["id"],
            "actual": session_id_actual,
            "expected": session_id_case["expected_session_id"],
        }
    )

    recovery_cases = load_json(FIXTURE_ROOT / "recovery.json")
    for case in recovery_cases["crash_cases"]:
        actual = recovery_observation(case["crash_id"])
        results.append({"id": case["id"], "actual": actual, "expected": case["expected"]})
    for case in recovery_cases["checkpoint_cases"]:
        actual = checkpoint_after_batch(case["sequence_numbers"], case["failed"])
        results.append({"id": case["id"], "actual": actual, "expected": case["expected_checkpoint"]})

    replay_skew = load_json(FIXTURE_ROOT / "replay-and-skew.json")
    for case in replay_skew["replay_cases"]:
        try:
            actual_replay: Any = replay_keys(
                generation_id=case["generation_id"],
                event_ids=case["event_ids"],
                integrity_verified=bool(case["integrity_verified"]),
            )
        except OracleError as exc:
            actual_replay = str(exc)
        expected_replay = case.get("expected_keys", case.get("expected_error"))
        results.append({"id": case["id"], "actual": actual_replay, "expected": expected_replay})
    for case in replay_skew["skew_cases"]:
        summary = skew_summary(case["keys"])
        expected_skew = {
            "hottest_count": case["expected_hottest_count"],
            "hottest_ratio": case["expected_hottest_ratio"],
        }
        results.append({"id": case["id"], "actual": summary, "expected": expected_skew})

    failures = [row["id"] for row in results if row["actual"] != row["expected"]]
    result = {
        "contract_version": semantics["contract_version"],
        "fixture_count": len(results),
        "failures": failures,
        "results": results,
        "status": "PASS" if not failures else "FAIL",
    }
    result["corpus_sha256"] = canonical_sha256(result)
    return result


def fixture_ids() -> set[str]:
    identifiers: set[str] = set()
    for filename in FIXTURE_FILES:
        data = load_json(FIXTURE_ROOT / filename)
        for key, value in data.items():
            if key == "base_event" or key == "group":
                continue
            rows = value if isinstance(value, list) else [value]
            for row in rows:
                if isinstance(row, dict) and isinstance(row.get("id"), str):
                    if row["id"] in identifiers:
                        raise OracleError(f"duplicate fixture ID: {row['id']}")
                    identifiers.add(row["id"])
    return identifiers
