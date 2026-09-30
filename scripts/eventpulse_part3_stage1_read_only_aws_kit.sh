#!/usr/bin/env bash
set -u
export AWS_PAGER=""
export AWS_DEFAULT_REGION="ap-south-2"
umask 077

EXPECTED_ACCOUNT="887720497919"
REGION="ap-south-2"
ROLE="EventPulseGitHubOidcRole"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${PWD}/EventPulse-Part3-Stage1-${STAMP}"
mkdir -p "$OUT"

declare -A STATUS
STATUS_FILE="$OUT/.command-status.tsv"
run() {
  local name="$1"; shift
  "$@" >"$OUT/${name}.json" 2>"$OUT/${name}.stderr"
  STATUS["$name"]=$?
  printf '%s\t%s\n' "$name" "${STATUS[$name]}" >>"$STATUS_FILE"
}

run caller aws sts get-caller-identity --output json
run region aws account get-region-opt-status --region-name "$REGION" --output json
run providers aws iam list-open-id-connect-providers --output json
run provider aws iam get-open-id-connect-provider --open-id-connect-provider-arn "arn:aws:iam::${EXPECTED_ACCOUNT}:oidc-provider/token.actions.githubusercontent.com" --output json
run role aws iam get-role --role-name "$ROLE" --output json
run attached aws iam list-attached-role-policies --role-name "$ROLE" --output json
run inline aws iam list-role-policies --role-name "$ROLE" --output json
run role_tags aws iam list-role-tags --role-name "$ROLE" --output json
run tagged aws resourcegroupstaggingapi get-resources --region "$REGION" --tag-filters Key=Project,Values=EventPulse --output json
run logs aws logs describe-log-groups --region "$REGION" --log-group-name-prefix /aws/lambda/eventpulse --output json
run streams aws kinesis list-streams --region "$REGION" --limit 100 --output json
run functions aws lambda list-functions --region "$REGION" --max-items 100 --output json
run tables aws dynamodb list-tables --region "$REGION" --limit 100 --output json
run buckets aws s3api list-buckets --query 'Buckets[].Name' --output json
run queues aws sqs list-queues --region "$REGION" --queue-name-prefix eventpulse --max-results 100 --output json
run quota_kinesis aws service-quotas list-service-quotas --region "$REGION" --service-code kinesis --max-results 100 --output json
run quota_lambda aws service-quotas list-service-quotas --region "$REGION" --service-code lambda --max-results 100 --output json
run quota_dynamodb aws service-quotas list-service-quotas --region "$REGION" --service-code dynamodb --max-results 100 --output json
run alarms aws cloudwatch describe-alarms --region "$REGION" --alarm-name-prefix eventpulse --max-records 100 --output json
run budgets aws budgets describe-budgets --account-id "$EXPECTED_ACCOUNT" --max-results 100 --output json

python3 - "$OUT" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
rows = [line.split("\t") for line in (root / ".command-status.tsv").read_text().splitlines()]
(root / "command-status.json").write_text(json.dumps(dict(sorted((name, int(code)) for name, code in rows)), indent=2, sort_keys=True) + "\n")
(root / ".command-status.tsv").unlink()
PY

python3 - "$OUT" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
rows = []
for path in sorted(root.iterdir()):
    if path.name == "sha256-manifest.json" or not path.is_file():
        continue
    rows.append({"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size})
(root / "sha256-manifest.json").write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n")
PY

(cd "$(dirname "$OUT")" && zip -qr "${OUT}.zip" "$(basename "$OUT")")
sha256sum "${OUT}.zip"
printf 'Private read-only evidence bundle: %s.zip\n' "$OUT"
printf 'Upload only to the private conversation. Do not commit raw AWS output.\n'
