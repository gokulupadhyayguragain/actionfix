#!/usr/bin/env bash
set -euo pipefail

# One-command ActionFix deployment. CloudFormation owns the app resources;
# SAM's resolved S3 bucket stores packaged artifacts, not stack state.
ROOT_DIR="$(dirname "$(dirname "$(realpath "$0")")")"
STACK_NAME="${STACK_NAME:-actionfix}"
AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
ALLOWED_ORIGIN="${ALLOWED_ORIGIN:-*}"
BUDGET_NOTIFICATION_EMAIL="${BUDGET_NOTIFICATION_EMAIL:-}"
BUILD_DIR="${ROOT_DIR}/.aws-sam/build"
KIRO_API_KEY_VALUE="${KIRO_API_KEY:-${KIRO_API:-}}"

# Read only the expected key assignment; do not execute the .env file.
if [[ -z "${KIRO_API_KEY_VALUE}" && -f "${ROOT_DIR}/.env" ]]; then
  KIRO_API_KEY_VALUE="$(awk -F= '/^(KIRO_API_KEY|KIRO_API)=/ { sub(/^[^=]*=/, ""); print; exit }' "${ROOT_DIR}/.env")"
fi
if [[ -z "${KIRO_API_KEY_VALUE}" ]]; then
  echo "Set KIRO_API_KEY (or KIRO_API) in the environment or ${ROOT_DIR}/.env." >&2
  exit 2
fi

if [[ -z "${AWS_REGION}" ]]; then
  echo "Set AWS_REGION (for example: AWS_REGION=us-east-1)." >&2
  exit 2
fi
command -v aws >/dev/null || { echo "AWS CLI is required." >&2; exit 2; }
command -v sam >/dev/null || { echo "AWS SAM CLI is required." >&2; exit 2; }

printf 'Checking AWS identity in %s…\n' "$AWS_REGION"
ACCOUNT_ID="$(aws sts get-caller-identity --region "$AWS_REGION" --query Account --output text)"
ARTIFACT_BUCKET="${ARTIFACT_BUCKET:-actionfix-sam-artifacts-${ACCOUNT_ID}-${AWS_REGION}}"
aws sts get-caller-identity --region "$AWS_REGION" >/dev/null

if ! aws s3api head-bucket --bucket "$ARTIFACT_BUCKET" --region "$AWS_REGION" >/dev/null 2>&1; then
  printf 'Creating SAM artifact bucket %s…\n' "$ARTIFACT_BUCKET"
  if [[ "$AWS_REGION" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "$ARTIFACT_BUCKET" --region "$AWS_REGION" >/dev/null
  else
    aws s3api create-bucket \
      --bucket "$ARTIFACT_BUCKET" \
      --region "$AWS_REGION" \
      --create-bucket-configuration "LocationConstraint=${AWS_REGION}" \
      >/dev/null
  fi
  aws s3api put-bucket-tagging \
    --bucket "$ARTIFACT_BUCKET" \
    --region "$AWS_REGION" \
    --tagging 'TagSet=[{Key=Project,Value=ActionFix},{Key=Purpose,Value=SamArtifacts}]'
fi

printf 'Building the Lambda package…\n'
sam build \
  --use-container \
  --template-file "${ROOT_DIR}/infra/template.yaml" \
  --build-dir "$BUILD_DIR" \
  --region "$AWS_REGION"

printf 'Deploying CloudFormation stack %s…\n' "$STACK_NAME"
DEPLOY_PARAMETERS=(
  "KiroApiKey=${KIRO_API_KEY_VALUE}"
  "KiroAgentEngine=${KIRO_AGENT_ENGINE:-v2}"
  "KiroEffort=${KIRO_EFFORT:-low}"
  "AllowedOrigin=${ALLOWED_ORIGIN}"
)
if [[ -n "${BUDGET_NOTIFICATION_EMAIL}" ]]; then
  DEPLOY_PARAMETERS+=("BudgetNotificationEmail=${BUDGET_NOTIFICATION_EMAIL}")
fi
sam deploy \
  --template-file "${BUILD_DIR}/template.yaml" \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION" \
  --s3-bucket "$ARTIFACT_BUCKET" \
  --resolve-image-repos \
  --capabilities CAPABILITY_IAM \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset \
  --parameter-overrides "${DEPLOY_PARAMETERS[@]}"

stack_output() {
  local key="$1"
  aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --query "Stacks[0].Outputs[?OutputKey==\`${key}\`].OutputValue" \
    --output text
}

SITE_BUCKET="$(stack_output SiteBucketName)"
DISTRIBUTION_ID="$(stack_output CloudFrontDistributionId)"
SITE_URL="$(stack_output SiteUrl)"

printf 'Uploading the static frontend to %s…\n' "$SITE_BUCKET"
aws s3 sync "${ROOT_DIR}/frontend" "s3://${SITE_BUCKET}/" \
  --delete \
  --region "$AWS_REGION" \
  --cache-control "public,max-age=300"

printf 'Invalidating CloudFront cache…\n'
aws cloudfront create-invalidation \
  --distribution-id "$DISTRIBUTION_ID" \
  --paths '/*' \
  >/dev/null

printf '\nActionFix deployed.\nURL: %s\nStack: %s\nRegion: %s\n\n' "$SITE_URL" "$STACK_NAME" "$AWS_REGION"
