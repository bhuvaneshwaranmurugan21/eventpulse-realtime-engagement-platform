"""Adversarial controls for the Stage 2 contract validator."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "stage2_validator", ROOT / "scripts/validate_stage2_contract.py"
)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class Stage2ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = VALIDATOR.load_all()

    def errors(self, data: dict[str, object]) -> list[str]:
        return VALIDATOR.validate_data(data)

    def test_authority_is_valid(self) -> None:
        self.assertEqual(self.errors(copy.deepcopy(self.data)), [])

    def test_duplicate_requirement_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["requirements"]["requirements"].append(
            copy.deepcopy(data["requirements"]["requirements"][0])
        )
        self.assertIn("duplicate requirement ID", self.errors(data))

    def test_missing_proof_mapping_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["proof"]["mappings"].pop()
        self.assertIn("proof matrix does not cover every requirement exactly once", self.errors(data))

    def test_aws_claim_inflation_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["claims"]["claims"][1]["level"] = "AWS_VERIFIED"
        self.assertTrue(any("claim inflation" in item for item in self.errors(data)))

    def test_region_drift_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["semantics"]["authority"]["region"] = "ap-south-1"
        self.assertIn("authoritative region must be ap-south-2", self.errors(data))

    def test_missing_late_category_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        del data["semantics"]["event_time"]["categories"]["beyond_watermark"]
        self.assertIn("watermark categories or allowed lateness drifted", self.errors(data))

    def test_ambiguous_watermark_boundary_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["semantics"]["event_time"]["boundary"] = "implementation decides"
        self.assertIn("watermark equality boundary is ambiguous", self.errors(data))

    def test_transport_exactly_once_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["recovery"]["claims"]["transport_exactly_once"] = True
        self.assertIn("transport exactly-once must remain false", self.errors(data))

    def test_missing_crash_boundary_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["recovery"]["boundaries"].pop()
        self.assertIn("crash transition matrix is incomplete", self.errors(data))

    def test_dedupe_ttl_shorter_than_horizon_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["semantics"]["identity"]["ttl_storage_ms"] = 604800000
        self.assertIn("dedupe horizon or protective TTL is invalid", self.errors(data))

    def test_session_closure_ambiguity_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["semantics"]["sessions"]["closure"] = "close eventually"
        self.assertIn("session closure is not strictly defined", self.errors(data))

    def test_lateness_too_short_for_bridge_is_rejected(self) -> None:
        data = copy.deepcopy(self.data)
        data["semantics"]["event_time"]["allowed_lateness_ms"] = 300000
        errors = self.errors(data)
        self.assertIn("watermark categories or allowed lateness drifted", errors)
        self.assertIn("allowed lateness cannot support the required bridge case", errors)


if __name__ == "__main__":
    unittest.main()
