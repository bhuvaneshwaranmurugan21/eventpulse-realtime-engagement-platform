# Managed streaming runbook

1. Create a run ID, pin the event contract digest, and record the Git commit.
2. Apply only the bounded lab topology in `ap-south-1`; record all resource identifiers.
3. Publish a deterministic baseline workload and capture source/accepted/duplicate counts.
4. Inject duplicates, changed-payload identities, late events, poison records, and one hot key.
5. Terminate the consumer before checkpoint publication, restart it, and compare digests.
6. Capture iterator age, errors, quarantine depth, throughput, p50/p95 latency, and state totals.
7. Re-read the immutable archive and prove aggregate equality after replay.
8. Export a redacted evidence bundle and compute its digest.
9. Destroy the stack, verify streams/queues/tables are gone, and record final cost.

Never place credentials, raw customer data, account IDs, or unmasked ARNs in repository evidence.

