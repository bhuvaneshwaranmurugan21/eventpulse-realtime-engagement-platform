#!/usr/bin/env python3
"""Run the twelve inherited mandatory semantic negative controls."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "tests.test_part2_stage2_negative_controls.MandatoryNegativeControls."
METHODS = [
    "test_nc01_archive_digest_corruption_is_rejected",
    "test_nc02_partial_transaction_visibility_is_rejected",
    "test_nc03_state_version_bypass_is_rejected",
    "test_nc04_later_failure_sequence_is_rejected",
    "test_nc05_changed_outbox_identity_is_rejected",
    "test_nc06_reversed_ttl_boundary_is_rejected",
    "test_nc07_removed_replay_generation_is_rejected",
    "test_nc08_reordered_journal_transition_is_rejected",
    "test_nc09_output_version_skip_is_rejected",
    "test_nc10_reused_process_is_rejected_even_with_valid_chain",
    "test_nc11_missing_raw_object_is_not_silently_replayable",
    "test_nc12_aws_claim_inflation_is_forbidden",
]


def run() -> dict[str, object]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0")
    results = []
    for index, method in enumerate(METHODS, 1):
        result = subprocess.run(  # noqa: S603 - frozen interpreter/test nodes
            [sys.executable, "-m", "unittest", PREFIX + method],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        results.append(
            {"id": f"MUT-{index:02d}", "killed": result.returncode == 0, "test": PREFIX + method}
        )
    killed = sum(bool(row["killed"]) for row in results)
    if killed != 12:
        raise RuntimeError("mandatory semantic control survived")
    return {
        "authority": "EP-FUTURE-P2-003",
        "mandatory_mutants": 12,
        "mutants_killed": killed,
        "results": results,
        "status": "PASS",
    }


if __name__ == "__main__":
    print(json.dumps(run(), separators=(",", ":"), sort_keys=True))
