#!/usr/bin/env bash
# Validate and deploy cloudformation.yaml, then (optionally) upload a document to test it.
#   bash infra/deploy.sh                          # validate + deploy
#   bash infra/deploy.sh samples/legal_doc.txt    # ...then upload this file and wait for its summary
set -euo pipefail
cd "$(dirname "$0")/.."

# Course credentials (access key, secret, session token) live in .env, never in code.
if [ -f .env ]; then set -a; . ./.env; set +a; fi
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
STACK_NAME="${STACK_NAME:-objection-inspection}"

aws sts get-caller-identity --query Account --output text >/dev/null

echo "== Validating cloudformation.yaml"
aws cloudformation validate-template --template-body file://cloudformation.yaml --query Description --output text

echo "== Deploying stack $STACK_NAME"
aws cloudformation deploy \
  --template-file cloudformation.yaml \
  --stack-name "$STACK_NAME" \
  --capabilities CAPABILITY_NAMED_IAM \
  --no-fail-on-empty-changeset

aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table

DOC="${1:-}"
[ -z "$DOC" ] && exit 0

output() {
  aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}
IN_BUCKET=$(output InputBucketName)
OUT_BUCKET=$(output OutputBucketName)
NAME=$(basename "$DOC")
SUMMARY_KEY="summaries/${NAME%.*}-summary.txt"

echo "== Uploading $DOC to s3://$IN_BUCKET/$NAME"
aws s3 cp "$DOC" "s3://$IN_BUCKET/$NAME"

echo "== Waiting for s3://$OUT_BUCKET/$SUMMARY_KEY"
aws s3api wait object-exists --bucket "$OUT_BUCKET" --key "$SUMMARY_KEY"
aws s3 cp "s3://$OUT_BUCKET/$SUMMARY_KEY" -
