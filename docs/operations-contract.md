# EventPulse operational and measurement contract

**Status:** `DESIGN_ONLY`. Thresholds are frozen here before any workload run.

## Workload profiles

| Profile | Rate | Duration | Mean encoded event | Maximum admitted event | Purpose |
| --- | ---: | ---: | ---: | ---: | --- |
| Smoke | 1 event/s | 5 minutes | 512 B | 16 KiB | Wiring and counters |
| Correctness | 100 events/s | 10 minutes | 512 B | 16 KiB | Semantic and failure cases |
| Upper bounded | 500 events/s | 10 minutes | 512 B | 16 KiB | Lag, skew and recovery observation |

The upper profile is permitted only after a dated admission check proves predicted bytes remain below 70% of one shard's 1 MiB/s write ceiling and predicted records remain below 70% of 1,000 records/s. At the declared mean, 500 events/s is 256,000 B/s before protocol overhead. Any changed size distribution requires recalculation. No profile is a production scale claim.

## Metric registry

| Metric | Population and clock | Required output |
| --- | --- | --- |
| Intake records/bytes | Successful producer acknowledgements in the run window | count, bytes and per-second series |
| Archived records | Unique canonical raw keys for the run/generation | count and digest inventory |
| Application effects | Successful new identity transactions | accepted count by event type |
| Output records | Closed session/materialized output keys for generation | count and canonical digest |
| Duplicate rate | identical duplicates / valid received events | count and ratio |
| Conflict rate | identity conflicts / valid received events | count and ratio |
| Late rate | accepted-late and beyond-watermark separately / valid events | counts and ratios |
| Quarantine rate | durable quarantine rows / received events | count by reason and ratio |
| Iterator age | `GetRecords.IteratorAgeMilliseconds`, maximum and series | p50/p95/p99/max over run window |
| End-to-end latency | output commit time minus ingest_time_ms for accepted events | p50/p95/p99/max, sample count, clock source |
| Recovery time | first failed invocation to backlog returning below pre-failure bound | milliseconds and timeline |
| Hot-key pressure | events for hottest user and shard / total events | both ratios and distribution |
| Cost | dated calculator forecast, usage quantities and settled billing later | forecast and observed values kept separate |

Latency percentiles use nearest-rank over the full accepted-event population, excluding quarantined and duplicate records while reporting those exclusions. Clocks use UTC epoch milliseconds; producer and Lambda clock skew is recorded. A run with missing samples or unreconciled clocks cannot support a latency claim.

## Frozen failure thresholds

- Source acknowledgements must equal accepted-to-stream count.
- Every source record must resolve to exactly one of: applied, identical duplicate, conflict quarantine, invalid quarantine, accepted-late application, or beyond-watermark quarantine.
- Raw archive reconciliation has zero unexplained missing or extra canonical keys.
- Materialized output equals the independent oracle exactly.
- No state or output version is applied twice.
- Iterator age alarm: maximum above 60,000 ms for two consecutive 60-second periods.
- Quarantine depth alarm: visible messages above zero for one 60-second period during an unacknowledged quarantine.
- Lambda errors or throttles outside a deliberate failure interval fail the run.
- A recovery run fails when backlog does not return below 5,000 ms within 300 seconds after consumer restoration.

## Evidence identity

Each run manifest freezes source SHA/tree, contract and schema digests, AWS account/region privately, resource IDs privately, seed, generation ID, event counts, size distribution, profile, thresholds, start/stop time, fault schedule and evidence output paths before publishing events.
