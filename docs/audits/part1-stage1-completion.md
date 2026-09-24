# EventPulse Part 1 Stage 1 completion receipt

**Result:** Exact-state and isolation audit completed at verified `main` commit `18b25390f05b81b92f0c5fba7239ac55956dff79`, tree `5fe27f8b895184fb4a4796b2658a363444bc4001`. This is a repository and scoped AWS boundary receipt, not an AWS workload or streaming performance result.

## Verification chain

| Gate | Evidence |
| --- | --- |
| Source checkpoint | Initial `main` `63f307763e1e712ba1a9770a755ea7adb41901b2`, tree `5f7dcc1951f9ddfcacf25b84c4c7168d2e77905c`. |
| Audit review | [PR #2](https://github.com/bhuvaneshwaranmurugan21/eventpulse-realtime-engagement-platform/pull/2), exact head `604a239f5f041a0294b96c1d17fad73994434825`, [audit run 36037084104](https://github.com/bhuvaneshwaranmurugan21/eventpulse-realtime-engagement-platform/actions/runs/36037084104) success. Five reviewed files; squash merge `b0fad295d6e403a3135225045156e2f94990b924`. |
| Main verification | [PR #3](https://github.com/bhuvaneshwaranmurugan21/eventpulse-realtime-engagement-platform/pull/3) added only `workflow_dispatch` to the unchanged audit job; exact-head run `36037710753` succeeded, then merged as `18b25390f05b81b92f0c5fba7239ac55956dff79`. Six files at `main` matched independently checked blob hashes. Their reconstructed Git tree is `5fe27f8b895184fb4a4796b2658a363444bc4001`. |
| Post-merge CI | [Run 36038011108](https://github.com/bhuvaneshwaranmurugan21/eventpulse-realtime-engagement-platform/actions/runs/36038011108) completed `audit` successfully. Its checkout log names `18b25390f05b81b92f0c5fba7239ac55956dff79`, and the validator ran with `--verify-source`. |
| AWS boundary | Private `ap-south-1` ZIP SHA-256 `e02e76faffd74aaa4f8a89d9dae391fad25d6a31a3d20b5945b427d3eaea25d5`; private `ap-south-2` ZIP SHA-256 `1711fbc41d8f13d65a97a9061a9c88d04ba75969663ddaba99d602f3e8ae7b69`; repository variable screenshot SHA-256 `9d061ab63a7ff45cecbbf4fcd0f2437b81dec3e9e7865ff44a181402fc6c14b6`. See the [audit](part1-stage1-exact-state.md) for scope and classification. |

## Continuation boundary

Draft [PR #1](https://github.com/bhuvaneshwaranmurugan21/eventpulse-realtime-engagement-platform/pull/1) remains separate and unmerged. The configured AWS region is `ap-south-2`; the draft Terraform default is `ap-south-1` and must be corrected and validated before any future deployment. Untagged or differently named resources were not excluded by the scoped inventory, and EventPulse-specific budget/cost was not measured. The OIDC role has no workload policies. No consumer runtime, managed recovery, latency, throughput, or AWS data processing has been verified by this stage.

The manifest at `evidence/part1/stage1/manifest.json` is the machine-readable receipt. This document records the prior verified main checkpoint; its own publication is a later documentation-only change and does not retroactively change the audited run's SHA.
