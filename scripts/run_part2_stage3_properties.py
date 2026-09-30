#!/usr/bin/env python3
"""Deterministic property and metamorphic proof for Part 2 Stage 3."""

from __future__ import annotations

import copy
import json
import random
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "part2/stage3/oracles")]

from identity_oracle import event_identity  # noqa: E402
from part2_stage1_helpers import batch, event, record  # noqa: E402

from eventpulse.canonical import event_digest  # noqa: E402
from eventpulse.handler import create_handler  # noqa: E402
from eventpulse.local import create_local_runtime  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run() -> dict[str, Any]:
    authority = json.loads((ROOT / "fixtures/part2/stage3/property-authority.json").read_text())
    rng = random.Random(authority["seed"])  # noqa: S311 - deterministic testing
    counts = authority["cases"]
    for index in range(counts["canonical_key_order"]):
        value = event(f"canonical-{index}", 1_000_000 + index, ingest_time_ms=2_000_000 + index)
        shuffled = dict(rng.sample(list(value.items()), len(value)))
        require(event_digest(value) == event_digest(shuffled), "key order changed identity")
        require(event_digest(value) == event_identity(value), "oracle disagreement")
    for index in range(counts["ingest_time_exclusion"]):
        left = event(f"clock-{index}", 3_000_000 + index, ingest_time_ms=4_000_000)
        right = copy.deepcopy(left)
        right["ingest_time_ms"] += rng.randint(1, 50_000)
        require(event_digest(left) == event_digest(right), "ingest time changed identity")
    for index in range(counts["semantic_mutation"]):
        left = event(f"semantic-{index}", 5_000_000 + index)
        right = copy.deepcopy(left)
        right["payload"]["page_id"] = f"changed-{index}"
        require(event_digest(left) != event_digest(right), "semantic mutation retained identity")
    for index in range(counts["batch_permutations"]):
        items = [record(event(f"batch-{index}-{n}", 10_000_000 + n), str(n + 1)) for n in range(6)]
        permuted = list(items)
        rng.shuffle(permuted)
        with tempfile.TemporaryDirectory() as left_dir, tempfile.TemporaryDirectory() as right_dir:
            left = create_local_runtime(Path(left_dir))
            right = create_local_runtime(Path(right_dir))
            require(
                create_handler(left)(batch(*items), None) == {"batchItemFailures": []},
                "batch failed",
            )
            require(
                create_handler(right)(batch(*permuted), None) == {"batchItemFailures": []},
                "permutation failed",
            )
            require(left.store.recovery_export() == right.store.recovery_export(), "state diverged")
    return {
        "authority": authority["authority"],
        "seed": authority["seed"],
        "status": "PASS",
        "total_generated_checks": sum(counts.values()),
    }


if __name__ == "__main__":
    print(json.dumps(run(), separators=(",", ":"), sort_keys=True))
