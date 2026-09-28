# Part 2 Stage 2 known limits

- The proof covers eight named boundaries in the file-backed SQLite/filesystem runtime. It is
  not evidence of managed AWS durability.
- Duplicate notification delivery is intentionally possible between send and delivered-marker
  commit; stable `outbox_id` preserves downstream dedupe authority.
- Failure-destination records remain `UNRESOLVED` until a separately authorized adjudication
  workflow exists. Silent success is prohibited.
- The recovery harness is deterministic and makes no network calls. It does not measure
  throughput, tail latency, cost, capacity, or operational teardown.
- Static AWS request shapes remain `DESIGN_ONLY`; managed consumer, durable AWS recovery, and
  managed raw completeness remain `UNCLAIMED`.
- `EP-FUTURE-P2-003` has not been attempted.
