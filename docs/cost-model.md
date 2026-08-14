# Cost controls

- One provisioned Kinesis shard for a short lab window; no MSK, NAT gateway, or always-on cluster.
- DynamoDB on-demand capacity and small synthetic state.
- S3 lifecycle expiry for replay/evidence objects.
- CloudWatch retention limited to seven days.
- `run_id` and `ExpiresAt` tags on every supported resource.
- Terraform destroy is part of the evidence contract, not an optional cleanup step.

Before deployment, estimate region-specific prices with the AWS calculator. After deployment,
record Cost Explorer usage after billing data settles; do not infer cost from architecture alone.

