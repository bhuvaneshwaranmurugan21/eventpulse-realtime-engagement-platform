# Architecture decisions

## Event time is the business clock

The processor advances a watermark from the highest observed event time minus a declared
lateness allowance. Records older than the watermark are retained for audit/reprocessing but do
not silently rewrite online aggregates. A production backfill publishes a new aggregate version.

## Delivery and state

Kinesis is at-least-once transport. EventPulse therefore treats source delivery, state mutation,
and checkpoint publication as separate concerns. Duplicate identity is checked before aggregate
mutation. A checkpoint digest covers deduplication state, aggregates, sessions, watermarks,
quarantine identities, and partition load. The local kernel proves atomic behavior; the managed
adapter must use conditional writes or an equivalent transactional checkpoint protocol.

## Partitioning and skew

User ID is the ordering and partition key. That preserves per-user order but permits celebrity or
bot hot keys. The lab records the hottest-partition ratio. Production mitigation is a deliberate
two-stage aggregation with deterministic key salting only where per-user ordering is not needed.

## Serving boundary

DynamoDB contains online aggregates, not the system of record. Immutable S3 events are the replay
authority. Quarantined records enter SQS with reason codes and redacted payload metadata.

