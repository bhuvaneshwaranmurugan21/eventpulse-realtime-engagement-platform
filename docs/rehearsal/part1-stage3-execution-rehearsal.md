# EventPulse Stage 3 execution and resumption rehearsal

## Local command order

Run from an isolated checkout of the recorded source with a disposable Python 3.12 environment and no undeclared package:

1. `python scripts/build_stage3_manifest.py --check`
2. `python scripts/validate_stage3_completion.py --verify-source`
3. `python -m unittest discover -s tests -p 'test_stage3_*.py' -v`
4. `python scripts/build_stage2_manifest.py --check`
5. `python scripts/validate_stage2_contract.py --verify-source`
6. `python -m unittest discover -s tests -p 'test_stage2_contract.py' -v`
7. `python scripts/validate_stage1_audit.py --verify-source`
8. `git diff --check`

Generation is explicit: `python scripts/build_stage3_manifest.py` writes the deterministic oracle result and artifact manifest. Generation is followed by check mode; CI only uses check mode.

## Stop, invalidation and resume rules

| Interruption | Stop condition | Invalidated evidence | Exact resume point |
| --- | --- | --- | --- |
| Remote main changes before branching | SHA/tree differs from entry authority | Entry receipt and ancestry | Inspect new delta, record a refreshed entry decision, rerun all predecessor gates |
| Contract or fixture changes | Corpus digest changes | Oracle result, manifest, tests and reviews derived from old cases | Recalculate expectation from authority, regenerate, rerun focused and cumulative gates |
| Dependency resolution changes | Environment differs from recorded standard-library-only boundary | Clean-environment reproducibility | Resolve declaration first, recreate environments, rerun everything |
| Local/CI divergence | Same head produces different result | Exact-head acceptance | Compare Python version, commands, checkout and bytes; repair root cause and rerun exact head |
| PR head or base moves | Reviewed identity no longer matches | Review and CI acceptance | Re-read changed files, rerun affected and cumulative gates, then re-pin expected head |
| Read-only AWS admission denied later | Required fact is unknown | Any admission-dependent forecast or plan | Retain `UNKNOWN`, obtain minimum read capability, rerun admission only |
| Account or region mismatch later | Identity differs from authority | Plan and all managed evidence | Stop before plan/apply; correct identity and requalify |
| Terraform plan is stale or destructive later | Source/variables/provider/account drift or unexpected deletion | Plan approval | Recreate and independently review a new saved plan |
| Forecast exceeds admission ceiling | Forecast is above USD 8 or hard cap is not USD 12 | Workload authorization | Reduce bounded scope or obtain a reviewed exception; never apply first |
| Canary or workload gate fails later | Wiring, semantic or threshold failure | Downstream managed claims | Preserve failure, repair narrow root cause, rerun canary and all invalidated workloads |
| Teardown is denied or residue remains | Absence cannot be independently proven | Teardown and final-cost claims | Restore least-privilege read/delete ability and resume from inventory verification |

## Merge rehearsal

The authority PR and later completion-receipt PR each use the same sequence: verify changed-file allow-list; run focused, adversarial and cumulative checks; publish draft; wait for exact-head jobs; inspect job steps; recheck head/base/files; merge with the expected head SHA; then verify merged-main SHA/tree and push CI. The repository currently has no protection rules, so the expected-head merge guard is mandatory.

No AWS transcript is synthesized. No later command is represented as having run merely because its stop and resume path is documented here.

## Authority-run environment and results

The execution harness fixes `TZ=UTC`, `LC_ALL=C.UTF-8`, `PYTHONHASHSEED=0`, and `PYTHONDONTWRITEBYTECODE=1`. The authoring environment used Python 3.12.14 and Git 2.51.1. The evaluator has no third-party runtime dependency; clean reproductions use `python -m venv --without-pip`.

The pristine authority pass produced 50 passing oracle cases, 31 passing Stage 3 tests, 12 passing Stage 2 tests, a successful Stage 3 fail-closed validator, a successful Stage 2 cumulative validator, and a successful Stage 1 audit validator. The canonical corpus SHA-256 is `3275a62ca3b7e90be6a6988d2d7f9a321db7ef53a767a8fdb8a3f01ea8de8461`. Final clean-environment result and manifest hashes are added to the completion receipt after the immutable authority commit is reproduced.
