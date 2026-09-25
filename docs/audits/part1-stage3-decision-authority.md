# EventPulse Part 1 Stage 3 decision authority

**Status:** Accepted
**Entry checkpoint:** `9394d1795d3e4e9622e4f580aef61be455f6ce4b` / tree `ad4077ea62bcae275030a7c389d5a0538a07d6fc`
**Region authority:** `ap-south-2` for future managed work; no AWS operation belongs to Stage 3.

## Entry receipt

- Repository/default branch: `bhuvaneshwaranmurugan21/eventpulse-realtime-engagement-platform` / `main`
- Verified remote main: `9394d1795d3e4e9622e4f580aef61be455f6ce4b`
- Verified remote tree: `ad4077ea62bcae275030a7c389d5a0538a07d6fc`
- Successful predecessor push runs: Stage 2 Contract `36098207537`; Stage 1 Audit `36098207533`
- Historical draft PR #1: open and separate at head `056f536a458b2573dbca8e9eeefee92ec48a14fc`; its 32-file draft is not copied, modified, merged or treated as authority
- Isolated branch: `part1-stage3-executable-oracles`, created directly from the verified main checkpoint
- Dependency boundary: Python standard library only; no package is added to the repository

Any different remote main, source tree, PR #1 state, or predecessor conclusion invalidates this receipt and stops publication until requalification.

Stage 3 makes the completed Stage 2 contract locally falsifiable. Fifty deterministic fixtures cover admission, identity, clock, watermark, shard independence, session boundaries, accepted-late bridging, dedupe expiry, every named crash boundary, checkpoint safety, replay generation isolation and hot-key measurement. The reference evaluator uses only the Python standard library and imports no production processing code.

Three byte-level details were not explicit enough to calculate exact outputs. `contracts/stage3-oracle-spec-v1.json` resolves them without changing Stage 2 behavior:

1. `ingest_time_ms` is the local-oracle reference for future/stale clock checks.
2. A session ID hashes the canonical JSON array `[contract_version,generation_id,user_id,sorted_member_event_ids]`.
3. A prohibited payload key is quarantined as `PRIVACY_VIOLATION`; disposition precedence is frozen before evaluation.

The fixture expectations are literal reviewed values. Recovery expectations are not copied from evaluator output, and the session-ID golden digest is precomputed from the documented preimage. The evaluator compares full content and counts, then emits a canonical corpus digest.

Stage 3 may promote only enumerated local oracle behavior to `LOCAL_VERIFIED`. Archive persistence, DynamoDB atomicity, poison durability, managed replay, consumer operation, AWS recovery, performance, spend and teardown remain `DESIGN_ONLY` or `UNCLAIMED`.

Completion requires all 30 acceptance criteria, controlled corruptions, clean-environment reproducibility, exact-head CI, guarded authority merge, merged-main CI, and a separate Part 1 completion receipt.
