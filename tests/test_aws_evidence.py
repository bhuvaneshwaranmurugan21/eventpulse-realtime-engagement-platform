from eventpulse.aws_evidence import validate_aws_lab_evidence
from eventpulse.model import digest


def valid_bundle() -> dict[str, object]:
    payload: dict[str, object] = {
        "project": "eventpulse-realtime-engagement-platform",
        "claim_level": "AWS_LAB_VERIFIED",
        "production_claim": False,
        "result": "PASS",
        "region": "ap-south-1",
        "run_id": "ep-20260814-001",
        "commit_sha": "0123456789abcdef",
        "resources": {
            "archive_bucket": "eventpulse-redacted-archive",
            "stream_name": "eventpulse-lab-events",
            "state_table": "eventpulse-lab-state",
            "quarantine_queue": "eventpulse-lab-quarantine",
            "cloudwatch_log_group": "/aws/eventpulse/redacted",
        },
        "failure_tests": [
            "conflicting_identity",
            "late_event",
            "poison_record",
            "consumer_crash",
            "hot_key",
        ],
        "metrics": {
            "records_processed": 1000,
            "runtime_seconds": 25.1,
            "p95_latency_ms": 18.4,
            "cost_usd": 0.55,
        },
        "teardown": {"destroyed": True, "verified_at": "2026-08-14T12:00:00Z"},
    }
    payload["evidence_digest"] = digest(payload)
    return payload


def test_complete_aws_evidence_contract_passes() -> None:
    assert validate_aws_lab_evidence(valid_bundle()) == ()


def test_evidence_contract_fails_closed() -> None:
    payload = valid_bundle()
    payload["failure_tests"] = "hot_key"
    payload["production_claim"] = True
    errors = validate_aws_lab_evidence(payload)
    assert any("production_claim" in error for error in errors)
    assert any("failure tests missing" in error for error in errors)
    assert any("evidence_digest" in error for error in errors)

