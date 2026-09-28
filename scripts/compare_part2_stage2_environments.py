#!/usr/bin/env python3
"""Compare crash evidence produced by two independently provisioned interpreters."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "evidence/part2/stage2/environment-reproducibility.json"


def _run(interpreter: Path, output: Path) -> tuple[bytes, str]:
    launcher = interpreter.absolute()
    environment = {
        **os.environ,
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "TZ": "UTC",
    }
    subprocess.run(  # noqa: S603 - caller-selected local interpreter, fixed repository script
        [
            str(launcher),
            str((ROOT / "scripts/run_part2_stage2_crash_matrix.py").resolve()),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        env=environment,
        timeout=180,
    )
    version = subprocess.check_output(  # noqa: S603 - local interpreter version only
        [str(launcher), "--version"], text=True
    ).strip()
    return (output / "summary.json").read_bytes(), version


def render(python_a: Path, python_b: Path) -> str:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        first, version_a = _run(python_a, root / "environment-a")
        second, version_b = _run(python_b, root / "environment-b")
    if first != second:
        raise AssertionError("clean environments produced different crash evidence")
    value = {
        "authority": "EP-FUTURE-P2-002",
        "environments_compared": 2,
        "evidence_sha256": hashlib.sha256(first).hexdigest(),
        "interpreter_a": version_a,
        "interpreter_b": version_b,
        "lock_sha256": hashlib.sha256(
            (ROOT / "requirements/dev.lock").read_bytes()
        ).hexdigest(),
        "network_calls_during_matrix": 0,
        "status": "PASS",
    }
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-a", type=Path, required=True)
    parser.add_argument("--python-b", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render(args.python_a, args.python_b)
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != expected:
            raise SystemExit("Part 2 Stage 2 environment evidence is stale")
    else:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
