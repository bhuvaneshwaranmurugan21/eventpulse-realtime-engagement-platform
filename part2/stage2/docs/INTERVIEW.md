# Explaining EventPulse Part 2 Stage 2

The design question is not “can the handler retry?” It is “what durable facts exist if the
process dies at each unsafe boundary, and can a new process converge without inventing or
repeating application authority?”

The production handler exposes eight inert failpoints. The acceptance harness arms one point,
executes the real handler in a child, hard-exits with code 91, snapshots raw files and SQLite,
then starts a new child from disk. A separate standard-library oracle validates the intermediate
inventory and final state. The journal is append-only, ordinal and hash chained; real PIDs prove
the restart did not retain handler memory, while deterministic exports normalize those PIDs.

The strongest result is local application-effect idempotency: raw capture, SQLite transaction,
partial-batch, poison isolation, outbox ambiguity, and exhausted-failure evidence converge at all
eight enumerated boundaries. The honest limit is equally important: this says nothing about a
managed Lambda/Kinesis interruption. `LOCAL_VERIFIED` is the maximum claim.

Key trade-off: notification delivery is at-least-once, not exactly-once. If death occurs after
send but before the delivered marker, restart sends again with the same `outbox_id`. That stable
identity is the dedupe contract; pretending the transport is exactly-once would be incorrect.

Start a repository walkthrough at `fixtures/part2/stage2/crash-matrix.json`, then show the
failpoints in `src/eventpulse`, the child-process supervisor, the independent oracle, the twelve
negative controls, and finally the claim registry and known limits.
