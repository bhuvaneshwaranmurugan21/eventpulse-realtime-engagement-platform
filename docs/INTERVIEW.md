# EventPulse Stage 2 interview walkthrough

## Two-minute explanation

EventPulse is an event-time engagement platform whose correctness contract is fixed before the managed consumer is built. A versioned envelope gives every record an immutable identity and user partition key. Per-shard watermarks accept bounded disorder without allowing idle shards to stall unrelated users. Sessions publish only after watermark closure, so an accepted bridge event can merge open components before one immutable result is emitted.

Kinesis and Lambda provide at-least-once delivery. Raw bytes are conditionally archived first, then DynamoDB atomically commits identity, state, materialized output and an outbox row. A retry after the transaction sees the existing identity/version and makes no repeated application effect. This is a design for idempotent effects; transport exactly once is deliberately not claimed.

## Three decisions to defend

1. **Lambda over Glue/Spark:** it runs the Python path directly, fits a short idle-free lab and exposes bounded Kinesis retry controls. Spark is reconsidered for sustained analytical windows or state that no longer fits the serverless design.
2. **Per-shard watermark with user partitioning:** one user's events stay ordered and an idle shard cannot stall another. The tradeoff is that repartitioning and multi-shard expansion require a separately proven state migration strategy.
   The thirty-minute allowed-lateness window matches the session gap so an out-of-order midpoint can still merge two open components before publication.
3. **Archive first, DynamoDB transaction second:** there is no cross-service transaction. An orphan archive is safe and replayable; a transaction without raw evidence is prohibited. Retries are guarded by deterministic keys, transaction tokens and versions.

## Honest claim boundary

Stage 2 proves the contract documents are complete, internally consistent and resistant to controlled corruption. It does not prove a managed consumer, AWS recovery, throughput, latency, cost or teardown. Those claims require source-bound AWS runs and independent oracle comparison.

## Expected questions

- Why does an event exactly at the watermark pass? The contract defines `< watermark` as beyond; equality is accepted late.
- What happens after dedupe TTL? The event is archived and quarantined as expired identity, never silently counted again.
- How are session IDs stable? They are computed from the closed generation and sorted member IDs; live sessions are not published before closure.
- What if S3 succeeds and DynamoDB fails? Retry verifies the same raw digest and repeats the idempotent transaction.
- What if DynamoDB succeeds and Lambda crashes? Redelivery hits the identity/version guards and does not repeat the application effect.
- Can you claim exactly once? No. Delivery can repeat; the future proof target is idempotent application effects.
