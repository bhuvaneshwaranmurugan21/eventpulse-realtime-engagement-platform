from __future__ import annotations

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from part2_stage1_helpers import batch, event, record  # noqa: E402

from eventpulse.admission import admit  # noqa: E402
from eventpulse.canonical import event_digest, session_id  # noqa: E402
from eventpulse.handler import create_handler  # noqa: E402
from eventpulse.local import create_local_runtime  # noqa: E402
from eventpulse.models import AdmittedEvent  # noqa: E402
from eventpulse.semantics import (  # noqa: E402
    classify_event_time,
    components,
    identity_disposition,
    is_closed,
)
from eventpulse.transport import parse_source  # noqa: E402

FIXTURE_ROOT = ROOT / "fixtures/part1/stage3"


def load(name: str) -> dict[str, object]:
    value = json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{name} must be an object")
    return value


def fixture_ids(value: object) -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        identifier = value.get("id")
        if isinstance(identifier, str) and identifier.startswith("EP-S3-FX-"):
            result.append(identifier)
        for child in value.values():
            result.extend(fixture_ids(child))
    elif isinstance(value, list):
        for child in value:
            result.extend(fixture_ids(child))
    return result


class CorpusConformanceTests(unittest.TestCase):
    def test_all_50_fixture_identities_enter_the_production_handler(self) -> None:
        documents = [
            load("envelope.json"),
            load("identity.json"),
            load("time.json"),
            load("sessions.json"),
            load("recovery.json"),
            load("replay-and-skew.json"),
        ]
        identifiers = sorted(identifier for doc in documents for identifier in fixture_ids(doc))
        self.assertEqual(len(identifiers), 50)
        self.assertEqual(len(set(identifiers)), 50)
        with tempfile.TemporaryDirectory() as directory:
            runtime = create_local_runtime(Path(directory))
            handler = create_handler(runtime)
            records = [
                record(
                    event(identifier.lower(), 1_000_000_000 + index, user_id=f"case-{index}"),
                    str(10_000 + index),
                )
                for index, identifier in enumerate(identifiers)
            ]
            self.assertEqual(handler(batch(*records), None), {"batchItemFailures": []})
            observed = {row["event_id"] for row in runtime.store.export()["identity_ledger"]}
            self.assertEqual(observed, {identifier.lower() for identifier in identifiers})

    def test_envelope_cases_match_frozen_expected_dispositions(self) -> None:
        fixture = load("envelope.json")
        base = fixture["base_event"]
        self.assertIsInstance(base, dict)
        for index, case in enumerate(fixture["cases"]):
            self.assertIsInstance(case, dict)
            value = deepcopy(base)
            value.update(deepcopy(case.get("patch", {})))
            for field in case.get("remove", []):
                value.pop(field, None)
            if case.get("append_source_characters"):
                value["source"] += "x" * int(case["append_source_characters"])
            result = admit(parse_source(record(value, str(index + 1))))
            actual = "ACCEPTED" if isinstance(result, AdmittedEvent) else result.disposition
            self.assertEqual(actual, case["expected"], case["id"])

    def test_identity_time_and_session_cases_match_frozen_expectations(self) -> None:
        identity = load("identity.json")
        for case in identity["cases"]:
            actual = identity_disposition(
                existing_digest="same" if case["has_existing"] else None,
                incoming_digest="same" if case["same_digest"] else "different",
                first_ingest_ms=0,
                ingest_ms=case["age_ms"],
            )
            expected = str(case["expected"]).replace("_QUARANTINE", "")
            self.assertEqual(actual, expected, case["id"])
        digest_case = identity["digest_cases"][0]
        self.assertEqual(event_digest(digest_case["event_a"]), event_digest(digest_case["event_b"]))

        time = load("time.json")
        for case in time["cases"]:
            decision = classify_event_time(
                case["event_time_ms"], case["previous_max_event_time_ms"]
            )
            self.assertEqual(
                {
                    "category": decision.category,
                    "watermark_after_ms": decision.watermark_after_ms,
                    "watermark_before_ms": decision.watermark_before_ms,
                },
                case["expected"],
                case["id"],
            )

        sessions = load("sessions.json")
        for case in sessions["cases"]:
            actual = [
                [event_id for event_id, _ in component]
                for component in components(
                    [(row["event_id"], row["event_time_ms"]) for row in case["events"]]
                )
            ]
            self.assertEqual(actual, case["expected_components"], case["id"])
        for case in sessions["closure_cases"]:
            self.assertEqual(
                is_closed(watermark_ms=case["watermark_ms"], session_end_ms=case["session_end_ms"]),
                case["expected_closed"],
                case["id"],
            )
        case = sessions["session_id_case"]
        self.assertEqual(
            session_id(
                case["contract_version"],
                case["generation_id"],
                case["user_id"],
                case["member_event_ids"],
            ),
            case["expected_session_id"],
        )

    def test_same_event_isolated_between_generations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = record(event("generation-event", 1_000), "1")
            live = create_local_runtime(root, "live-v1")
            replay = create_local_runtime(root, "replay-1")
            create_handler(live)(batch(value), None)
            create_handler(replay)(batch(value), None)
            identities = live.store.export()["identity_ledger"]
            self.assertEqual(
                {(row["generation_id"], row["event_id"]) for row in identities},
                {("live-v1", "generation-event"), ("replay-1", "generation-event")},
            )


if __name__ == "__main__":
    unittest.main()
