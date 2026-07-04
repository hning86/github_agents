#!/usr/bin/env bash
set -e

# Resolve repository root directory (one level up from script directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# Load environment variables from .env if present
if [ -f .env ]; then
  echo "Loading environment variables from .env..."
  export $(grep -v '^#' .env | xargs)
fi

PROJECT_ID="${GCP_PROJECT_ID:-ninghai-ccai}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="github-webhook-service"

echo "============================================================"
echo "  Deploying Webhook Service to Google Cloud Run"
echo "============================================================"
echo "Project ID:               ${PROJECT_ID}"
echo "Region:                   ${REGION}"
echo "Service Name:             ${SERVICE_NAME}"
echo "PR Reviewer Engine ID:    ${PR_REVIEWER_ENGINE_ID}"
echo "Docs Refresher Engine ID: ${DOCS_REFRESHER_ENGINE_ID}"
echo "============================================================"

# Ensure cleanup of copied Dockerfile upon exit
cleanup() {
  if [ -f "Dockerfile" ]; then
    rm -f "Dockerfile"
  fi
}
trap cleanup EXIT

echo "Copying webhook_service/Dockerfile to ./Dockerfile for Cloud Run build..."
cp webhook_service/Dockerfile ./Dockerfile

# Construct comma-separated environment variables for Cloud Run
ENV_VARS="GCP_PROJECT_ID=${PROJECT_ID},GCP_REGION=${REGION}"

if [ -n "${PR_REVIEWER_ENGINE_ID}" ]; then
  ENV_VARS="${ENV_VARS},PR_REVIEWER_ENGINE_ID=${PR_REVIEWER_ENGINE_ID}"
fi
if [ -n "${DOCS_REFRESHER_ENGINE_ID}" ]; then
  ENV_VARS="${ENV_VARS},DOCS_REFRESHER_ENGINE_ID=${DOCS_REFRESHER_ENGINE_ID}"
fi
if [ -n "${ALLOWED_CODE_REPOS}" ]; then
  ENV_VARS="${ENV_VARS},ALLOWED_CODE_REPOS=${ALLOWED_CODE_REPOS}"
fi
if [ -n "${DOCS_TARGET_REPO}" ]; then
  ENV_VARS="${ENV_VARS},DOCS_TARGET_REPO=${DOCS_TARGET_REPO}"
fi
if [ -n "${GITHUB_WEBHOOK_SECRET}" ]; then
  ENV_VARS="${ENV_VARS},GITHUB_WEBHOOK_SECRET=${GITHUB_WEBHOOK_SECRET}"
fi

echo "Deploying ${SERVICE_NAME} to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --allow-unauthenticated \
  --set-env-vars="${ENV_VARS}"

echo ""
echo "✅ Cloud Run deployment of ${SERVICE_NAME} completed successfully!"
