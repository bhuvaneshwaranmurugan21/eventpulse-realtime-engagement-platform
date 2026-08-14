# Threat model

| Threat | Control in the design | Remaining proof |
|---|---|---|
| Public event archive | S3 public-access block and encryption | AWS policy/config evidence |
| Forged duplicate identity | Payload digest conflict fails closed | Managed replay test |
| Poison payload leakage | Metadata-only quarantine contract | Redaction test in adapter |
| Excessive consumer rights | Separate least-privilege role | IAM Access Analyzer review |
| Evidence tampering | Deterministic evidence digest | Immutable/versioned evidence store |
| Denial by hot key | Partition metric and alarm | Load test and recovery time |

This is a technical threat model, not a compliance certification.

