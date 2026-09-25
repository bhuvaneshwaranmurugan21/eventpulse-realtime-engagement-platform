# ADR 0001: Kinesis with a Python Lambda consumer

**Decision:** Accepted for the bounded EventPulse lab
**Claim level:** `DESIGN_ONLY`
**Region:** `ap-south-2`

## Context

The selected runtime must execute the Python processing path, preserve per-user order, expose retry and checkpoint behavior, fit a short low-cost lab, and produce observable evidence. The Stage 1 audit found no managed consumer and no workload permissions. The historical Glue/Spark proposal is therefore a candidate, not an inherited decision.

## Decision

Use Kinesis Data Streams with an AWS Lambda event source mapping and a Python handler. Use one provisioned shard for the bounded lab, `user_id` as the partition key, parallelization factor 1, partial batch failure reporting, bounded retries, batch bisection and an S3 on-failure destination. Use DynamoDB transactions and conditional versions for application effects, S3 conditional writes for raw capture, and an outbox-backed SQS quarantine channel.

The authoritative region is `ap-south-2`. The historical draft default `ap-south-1` is rejected; future implementation must correct that default before any deployment review.

AWS documents that a Kinesis event-source batch is checkpointed only when successful by default; `ReportBatchItemFailures` permits retry from the lowest failed sequence. Lambda event-source mappings can deliver records more than once, so the handler must be idempotent. DynamoDB transactions provide all-or-nothing writes and an idempotent client token. S3 `If-None-Match: *` prevents overwriting an existing raw key. Kinesis, Lambda, DynamoDB, S3, SQS and CloudWatch are available in Asia Pacific (Hyderabad).

## Configuration authority

- Batch size: 100 records
- Maximum batching window: 1 second
- Parallelization factor: 1
- `ReportBatchItemFailures`: enabled
- `BisectBatchOnFunctionError`: enabled
- Maximum retry attempts: 3
- Maximum record age: 3,600 seconds
- On-failure destination: dedicated S3 prefix with full failed invocation record
- Function reserved concurrency: 2 for the one-shard lab
- No VPC attachment or NAT gateway

## Alternatives

### AWS Glue streaming/Spark

Rejected for this bounded stage because the existing processor is plain Python, the design needs record-level conditional effects, and adopting Spark would require a separate semantic implementation and longer-lived job lifecycle. Reconsider when windowed analytical state or multi-shard sustained processing justifies that runtime and the same oracles can qualify it.

### Managed Service for Apache Flink

Rejected because it would introduce a second state/checkpoint model and implementation language/runtime surface before the contract is executable. It is a future candidate for larger event-time workloads requiring native keyed state and timers.

### ECS/Fargate with KCL

Rejected for the lab because task lifecycle, scaling and KCL lease management add operational scope without improving the current proof target. Reconsider for sustained workloads that outgrow Lambda execution limits.

## Consequences

Lambda keeps idle cost and packaging small and maps directly to the Python code path. The application must explicitly solve idempotency and cross-service recovery. Long-running large state is unsuitable; state lives in DynamoDB. Per-user order depends on `partition_key=user_id`. One shard is a bounded correctness lab, not a scalability claim.

## Primary sources reviewed on 2026-09-25

- https://docs.aws.amazon.com/lambda/latest/dg/with-kinesis.html
- https://docs.aws.amazon.com/lambda/latest/dg/services-kinesis-batchfailurereporting.html
- https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html
- https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html
- https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html
- https://docs.aws.amazon.com/general/latest/gr/ak.html
- https://docs.aws.amazon.com/general/latest/gr/lambda-service.html
