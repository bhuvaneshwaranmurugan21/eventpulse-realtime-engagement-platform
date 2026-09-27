#!/usr/bin/env python3
"""Build a reproducible self-contained EventPulse Lambda ZIP and inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements/runtime.lock"
TARGET = ROOT / "evidence/part2/stage1/package-inventory.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _include_runtime_file(relative: Path) -> bool:
    """Keep importable runtime files and omit environment-bound console launchers."""
    return bool(relative.parts) and relative.parts[0] != "bin"


def _normalize_record_text(body: str) -> str:
    """Remove metadata rows for console launchers omitted from the Lambda ZIP."""
    rows = [line for line in body.splitlines() if not line.startswith("../../bin/")]
    return "\n".join(rows) + "\n"


def build(wheelhouse: Path, output_zip: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as directory:
        package = Path(directory) / "package"
        package.mkdir()
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        subprocess.run(  # noqa: S603 - fixed interpreter and qualified local wheelhouse
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-index",
                "--find-links",
                str(wheelhouse.resolve()),
                "--require-hashes",
                "--no-compile",
                "--target",
                str(package),
                "-r",
                str(LOCK),
            ],
            check=True,
            cwd=ROOT,
            env=environment,
            stdout=subprocess.DEVNULL,
        )
        shutil.copytree(ROOT / "src/eventpulse", package / "eventpulse")
        for path in list(package.rglob("__pycache__")):
            shutil.rmtree(path)
        for path in list(package.rglob("*.pyc")):
            path.unlink()
        for path in sorted(package.glob("*.dist-info/RECORD")):
            path.write_text(
                _normalize_record_text(path.read_text(encoding="utf-8")),
                encoding="utf-8",
                newline="\n",
            )

        # Console entrypoints are not used by Lambda and their generated shebangs
        # embed the builder virtual-environment path. Excluding them keeps the
        # deployment artifact reproducible across independently located builders.
        files = [
            path
            for path in sorted(package.rglob("*"))
            if path.is_file() and _include_runtime_file(path.relative_to(package))
        ]
        output_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(
            output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as out:
            for path in files:
                relative = str(path.relative_to(package))
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                out.writestr(info, path.read_bytes())
        return {
            "archive_sha256": digest(output_zip),
            "archive_size_bytes": output_zip.stat().st_size,
            "files": [
                {
                    "path": str(path.relative_to(package)),
                    "sha256": digest(path),
                    "size_bytes": path.stat().st_size,
                }
                for path in files
            ],
            "handler": "eventpulse.lambda_entry.lambda_handler",
            "python": "3.12",
            "runtime_lock_sha256": digest(LOCK),
            "self_contained_runtime_dependencies": True,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheelhouse", type=Path)
    parser.add_argument("output_zip", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    value = build(args.wheelhouse, args.output_zip)
    rendered = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != rendered:
            raise SystemExit("Lambda package inventory is stale")
    else:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
