# EventPulse Part 3 Stage 1 known limits

- This stage observes and adjudicates admission. It does not mutate IAM, initialize a Terraform backend, acquire a lease, create resources, plan, deploy or run a workload.
- Resource inventories are bounded by the recorded AWS APIs and cannot prove that an unrelated, untagged resource is safe to reuse. Ambiguity is a collision and therefore a `NO_GO`.
- Service-quota listings establish readable configured quota values, not current utilization or a capacity guarantee.
- The cost envelope is `DESIGN_ONLY` until dated authoritative prices and budget visibility are captured. Free-tier assumptions never satisfy admission.
- An admission decision expires after 24 hours or immediately after source, account, region, trust, policy, resource, quota, backend, budget or lease drift.
- Completion of this stage means the admission authority and evidence are complete. Only an `ADMITTED` decision permits Stage 2 planning; `NO_GO` and `INDETERMINATE` preserve the stop.
