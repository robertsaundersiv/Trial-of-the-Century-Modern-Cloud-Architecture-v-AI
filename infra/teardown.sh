#!/usr/bin/env bash
# Empty both buckets (CloudFormation cannot delete a non-empty bucket), then delete the stack.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then set -a; . ./.env; set +a; fi
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
STACK_NAME="${STACK_NAME:-objection-inspection}"

for key in InputBucketName OutputBucketName; do
  bucket=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='$key'].OutputValue" --output text 2>/dev/null || true)
  if [ -n "$bucket" ] && [ "$bucket" != "None" ]; then
    echo "== Emptying s3://$bucket"
    aws s3 rm "s3://$bucket" --recursive
  fi
done

echo "== Deleting stack $STACK_NAME"
aws cloudformation delete-stack --stack-name "$STACK_NAME"
aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"
echo "Stack $STACK_NAME deleted."
