# EventPulse Part 2 Stage 1 interview authority

## What this stage proves

Part 2 Stage 1 turns the frozen Part 1 authority into the real Lambda/Kinesis entry path. Literal Kinesis records pass through duplicate-key-safe decoding, JSON Schema admission, canonicalization, archive-first ordering, SQLite transactional state and Lambda partial-batch response construction. The same handler factory backs the deployable export and local harness; production code never imports the independent oracle.

A per-shard closure index lets user B's watermark advance close user A's eligible component without changing the contract into an incorrect per-user watermark. Poison records are durably quarantined and acknowledged; transient failures stop the shard at the first failed sequence number and return that identifier through the Lambda partial-batch response.

## Defensible boundary

The stage proves locally executed production-path behavior with filesystem and SQLite adapters. It does not prove managed AWS durability, service integration, throughput, latency, cost, teardown or raw-archive completeness. AWS adapter tests establish request construction and error classification only.

Application-effect crash/restart proof remains `DESIGN_ONLY` until the separately authorized Part 2 Stage 2 crash matrix is implemented and executed.
