# Process-death proof decision

## Decision

Acceptance uses a parent supervisor and disposable child processes. A failpoint appends and
fsyncs one hash-chained journal row, then calls `os._exit(91)`. The parent snapshots durable state
before creating a different child process for restart. Exceptions, in-memory stores, retained
handlers, and cleanup callbacks cannot satisfy the proof.

## Durable authorities

- Raw objects are exclusive-create filesystem objects with digest verification.
- Application identity, state, output, quarantine, outbox, processing-commit, and failure records
  are SQLite authorities under `journal_mode=WAL` and `synchronous=FULL`.
- Notification attempts are repeatable; the outbox row is singular and carries stable identity.
- Retry-exhausted failures have a conditional object and singular `UNRESOLVED` database record.

## Determinism and independence

The journal stores actual PIDs, but canonical evidence replaces volatile PIDs and entry hashes
with ordinal labels after independently validating the raw hash chain and distinct process IDs.
The oracle imports only Python’s standard library and reads exported files and tables. Two fresh
locked Python 3.12 environments must produce byte-identical summaries.

## Descendant CI routing

The frozen Part 1 Stage 3 workflow and manifest remain byte-for-byte unchanged. The Stage 2
oracle lives under the Stage 2 authority namespace, so it cannot masquerade as a Part 1 oracle or
spuriously trigger that frozen workflow. The Stage 1 workflow uses explicit descendant mode once
the Stage 2 requirement marker exists: it validates immutable predecessor receipts historically
and runs cumulative behavior without recomputing the Stage 1 manifest from descendant source.
Shared runtime changes remain owned by the active Stage 2 workflow. This prevents both false
failures and silent weakening of predecessor evidence.
