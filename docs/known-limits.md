# EventPulse Part 1 Stage 2 known limits

- The contract and ADR are design authority. No managed EventPulse consumer has run.
- The draft Python processor and Terraform remain in draft PR #1 and do not satisfy this contract without adaptation.
- The selected one-shard Lambda design is a bounded correctness lab. It does not prove multi-shard scaling, resharding, sustained throughput or production availability.
- The seven-day archive and dedupe horizons bound replay and duplicate protection. Older identities are quarantined rather than applied.
- Cross-service atomicity between S3 and DynamoDB is not claimed. The archive-first retry protocol closes the identified crash paths only after implementation and failure proof.
- SQS quarantine notification is at least once. DynamoDB quarantine/outbox state is authoritative.
- AWS latency, throughput, recovery, cost, teardown and raw completeness remain `UNCLAIMED`.
- Current EventPulse workload IAM permissions are absent. Stage 2 does not change them.
- The historical Terraform default `ap-south-1` is rejected by this authority; it must become `ap-south-2` in a later reviewed implementation change before deployment.
