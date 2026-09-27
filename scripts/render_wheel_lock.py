#!/usr/bin/env python3
"""Render a platform-specific hash lock from a qualified wheel directory."""

from __future__ import annotations

import argparse
import hashlib
import zipfile
from email.parser import BytesParser
from pathlib import Path


def wheel_identity(path: Path) -> tuple[str, str]:
    with zipfile.ZipFile(path) as archive:
        metadata_path = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        metadata = BytesParser().parsebytes(archive.read(metadata_path))
    return str(metadata["Name"]), str(metadata["Version"])


def render(directory: Path) -> str:
    rows: list[tuple[str, str, str]] = []
    for wheel in directory.glob("*.whl"):
        name, version = wheel_identity(wheel)
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        rows.append((name, version, digest))
    lines = [
        "# Generated from qualified CPython 3.12 Linux wheels; do not edit by hand.",
        "# Install with: python -m pip install --require-hashes -r <this-file>",
    ]
    lines.extend(
        f"{name}=={version} --hash=sha256:{digest}"
        for name, version, digest in sorted(rows, key=lambda row: row[0].lower())
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel_directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    value = render(args.wheel_directory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(value, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
