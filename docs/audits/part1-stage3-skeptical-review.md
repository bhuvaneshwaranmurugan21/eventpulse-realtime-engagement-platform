# EventPulse Part 1 Stage 3 skeptical review

## Review stance

The reviewer assumes that a green test can still be circular, incomplete or misleading. Every local claim must survive a counterexample and remain below its managed-proof ceiling.

## Findings and resolutions

| Finding | Risk | Resolution | Result |
| --- | --- | --- | --- |
| Future/stale thresholds lacked an explicit comparison clock. | Two correct-looking implementations could disagree. | Freeze `ingest_time_ms` as the local reference in the oracle specification; test equality and plus one. | Resolved locally. |
| The session-ID components were named but their byte preimage was not. | Cross-runtime session IDs could drift. | Freeze a canonical JSON array preimage and a literal golden digest. | Resolved locally. |
| Privacy-invalid payloads were forbidden but lacked a named disposition. | Invalid schema and privacy quarantine could be conflated. | Freeze `PRIVACY_VIOLATION` before semantic processing and document precedence. | Resolved locally. |
| Recovery expectations could become circular if read back from the evaluator. | Contract and oracle could repeat the same error. | Store literal expected durable effects, retry and safety text in fixtures and compare them with contract extraction. | Resolved. |
| Main contains no production consumer implementation. | Oracle success could be misrepresented as working streaming behavior. | Import isolation is enforced and managed/application-effect claims remain unpromoted. | Preserved as a future obligation. |
| A one-shard watermark oracle does not prove resharding. | Local correctness could be overstated as scale proof. | Shard independence is locally verified; multi-shard runtime and resharding remain unclaimed. | Correctly bounded. |
| Replay key isolation does not prove raw completeness. | A local replay could hide missing source records. | Integrity failure blocks local replay; source/archive/output reconciliation remains a future managed gate. | Correctly bounded. |

## Adversarial questions answered

- Exact watermark equality is accepted late; one millisecond below is beyond the watermark.
- Exact inactivity gap remains one session; gap plus one creates another component.
- Exact dedupe horizon remains protected; horizon plus one is quarantined as expired identity.
- Watermark equal to session end plus gap does not close the session; plus one does.
- The checkpoint never passes the lowest failed sequence.
- Same-generation replay deduplicates stable keys; another generation cannot overwrite them.
- Missing raw integrity fails replay rather than producing a partial success.
- A hot-key case reports an exact ratio rather than hiding behind the mean.

## Unresolved future proof obligations

Managed archive ordering, transactional effects, poison durability, partial-batch runtime behavior, complete raw capture, AWS replay, IAM, encryption, performance, cost and teardown are not established by Part 1. They retain their later acceptance IDs and claim ceilings in `docs/requirements/parts2-5-acceptance.json`.

## Review conclusion

The Stage 3 design is independently falsifiable and preserves honest claim boundaries. Final acceptance remains conditional on the complete clean-environment, negative-control, exact-head and post-merge evidence chain.
