# Bounded AWS topology

The module creates an encrypted replay/evidence bucket, one provisioned Kinesis shard, on-demand
DynamoDB state, an encrypted SQS quarantine queue, and short-retention CloudWatch signals. It does
not deploy a consumer executable; the correctness kernel and managed adapter remain separate so a
validated topology cannot be mistaken for a successful streaming run.

