# EventPulse Part 2 Stage 1 known limits

- The production entry path is locally executed with filesystem and SQLite durability. This is not evidence that S3, DynamoDB, Lambda, Kinesis, SQS or CloudWatch has run.
- AWS request construction and error classification use injected clients only. Managed closure execution, service conditions and interruption recovery remain unverified.
- Stage 1 ordinary-path transactions and restartable local state do not satisfy the eight crash-boundary proof requirement. That proof belongs to Part 2 Stage 2.
- The bounded closure protocol acknowledges only after closure work drains; process-killing restart evidence is still pending.
- Branch-aware coverage describes this bounded Stage 1 suite, not whole-project behavior or production reliability.
