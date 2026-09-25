# EventPulse security, cost and lifecycle authority

**Status:** `DESIGN_ONLY`. This document authorizes no IAM or AWS mutation.

## IAM boundaries

| Principal | Required actions | Resource boundary |
| --- | --- | --- |
| Lambda consumer | `kinesis:DescribeStreamSummary`, `kinesis:GetRecords`, `kinesis:GetShardIterator`, `kinesis:ListShards` | Exact EventPulse stream ARN |
| Lambda consumer | `s3:PutObject`, `s3:GetObject`, `s3:HeadObject` | Exact raw and failure prefixes |
| Lambda consumer | `dynamodb:GetItem`, `dynamodb:Query`, `dynamodb:TransactWriteItems` | Exact EventPulse state table ARN |
| Lambda consumer | `sqs:SendMessage` | Exact EventPulse quarantine queue ARN |
| Lambda consumer | `cloudwatch:PutMetricData` | `EventPulse/Lab` namespace with condition where supported |
| Lambda logging | `logs:CreateLogStream`, `logs:PutLogEvents` | Exact EventPulse log group ARN |
| Evidence reader | list/describe/get metric and sanitized evidence reads | Exact EventPulse resources and prefixes |
| Deployment role | Reviewed create/update/delete actions only for the saved plan | Exact EventPulse naming/tag boundary; defined later before Part 3 |

The Stage 1 OIDC role currently has no workload policies. A future policy change requires a separate reviewed correction, snapshot, rollback and requalification.

## Data protection

Use service-managed encryption for the bounded lab unless admission selects a reviewed customer key. Block all public S3 access. Require TLS. Store no customer data; workloads use deterministic synthetic pseudonymous users. Raw payloads, account IDs and ARNs stay out of public evidence. CloudWatch retention, raw retention and quarantine retention are seven days.

## Cost admission

- Hard cap: USD 12 for the complete EventPulse bounded AWS lab.
- Forecast admission ceiling: USD 8, leaving USD 4 for retries, delayed cleanup and billing uncertainty.
- A dated region-specific calculator or price manifest is mandatory before creation.
- Forecast includes Kinesis shard-hours and PUT payload units, Lambda requests/duration, DynamoDB transactions/storage, S3 requests/storage, SQS requests, CloudWatch ingestion/storage/metrics and retry/replay allowance.
- Stop before deployment when any coefficient is unknown, forecast exceeds USD 8, the hard cap is absent, or another EventPulse lease is active.
- During execution, stop workload publication at USD 9 forecast-consumed or any unexpected always-on/NAT resource.

No cost is observed or claimed by Stage 2.

## Ownership and lifetime

Every resource carries `Project=EventPulse`, `Environment=lab`, `RunId=<immutable-run-id>`, `ExpiresAt=<UTC>`, `Owner=<reviewed-owner>` and `SourceSha=<40-char-sha>` where supported. The lease expires no later than four hours after creation. Raw/quarantine/log retention is seven days, while infrastructure teardown occurs in the same controlled session after evidence preservation.

The teardown inventory covers stream, event source mapping, Lambda function/version, IAM policy attachments created for the run, S3 buckets/objects, DynamoDB table/backups, SQS queue, log group, alarms and temporary packages. Success requires independent list/describe absence checks. `AccessDenied` and a successful delete request are not absence proof. Delayed billing is recorded separately.
