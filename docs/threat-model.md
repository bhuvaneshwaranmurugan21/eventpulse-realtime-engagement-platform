# EventPulse Stage 2 threat and failure model

| Threat or failure | Preventive control | Detection | Remaining proof |
| --- | --- | --- | --- |
| Forged or reused event identity | Canonical digest and conditional identity ledger | conflict metric and quarantine row | Managed conflicting-ID run |
| Future timestamp advances watermark | 60-second future bound before watermark update | FUTURE_CLOCK reason | Boundary oracle and AWS run |
| Old event is counted after TTL | EXPIRED_IDENTITY quarantine after horizon | expiry metric | TTL boundary run |
| Hot user overloads one shard | user partitioning plus explicit hottest-key metric | shard/key distribution and iterator age | Bounded skew run |
| Poison record blocks shard | durable quarantine then success; bounded retry for transient errors | quarantine and failure destination | Poison and transient failure run |
| Crash loses archive or state | archive-first plus idempotent transaction | source/archive/state reconciliation | Injected crash matrix |
| Retry double-applies output | identity and version conditions | duplicate and conditional-failure metrics | Retry/restart run |
| Replay overwrites live results | isolated generation namespace | generation mismatch gate | Same/new-generation replay tests |
| Public archive exposure | S3 public-access block and TLS | policy/config evidence | AWS configuration inspection |
| Excess runtime privilege | exact resource IAM matrix | policy simulation and Access Analyzer | Reviewed IAM admission |
| Evidence tampering | canonical manifests and SHA-256 digests | independent digest recomputation | Preserved AWS evidence bundle |
| Cost runaway | no NAT/cluster, four-hour lease, forecast and hard stop | budget/forecast/resource inventory | Part 3 admission and teardown |

This model is technical design authority, not compliance certification or proof of AWS execution.
