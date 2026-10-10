#!/usr/bin/env bash
set -euo pipefail

# Empty the CloudFormation-owned site bucket first; that makes stack deletion
# a single command even after frontend files have been uploaded.
STACK_NAME="${STACK_NAME:-actionfix}"
AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"

if [[ -z "${AWS_REGION}" ]]; then
  echo "Set AWS_REGION (for example: AWS_REGION=us-east-1)." >&2
  exit 2
fi
command -v aws >/dev/null || { echo "AWS CLI is required." >&2; exit 2; }
ACCOUNT_ID="$(aws sts get-caller-identity --region "$AWS_REGION" --query Account --output text)"
ARTIFACT_BUCKET="${ARTIFACT_BUCKET:-actionfix-sam-artifacts-${ACCOUNT_ID}-${AWS_REGION}}"

if ! aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" >/dev/null 2>&1; then
  echo "CloudFormation stack ${STACK_NAME} does not exist in ${AWS_REGION}."
  exit 0
fi

SITE_BUCKET="$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION" \
  --query 'Stacks[0].Outputs[?OutputKey==`SiteBucketName`].OutputValue' \
  --output text)"

if [[ -n "$SITE_BUCKET" && "$SITE_BUCKET" != "None" ]]; then
  printf 'Emptying site bucket %s…\n' "$SITE_BUCKET"
  aws s3 rm "s3://${SITE_BUCKET}/" --recursive --region "$AWS_REGION"
fi

FUNCTION_NAME="$(aws cloudformation describe-stack-resources \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION" \
  --logical-resource-id ActionFixFunction \
  --query 'StackResources[0].PhysicalResourceId' \
  --output text)"
IMAGE_URI="$(aws lambda get-function \
  --function-name "$FUNCTION_NAME" \
  --region "$AWS_REGION" \
  --query 'Code.ImageUri' \
  --output text || true)"
ECR_REPOSITORY=""
if [[ -n "$IMAGE_URI" && "$IMAGE_URI" != "None" ]]; then
  ECR_REPOSITORY="${IMAGE_URI#*/}"
  ECR_REPOSITORY="${ECR_REPOSITORY%%:*}"
fi

printf 'Deleting CloudFormation stack %s…\n' "$STACK_NAME"
aws cloudformation delete-stack --stack-name "$STACK_NAME" --region "$AWS_REGION"
aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" --region "$AWS_REGION"

if [[ -n "$ECR_REPOSITORY" ]]; then
  printf 'Deleting SAM image repository %s…\n' "$ECR_REPOSITORY"
  aws ecr delete-repository --repository-name "$ECR_REPOSITORY" --force --region "$AWS_REGION"
fi

if aws s3api head-bucket --bucket "$ARTIFACT_BUCKET" --region "$AWS_REGION" >/dev/null 2>&1; then
  printf 'Deleting SAM artifact bucket %s…\n' "$ARTIFACT_BUCKET"
  aws s3 rm "s3://${ARTIFACT_BUCKET}/" --recursive --region "$AWS_REGION"
  aws s3api delete-bucket --bucket "$ARTIFACT_BUCKET" --region "$AWS_REGION"
fi
printf 'Stack %s and its dedicated artifact bucket were deleted.\n' "$STACK_NAME"
