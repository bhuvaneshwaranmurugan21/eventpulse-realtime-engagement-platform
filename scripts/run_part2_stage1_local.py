#!/usr/bin/env python3
"""Invoke the production handler factory with durable local adapters."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eventpulse.canonical import canonical_bytes, canonical_sha256  # noqa: E402
from eventpulse.handler import create_handler  # noqa: E402
from eventpulse.local import create_local_runtime  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", type=Path)
    parser.add_argument("state_root", type=Path)
    parser.add_argument("--generation", default="live-v1")
    args = parser.parse_args()
    event = json.loads(args.fixture.read_text(encoding="utf-8"))
    runtime = create_local_runtime(args.state_root, args.generation)
    response = create_handler(runtime)(event, None)
    result = {
        "handler_response": response,
        "logs": runtime.logger.events,
        "state": runtime.store.export(),
    }
    result["result_sha256"] = canonical_sha256(result)
    sys.stdout.buffer.write(canonical_bytes(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
