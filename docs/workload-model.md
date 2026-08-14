# Workload and capacity model

The portfolio lab is intentionally small: one provisioned shard, deterministic synthetic users,
and short executions. A Kinesis shard supports a documented service envelope, but the repository
does not claim that limit as measured throughput. The managed run measures its own records/s and
bytes/s and stops before sustained throttling creates uncontrolled cost.

Capacity decisions use four signals: incoming bytes, incoming records, iterator age, and hottest
partition ratio. Scaling on average throughput alone is invalid when one partition key dominates.
The interview claim is the decision process and measured lab result—not fictional production
traffic.

