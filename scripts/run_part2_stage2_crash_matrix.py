#!/usr/bin/env python3
"""Run the eight Stage 2 crash boundaries through the production handler."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "part2/stage2/oracles"))

from part2_stage1_helpers import batch, event, record  # noqa: E402
from part2_stage2_recovery import digest, export, verify, verify_frozen_result  # noqa: E402

from eventpulse.canonical import canonical_bytes, sha256_bytes  # noqa: E402
from eventpulse.errors import InvariantViolation, RetryableDependencyError  # noqa: E402
from eventpulse.handler import create_handler  # noqa: E402
from eventpulse.local import (  # noqa: E402
    FilesystemFailureDestination,
    FilesystemOutboxPublisher,
    LocalRuntime,
    SQLiteApplicationStore,
    create_local_runtime,
)
from eventpulse.models import AdmittedEvent, ApplyResult, RejectedEvent  # noqa: E402
from eventpulse.recovery import (  # noqa: E402
    CRASH_BOUNDARIES,
    drain_outbox,
    record_exhausted_failure,
    require_no_unresolved_failures,
)

CRASH_EXIT = 91
GOLDEN = ROOT / "fixtures/part2/stage2/golden-digests.json"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


@dataclass
class JournalCrashProbe:
    root: Path
    armed: str | None
    phase: str
    case_id: str

    def reach(self, boundary: str, *, detail: dict[str, str]) -> None:
        if boundary not in CRASH_BOUNDARIES:
            raise InvariantViolation(f"unknown crash boundary: {boundary}")
        path = self.root / "crash-journal.jsonl"
        prior = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        previous = "GENESIS" if not prior else json.loads(prior[-1])["entry_sha256"]
        row: dict[str, object] = {
            "boundary": boundary,
            "detail": dict(sorted(detail.items())),
            "ordinal": len(prior) + 1,
            "phase": self.phase,
            "previous_sha256": previous,
            "process_id": os.getpid(),
            "run_id": f"{self.case_id}:{self.phase}",
        }
        row["entry_sha256"] = sha256_bytes(canonical_bytes(row))
        with path.open("a", encoding="utf-8") as stream:
            stream.write(canonical_bytes(row).decode("utf-8") + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if boundary == self.armed:
            os._exit(CRASH_EXIT)


@dataclass
class TransientStore:
    delegate: SQLiteApplicationStore

    def isolate_rejected(self, rejected: RejectedEvent, raw_key: str) -> ApplyResult:
        return self.delegate.isolate_rejected(rejected, raw_key)

    def apply_event(
        self, admitted: AdmittedEvent, raw_key: str, generation_id: str
    ) -> ApplyResult:
        if admitted.event["event_id"] == "event-transient":
            raise RetryableDependencyError("deterministic Stage 2 transient")
        return self.delegate.apply_event(admitted, raw_key, generation_id)

    def drain_closures(self, shard_id: str, generation_id: str, limit: int) -> bool:
        return self.delegate.drain_closures(shard_id, generation_id, limit)


def _runtime(root: Path, probe: JournalCrashProbe) -> LocalRuntime:
    return create_local_runtime(root, crash_probe=probe)


def _valid_batch() -> dict[str, Any]:
    return batch(record(event("event-success", 10_000_000), "1"))


def _poison_batch() -> dict[str, Any]:
    value = event("event-poison", 10_000_000)
    value["payload"] = {"email": "redacted@example.invalid"}
    return batch(record(value, "1"))


def _partial_batch() -> dict[str, Any]:
    return batch(
        record(event("event-prefix", 10_000_000), "1"),
        record(event("event-transient", 10_000_001), "2"),
        record(event("event-later", 10_000_002), "3"),
    )


def _run_handler(runtime: LocalRuntime, payload: dict[str, Any], transient: bool) -> dict[str, Any]:
    if transient:
        runtime.store = cast(Any, TransientStore(runtime.store))
    return create_handler(runtime)(payload, None)


def deny_network(event: str, _arguments: tuple[object, ...]) -> None:
    """Fail closed if a child attempts a socket operation."""
    if event.startswith("socket."):
        raise RuntimeError(f"network operation prohibited in crash harness: {event}")


def child(root: Path, case_id: str, armed: str | None, phase: str) -> dict[str, Any]:
    sys.addaudithook(deny_network)
    probe = JournalCrashProbe(root, armed, phase, case_id)
    if case_id in {"EP-CRASH-01", "EP-CRASH-02", "EP-CRASH-03", "EP-CRASH-04"}:
        return _run_handler(_runtime(root, probe), _valid_batch(), False)
    if case_id == "EP-CRASH-05":
        return _run_handler(_runtime(root, probe), _partial_batch(), True)
    if case_id == "EP-CRASH-06":
        return _run_handler(_runtime(root, probe), _poison_batch(), False)
    if case_id == "EP-CRASH-07":
        runtime = _runtime(root, probe)
        _run_handler(runtime, _poison_batch(), False)
        drain_outbox(
            runtime.store,
            FilesystemOutboxPublisher(root / "notifications"),
            probe,
        )
        return {"batchItemFailures": []}
    if case_id == "EP-CRASH-08":
        runtime = _runtime(root, probe)
        payload = canonical_bytes(_partial_batch())
        record_exhausted_failure(
            runtime.store,
            FilesystemFailureDestination(root / "failure-destination"),
            probe,
            invocation_id="invocation-exhausted-1",
            earliest_sequence="1",
            body=payload,
        )
        blocked = False
        try:
            require_no_unresolved_failures(runtime.store)
        except InvariantViolation:
            blocked = True
        return {
            "blocked": blocked,
            "unresolved_failures": runtime.store.unresolved_failure_count(),
        }
    raise InvariantViolation(f"unknown crash boundary: {case_id}")


def _child_command(
    root: Path, case_id: str, armed: str | None, phase: str
) -> list[str]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child",
        "--root",
        str(root),
        "--case",
        case_id,
        "--phase",
        phase,
    ]
    if armed is not None:
        command.extend(["--armed", armed])
    return command


def _environment() -> dict[str, str]:
    return {
        **os.environ,
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "TZ": "UTC",
    }


def supervise(output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"refusing to reuse evidence root: {output}")
    output.mkdir(parents=True)
    results = []
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for case_id in CRASH_BOUNDARIES:
        case_root = output / case_id
        case_root.mkdir()
        crashed = subprocess.run(  # noqa: S603 - fixed local interpreter and script
            _child_command(case_root, case_id, case_id, "crash"),
            capture_output=True,
            check=False,
            env=_environment(),
            text=True,
            timeout=30,
        )
        if crashed.returncode != CRASH_EXIT:
            raise RuntimeError(
                f"{case_id} expected exit {CRASH_EXIT}; got {crashed.returncode}: "
                f"{crashed.stdout} {crashed.stderr}"
            )
        after_crash = export(case_root)
        write_json(case_root / "after-crash.json", after_crash)

        restarted = subprocess.run(  # noqa: S603 - fixed local interpreter and script
            _child_command(case_root, case_id, None, "restart"),
            capture_output=True,
            check=False,
            env=_environment(),
            text=True,
            timeout=30,
        )
        if restarted.returncode != 0:
            raise RuntimeError(f"{case_id} restart failed: {restarted.stdout} {restarted.stderr}")
        response = json.loads(restarted.stdout)
        after_restart = export(case_root)
        write_json(case_root / "after-restart.json", after_restart)
        write_json(case_root / "response.json", response)
        errors = verify(case_id, after_crash, after_restart, response)
        if errors:
            raise RuntimeError(f"{case_id} oracle mismatch: {errors}")
        result = {
            "after_crash_sha256": digest(after_crash),
            "after_restart_sha256": digest(after_restart),
            "case_id": case_id,
            "crash_exit": crashed.returncode,
            "oracle": "PASS",
            "response_sha256": digest(response),
        }
        frozen_errors = verify_frozen_result(result, golden)
        if frozen_errors:
            raise RuntimeError(f"{case_id} frozen oracle mismatch: {frozen_errors}")
        results.append(result)
    summary = {
        "authority": "EP-FUTURE-P2-002",
        "boundaries_passed": len(results),
        "claim_ceiling": "LOCAL_VERIFIED",
        "network_calls": 0,
        "production_entry": "eventpulse.handler.create_handler",
        "results": results,
        "status": "PASS",
    }
    write_json(output / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--case", choices=CRASH_BOUNDARIES)
    parser.add_argument("--armed", choices=CRASH_BOUNDARIES)
    parser.add_argument("--phase", choices=("crash", "restart"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.child:
        if args.root is None or args.case is None or args.phase is None:
            parser.error("--child requires --root, --case and --phase")
        result = child(args.root, args.case, args.armed, args.phase)
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.output is None:
        parser.error("supervisor requires --output")
    print(json.dumps(supervise(args.output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
