# EventPulse Part 3 Stage 1 account rebind

On 2026-10-01 the owner confirmed that AWS account `887720497919` is unavailable and explicitly assigned previously unused account `773994909635` exclusively to EventPulse. The active Part 3 Stage 1 account boundary is therefore `773994909635` in `ap-south-2`.

This is an authority correction before AWS observation, not AWS evidence. It does not rewrite the historical Part 1 observations made in `887720497919`, grant mutation permission, promote an AWS claim, or establish that the EventPulse OIDC role and controls already exist in the replacement account. The regenerated kit must observe the replacement account and fail closed on missing identity, trust, policy, quota, resource, backend, budget or lease evidence.

The cumulative CI gate executes all Part 1 and Part 2 test suites and checks the terminal immutable manifest for each completed part. Earlier stage validators intentionally reject every later-stage path as out of scope, so invoking them on a legitimate successor would be a false failure; their accepted bytes remain protected by the terminal manifests instead.
