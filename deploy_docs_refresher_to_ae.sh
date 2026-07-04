#!/usr/bin/env bash
set -e

# Load environment variables from .env if present
if [ -f .env ]; then
  echo "Loading environment variables from .env..."
  export $(grep -v '^#' .env | xargs)
fi

PROJECT_ID="${GCP_PROJECT_ID}"
REGION="${GCP_REGION}"
AGENT_ENGINE_ID="${DOCS_REFRESHER_ENGINE_ID}"
DISPLAY_NAME="ADK GitHub Docs Refresher"
DESCRIPTION="Autonomous markdown documentation refresher triggered upon merged PRs"
TARGET_ENV="docs_refresher/.env"

# Ensure cleanup of copied .env file upon exit
cleanup() {
  if [ -f "${TARGET_ENV}" ]; then
    rm -f "${TARGET_ENV}"
  fi
}
trap cleanup EXIT

# Simply copy .env into the agent folder so load_dotenv() loads it inside Agent Engine
if [ -f .env ]; then
  echo "Copying .env to ${TARGET_ENV} for packaging..."
  cp .env "${TARGET_ENV}"
fi

echo "============================================================"
echo "  Deploying docs_refresher to GCP Vertex AI Agent Engine"
echo "============================================================"
echo "Project ID:      ${PROJECT_ID}"
echo "Region:          ${REGION}"
echo "Agent Engine ID: ${AGENT_ENGINE_ID}"
echo "Display Name:    ${DISPLAY_NAME}"
echo "============================================================"

uv run adk deploy agent_engine docs_refresher \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --display_name="${DISPLAY_NAME}" \
  --agent_engine_id="${AGENT_ENGINE_ID}" \
  --description="${DESCRIPTION}" \
  --otel_to_cloud

echo ""
echo "✅ Deployment update of docs_refresher (${AGENT_ENGINE_ID}) completed!"
