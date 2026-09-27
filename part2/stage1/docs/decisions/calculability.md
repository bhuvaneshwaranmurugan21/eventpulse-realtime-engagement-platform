# Part 2 Stage 1 calculability decision

**Status:** accepted, semantic-preserving implementation detail

**Contract:** EventPulse 1.0.0

**Claim ceiling:** `LOCAL_VERIFIED`

## Malformed transport identity

The raw identity of a record that cannot produce a valid `event_id` is:

`rejected/source=<sha256(eventSourceARN)>/shard=<shard-id>/sequence=<sequence>/transport=<sha256(exact received data text)>.bin`

The archive body is the exact base64-decoded byte sequence when decoding succeeds and the exact ASCII transport text when it does not. The metadata records which representation was used. Quarantine and outbox identifiers are SHA-256 digests of canonical arrays containing the contract version, disposition, source coordinate and body digest. Raw bytes, transport text and unredacted identifiers never enter logs or metrics.

Valid admitted events use the existing semantic digest and:

`raw/schema=1.0.0/date=<UTC ingest date>/event_id=<event-id>/<payload-digest>.json`

Retries therefore produce the same key. A different source coordinate or body produces a different rejected key.

## Bounded cross-user closure

The shard watermark remains authoritative. Each accepted event transaction records the identity and event, advances the shard maximum conditionally, updates at most two neighboring component rows plus one merged component row, and creates a deterministic closure-work row for the prospective shard watermark.

The same handler drains closure work in pages of 20 components. Each page is a separate conditional transaction; the Kinesis record is not acknowledged while work remains. If execution budget expires, the record is returned as the earliest unresolved retryable failure. On retry, stable identity and work identifiers resume the drain. Thus another user's event can close due components without a table scan, and work survives interruption without a new runtime or trigger.

Open event members are separate rows. Component metadata stores only bounds and version, avoiding an unbounded DynamoDB item. Closure output consists of a bounded header plus member rows; the final session ID is computed from the sorted member IDs. The Stage 1 SQLite adapter implements the same logical state. Full interruption proof remains Part 2 Stage 2.

## Bounds

- One event application transaction: at most 9 DynamoDB items (identity, event member, shard, aggregate, closure work, one new component, and at most two replaced components plus optional outbox).
- One closure page: at most 20 components; request construction caps a transaction below 100 items and checks the 4 MiB serialized-request ceiling before dispatch.
- Component and member items are capped by the frozen 16 KiB event admission limit and never embed the raw event.
- `ClientRequestToken`: first 36 hexadecimal characters of SHA-256 over the canonical token preimage, below DynamoDB's 36-character limit.
- All generated IDs are 64 lowercase hexadecimal characters.

No Part 1 behavior changes: watermark scope, strict closure inequality, archive-first ordering, generation isolation and acknowledgement rules remain unchanged.

Identity uniqueness is scoped by `(generation_id, event_id)`. The semantic key remains
`event_id` inside a generation, while a separately authorized replay generation can apply
the same retained raw event without consulting or overwriting live-generation identity or
state. The raw archive key remains generation-independent and immutable.
