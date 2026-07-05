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

PROJECT_ID="${GCP_PROJECT_ID}"
REGION="${GCP_REGION}"
AGENT_ENGINE_ID="${PR_REVIEWER_ENGINE_ID}"
DISPLAY_NAME="ADK GitHub PR Reviewer"
DESCRIPTION="Autonomous GitHub Pull Request code reviewer powered by Gemini 2.5 Pro and MCP"
TARGET_ENV="pr_reviewer/.env"

# Ensure cleanup of copied .env file upon exit
cleanup() {
  if [ -f "${TARGET_ENV}" ]; then
    rm -f "${TARGET_ENV}"
  fi
}
trap cleanup EXIT

# Copy .env into the agent folder and ensure mTLS bypass is set for OTel
if [ -f .env ]; then
  echo "Copying .env to ${TARGET_ENV} for packaging..."
  cp .env "${TARGET_ENV}"
fi
echo "GOOGLE_API_USE_MTLS_ENDPOINT=never" >> "${TARGET_ENV}"

echo "============================================================"
echo "  Deploying pr_reviewer to GCP Vertex AI Agent Engine"
echo "============================================================"
echo "Project ID:      ${PROJECT_ID}"
echo "Region:          ${REGION}"
echo "Agent Engine ID: ${AGENT_ENGINE_ID}"
echo "Display Name:    ${DISPLAY_NAME}"
echo "============================================================"

uv run adk deploy agent_engine pr_reviewer \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --display_name="${DISPLAY_NAME}" \
  --agent_engine_id="${AGENT_ENGINE_ID}" \
  --description="${DESCRIPTION}" \
  --otel_to_cloud

echo ""
echo "✅ Deployment update of pr_reviewer (${AGENT_ENGINE_ID}) completed!"
