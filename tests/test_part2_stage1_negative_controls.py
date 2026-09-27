from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_lambda_package import _include_runtime_file, _normalize_record_text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from part2_stage1_helpers import event, record  # noqa: E402

from eventpulse.admission import admit  # noqa: E402
from eventpulse.canonical import canonical_sha256, event_digest, rejected_raw_key  # noqa: E402
from eventpulse.local import LambdaBatchResponder  # noqa: E402
from eventpulse.semantics import components, identity_disposition  # noqa: E402
from eventpulse.transport import parse_source  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "part2_stage1_validator", ROOT / "scripts/validate_part2_stage1.py"
)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class NegativeControlTests(unittest.TestCase):
    def test_environment_bound_console_scripts_are_excluded_from_lambda_zip(self) -> None:
        self.assertFalse(_include_runtime_file(Path("bin/jsonschema")))
        self.assertTrue(_include_runtime_file(Path("eventpulse/handler.py")))
        record = "../../bin/jsonschema,sha256=environment-bound,1\r\npkg/file.py,sha256=x,2\r\n"
        self.assertEqual(_normalize_record_text(record), "pkg/file.py,sha256=x,2\n")

    def test_wrong_precedence_is_detected(self) -> None:
        value = event("precedence", 1_000)
        value["payload"] = {"email": "blocked@example.invalid", "unexpected": "also-invalid"}
        actual = admit(parse_source(record(value, "1"))).disposition
        self.assertEqual(actual, "PRIVACY_VIOLATION")
        self.assertNotEqual(actual, "INVALID_SCHEMA")

    def test_digest_including_ingest_time_is_detected(self) -> None:
        value = event("digest", 1_000, ingest_time_ms=2_000)
        self.assertNotEqual(event_digest(value), canonical_sha256(value))

    def test_wrong_malformed_raw_key_is_detected(self) -> None:
        values = {
            "event_source_arn": "arn:test",
            "shard_id": "shard-a",
            "sequence_number": "1",
            "transport_text": "YmFk",
        }
        correct = rejected_raw_key(**values)
        wrong = rejected_raw_key(**{**values, "sequence_number": "2"})
        self.assertNotEqual(correct, wrong)

    def test_exclusive_session_gap_is_detected(self) -> None:
        actual = components([("a", 0), ("b", 1_800_000)])
        self.assertEqual(actual, [[("a", 0), ("b", 1_800_000)]])
        self.assertNotEqual(actual, [[("a", 0)], [("b", 1_800_000)]])

    def test_exclusive_ttl_boundary_is_detected(self) -> None:
        actual = identity_disposition(
            existing_digest="x",
            incoming_digest="x",
            first_ingest_ms=0,
            ingest_ms=604_800_000,
        )
        self.assertEqual(actual, "IDENTICAL_DUPLICATE")
        self.assertNotEqual(actual, "EXPIRED_IDENTITY")

    def test_batch_response_reordering_or_duplication_is_detected(self) -> None:
        response = LambdaBatchResponder().response(["20", "3", "20"])
        self.assertEqual(
            response,
            {"batchItemFailures": [{"itemIdentifier": "20"}, {"itemIdentifier": "3"}]},
        )

    def test_missing_acceptance_and_trace_mapping_are_rejected(self) -> None:
        requirements = json.loads(
            (ROOT / "docs/requirements/part2-stage1.json").read_text(encoding="utf-8")
        )
        requirements["acceptance_checks"].pop()
        self.assertIn(
            "Stage 1 requirements are not exactly AC-01 through AC-32",
            VALIDATOR.validate_requirements(requirements),
        )
        traceability = json.loads(
            (ROOT / "docs/traceability/part2-stage1.json").read_text(encoding="utf-8")
        )
        traceability["mappings"].pop()
        self.assertIn(
            "traceability does not cover every Stage 1 acceptance check exactly once",
            VALIDATOR.validate_traceability(traceability),
        )

    def test_corrupt_evidence_digest_is_rejected(self) -> None:
        evidence = json.loads(
            (ROOT / "evidence/part2/stage1/handler-result.json").read_text(encoding="utf-8")
        )
        evidence["result_sha256"] = "0" * 64
        self.assertIn("handler result digest mismatch", VALIDATOR.validate_evidence(evidence))

    def test_oracle_import_boundary_is_rejected(self) -> None:
        target = ROOT / "src/eventpulse/semantics.py"
        original = Path.read_text

        def injected(path: Path, *args: object, **kwargs: object) -> str:
            value = original(path, *args, **kwargs)
            return value + "\nimport oracles.eventpulse_reference\n" if path == target else value

        with patch.object(Path, "read_text", autospec=True, side_effect=injected):
            errors = VALIDATOR.validate_import_isolation()
        self.assertIn("production imports independent oracle: src/eventpulse/semantics.py", errors)


if __name__ == "__main__":
    unittest.main()
