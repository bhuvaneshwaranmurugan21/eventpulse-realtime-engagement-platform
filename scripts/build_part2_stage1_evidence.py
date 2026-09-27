#!/usr/bin/env python3
"""Generate deterministic evidence through the production handler path."""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eventpulse.canonical import canonical_bytes, canonical_sha256  # noqa: E402
from eventpulse.handler import create_handler  # noqa: E402
from eventpulse.local import create_local_runtime  # noqa: E402

FIXTURE = ROOT / "fixtures/part2/stage1/kinesis-vertical-slice.json"
TARGET = ROOT / "evidence/part2/stage1/handler-result.json"


def _blocked_socket(*args: object, **kwargs: object) -> socket.socket:
    del args, kwargs
    raise AssertionError("network access is forbidden in Stage 1 local evidence")


def run_once() -> dict[str, Any]:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        runtime = create_local_runtime(root)
        with patch("socket.socket", _blocked_socket):
            response = create_handler(runtime)(fixture, None)
        archive = [
            {
                "path": str(path.relative_to(root / "archive")),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size_bytes": path.stat().st_size,
            }
            for path in sorted((root / "archive").rglob("*"))
            if path.is_file()
        ]
        return {
            "archive": archive,
            "handler_response": response,
            "logs": runtime.logger.events,
            "state": runtime.store.export(),
        }


def render() -> str:
    first = run_once()
    second = run_once()
    if canonical_bytes(first) != canonical_bytes(second):
        raise AssertionError("production handler evidence is nondeterministic")
    result = {
        "claim_level": "LOCAL_VERIFIED",
        "fixture": str(FIXTURE.relative_to(ROOT)),
        "network_calls": 0,
        "production_entry": "eventpulse.handler.create_handler",
        "result": first,
        "result_sha256": canonical_sha256(first),
        "runs_compared": 2,
    }
    return json.dumps(result, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != expected:
            raise SystemExit("Part 2 Stage 1 handler evidence is stale")
    else:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
