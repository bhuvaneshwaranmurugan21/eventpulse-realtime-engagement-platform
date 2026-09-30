#!/usr/bin/env python3
"""Fail-closed structural Stage 3 validator."""

from __future__ import annotations

import argparse
import ast
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_SHA = "f01117690788f3fcfa7751be119a3856c3b3aac6"
BASE_TREE = "a35bafb242c21c21a00e4c88ffec5fb788ec17d1"
GIT = shutil.which("git") or "git"


def load(path: str) -> object:
    return json.loads((ROOT / path).read_text())


def validate() -> list[str]:
    errors = []
    requirements = load("part2/stage3/docs/requirements.json")
    branches = load("part2/stage3/docs/critical-branches.json")
    trace = load("part2/stage3/docs/traceability.json")
    properties = load("evidence/part2/stage3/property-results.json")
    mutations = load("evidence/part2/stage3/mutation-results.json")
    critical = load("evidence/part2/stage3/critical-coverage.json")
    if len(requirements["criteria"]) != 33 or len(set(requirements["criteria"])) != 33:
        errors.append("criteria registry drift")
    if (
        requirements["predecessor_commit"] != BASE_SHA
        or requirements["predecessor_tree"] != BASE_TREE
    ):
        errors.append("predecessor drift")
    if len(branches["branches"]) != 25 or critical["critical_branches_observed"] != 25:
        errors.append("critical branch proof incomplete")
    if properties["total_generated_checks"] != 208 or properties["status"] != "PASS":
        errors.append("property proof incomplete")
    if mutations["mutants_killed"] != 12 or mutations["status"] != "PASS":
        errors.append("mutation proof incomplete")
    if len(trace["mappings"]) != 33:
        errors.append("traceability incomplete")
    tree = ast.parse((ROOT / "part2/stage3/oracles/identity_oracle.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            ("eventpulse", "tests")
        ):
            errors.append("oracle imports production")
    changed = set(
        subprocess.check_output(  # noqa: S603 - fixed git and immutable baseline
            [GIT, "diff", "--name-only", BASE_SHA, "--"], cwd=ROOT, text=True
        ).splitlines()
    )  # noqa: S603
    allowed = (
        ".github/workflows/part2-stage3-",
        "evidence/part2/stage3/",
        "fixtures/part2/stage3/",
        "part2/stage3/",
        "scripts/build_part2_stage3_",
        "scripts/run_part2_stage3_",
        "scripts/validate_part2_stage3.py",
        "tests/test_part2_stage3_",
    )
    errors.extend(f"out-of-scope file: {item}" for item in changed if not item.startswith(allowed))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-source", action="store_true")
    args = parser.parse_args()
    errors = validate()
    if args.verify_source:
        tree = subprocess.check_output(  # noqa: S603 - fixed git and immutable baseline
            [GIT, "show", "-s", "--format=%T", BASE_SHA], cwd=ROOT, text=True
        ).strip()  # noqa: S603
        if (
            tree != BASE_TREE
            or subprocess.run(  # noqa: S603 - fixed git and immutable baseline
                [GIT, "merge-base", "--is-ancestor", BASE_SHA, "HEAD"], cwd=ROOT
            ).returncode
        ):
            errors.append("source identity failed")  # noqa: S603
    if errors:
        print("\n".join(errors))
        return 1
    print("EventPulse Part 2 Stage 3 validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
