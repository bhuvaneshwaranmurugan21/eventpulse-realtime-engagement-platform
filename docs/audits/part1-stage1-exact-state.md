# EventPulse Part 1 Stage 1 — exact-state audit

Status: **IN PROGRESS**. Observation checkpoint: 2026-09-24 13:01:50 UTC. This is an audit of EventPulse only. The machine-readable evidence is in `evidence/part1/stage1/manifest.json`.

## Source and PR reality

| Item | Observed evidence | Limit |
| --- | --- | --- |
| Repository | `bhuvaneshwaranmurugan21/eventpulse-realtime-engagement-platform`, GitHub repository ID `1333031049` | Identity was checked through repository metadata. |
| Default branch | `main` commit `63f307763e1e712ba1a9770a755ea7adb41901b2`, tree `5f7dcc1951f9ddfcacf25b84c4c7168d2e77905c` | One tracked file: `.github/workflows/aws-oidc-identity.yml`. |
| Governance | Branch metadata reported `protected=false`; repository rulesets returned `[]` | No branch rule is treated as an approval substitute. |
| Historical [PR #1](https://github.com/bhuvaneshwaranmurugan21/eventpulse-realtime-engagement-platform/pull/1) | Open draft; base is the above `main`; head `056f536a458b2573dbca8e9eeefee92ec48a14fc`, tree `7214d03f3b5b18bfbffedc19d856f5a43ebaf1a8`; 32 changed files, 1,315 additions, one deletion | Its source, tests, Terraform and README are **draft-only**, not default-branch implementation. Retain for separate review; do not merge as part of this audit. |
| PR CI | [CI run 31772945884](https://github.com/bhuvaneshwaranmurugan21/eventpulse-realtime-engagement-platform/actions/runs/31772945884): `quality` success; [Infrastructure run 31772945898](https://github.com/bhuvaneshwaranmurugan21/eventpulse-realtime-engagement-platform/actions/runs/31772945898): `validate` success, both at the exact PR head | These checks support that draft head only. They are not proof of managed AWS execution. |
| Main identity | [OIDC run 31722050727](https://github.com/bhuvaneshwaranmurugan21/eventpulse-realtime-engagement-platform/actions/runs/31722050727): `verify-identity` success at the exact main commit | The workflow checks an assumed role name. It does not inventory current account resources or requalify current trust. |

The draft contains `.github` workflows, schema, docs, local evidence, Terraform, a Python package and three test files. The source was reconstructed locally from the exact PR head and its Git tree reproduced as `7214d03f3b5b18bfbffedc19d856f5a43ebaf1a8`. No part of the draft was imported into this audit branch.

## Baseline check and limitations

- The draft declares Python `>=3.11` and dev dependencies `mypy==1.17.1`, `pytest==8.4.1`, `pytest-cov==6.2.1`, `ruff==0.12.8`. The GitHub `quality` job at the exact head reported success for installation, Ruff, mypy, pytest and simulation. The PR description reports seven tests and 90.28% coverage; this audit treats those numbers as the PR author's statement, not an independently remeasured local result.
- This execution workspace has Python 3.12.14. Installing the declared dev extra in a disposable venv exited 1 because its package-index proxy timed out while fetching `mypy==1.17.1`. This is `ENVIRONMENT_BLOCKED_PACKAGE_INDEX`, not a passing or failing code test. No undeclared replacement dependency was installed.
- The local standard-library simulation did execute from the exact draft tree. The regenerated file matched the committed `evidence/local-simulation.json` byte for byte, SHA-256 `56e5d11006d87304062ac7809b467ce9c77f6df30656e9428d3d23b479609cf6`.
- No Terraform binary exists in this workspace. The exact-head GitHub `validate` job reported success for formatting, backend-disabled initialization and validation. No Terraform apply or AWS workload occurred here.

## Claim and implementation inventory

| Claim or behavior | Exact source | Classification and finding |
| --- | --- | --- |
| Event identity, duplicate suppression, lateness, poison handling, session state and checkpoint simulation | Draft `src/eventpulse/processor.py`, `tests/test_processor.py`, `evidence/local-simulation.json` | Local model on draft head; CI passed and deterministic simulation reproduced. The draft is not on `main`. |
| Atomic micro-batch and restart | Draft `StreamProcessor.process_batch()` copies in-memory state, optionally raises before assignment, then creates a checkpoint; `restore()` reads an in-memory `Checkpoint` value | `LOCAL_VERIFIED` in that narrow model. It is not durable cross-service checkpoint or managed restart proof. |
| Real Kinesis consumer and DynamoDB/S3/SQS effects | Draft Terraform resources and architectural/runbook descriptions | `DESIGN_ONLY`: the draft tree contains no consumer runtime or integration executing `StreamProcessor` against those services. |
| AWS processing latency, throughput, cost and recovery | Draft `docs/claims.yaml` keeps `aws_stream_processing` at `DESIGN_ONLY` | `UNCLAIMED` as a measured outcome. `src/eventpulse/aws_evidence.py` validates a bundle shape; its test uses constructed values and is not an actual AWS run. |
| Exactly-once transport | Draft `docs/claims.yaml` says `NOT_CLAIMED` | Not asserted. The Part 1 plan's taxonomy says `UNCLAIMED`; this vocabulary difference needs a deliberate mapping, not a silent rewrite. |

The current single-session-per-user tuple in `processor.py` cannot represent two retained sessions and merge them when a later bridge event arrives; its deduplication map also has no expiry. These are design/coverage gaps to carry forward, not behavior changes within this audit. The README presents local correctness and explicitly says Terraform does not prove managed AWS execution. The repository description calls latency “measurable”; it does not present an observed numeric result.

## EventPulse isolation checkpoint

The main workflow names `EventPulseGitHubOidcRole` and reads repository variables `AWS_ROLE_ARN` and `AWS_REGION`. Draft Terraform defaults its region to `ap-south-1`, uses `Project=EventPulse`, an `eventpulse-lab` naming prefix, `RunId` and `ExpiresAt` tags. These are **declared** settings, not a fresh authenticated account/region/role-trust or resource-inventory observation. There is no AWS CLI or credential in the execution workspace. Account, current role trust, deployed resources, budget and cost remain `UNKNOWN`; an inaccessible service must never be described as empty.

The isolation gate remains open until EventPulse-scoped read-only identity and resource evidence is obtained. No other repository or AWS resource is part of this audit.

## Findings and disposition

| ID | Finding | Effect and next action |
| --- | --- | --- |
| EP-S1-F01 | Default branch contains only the OIDC workflow; substantial work is in draft PR #1. | Preserve draft; do not present its code as released main. Later review must decide its promotion. |
| EP-S1-F02 | No consumer runtime appears in the draft tree; Terraform only provisions topology. | Keep AWS processing as design-only. |
| EP-S1-F03 | Local checkpoint simulation does not persist sink and offset effects across services. | Bound the local claim; retain managed-recovery proof obligation. |
| EP-S1-F04 | Session bridge merging and deduplication TTL are not represented by the current processor. | Record semantic decision/implementation gap for subsequent work. |
| EP-S1-F05 | Draft evidence vocabulary (`AWS_LAB_VERIFIED`, `NOT_CLAIMED`) differs from the Part 1 plan vocabulary (`AWS_VERIFIED`, `UNCLAIMED`). | Reconcile through an explicit claim authority before future promotion. No rewriting in this audit. |
| EP-S1-F06 | Disposable dev install and local Terraform check were blocked by workspace tooling/network; exact-head GitHub jobs succeeded. | Preserve separate environment and CI evidence; do not report local pytest/Terraform success. |
| EP-S1-F07 | Fresh AWS identity/ownership, resource and cost inventory unavailable in this workspace. | **Stage 1 isolation blocker.** Obtain scoped read-only evidence, then update this receipt before completion. |

## Acceptance state

Source, draft-head tree, CI and claim boundaries were observed and recorded. The stage is **not complete** while AWS isolation evidence and audit PR exact-head/merged-main gates remain pending. A later completion receipt must name the actual reviewed head, merged main SHA/tree, required CI runs and evidence digest. No `AWS_VERIFIED`, workload, throughput or release claim follows from this audit.
