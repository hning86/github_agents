# ADK Automated GitHub PR Reviewer & Docs Refresher

An intelligent, multi-agent AI system built on the **Google Agent Development Kit (ADK)** and **Gemini 3.5 Flash via Vertex AI**. This service integrates directly with remote GitHub MCP servers over Streamable HTTP to autonomously review Pull Requests and keep repository documentation synchronized.

---

## 🏗️ Architecture & Agents

The project is structured into modular components:

1. **`pr_reviewer` (Pull Request Review Agent)**
   - Conducts automated, constructive code reviews when Pull Requests are opened or updated.
   - Leverages GitHub MCP tools (`get_pull_request_files`, `pull_request_review_write`, `add_comment_to_pending_review`) to post overall review summaries as well as **specific inline line comments** on exact file diffs when warranted.
2. **`docs_refresher` (Documentation Synchronization Agent)**
   - Triggered automatically when a Pull Request is closed and merged.
   - Searches across target documentation repositories (configured via `DOCS_TARGET_REPO`) to discover any relevant markdown (`.md`) documentation affected by code changes.
   - Autonomously creates a new branch, updates or adds all necessary documentation files, and opens a summary Pull Request in the docs repository.
3. **`webhook_service` (FastAPI Cloud Run Service)**
   - Production-ready event receiver that listens for GitHub `pull_request` webhooks.
   - Enforces HMAC SHA-256 webhook signature verification (`GITHUB_WEBHOOK_SECRET`) and repository whitelisting (`ALLOWED_CODE_REPOS`).
   - Processes agent workflows asynchronously in background task queues so incoming webhook deliveries return `202 Accepted` immediately without timing out.

---

## ⚙️ Setup & Configuration

1. **Install Dependencies**:
   Ensure you have Python 3.13+ and [uv](https://docs.astral.sh/uv/) installed:
   ```bash
   uv sync
   ```

2. **Configure `.env`**:
   Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
   Open `.env` and provide your credentials and routing preferences:
   ```ini
   # Vertex AI Configuration
   GCP_PROJECT_ID=your-gcp-project-id
   GCP_REGION=us-central1
   GOOGLE_GENAI_USE_VERTEXAI=1

   # Remote GitHub MCP Authentication
   GITHUB_PERSONAL_ACCESS_TOKEN=github_pat_...
   GITHUB_MCP_SSE_URL=https://api.githubcopilot.com/mcp/sse

   # Webhook Security & Filtering
   GITHUB_WEBHOOK_SECRET=your_webhook_secret_passphrase
   ALLOWED_CODE_REPOS=owner/repo-name

   # Docs Refresher Target Repository
   DOCS_TARGET_REPO=owner/repo-docs
   ```

---

## 🚀 Usage Modes

### 1. Interactive Web UI (`adk web`)
Test and converse with either agent interactively through ADK's built-in web developer interface:
```bash
# Launch UI for pr_reviewer
uv run adk web pr_reviewer

# Launch UI for docs_refresher
uv run adk web docs_refresher
```

### 2. Command-Line Runner (`run_agent.py`)
Run ad-hoc queries from the terminal against `pr_reviewer`:
```bash
uv run run_agent.py "Show the last commit in owner/repo"
```

### 3. Live Webhook Server (Local Tunneling)
Start the local FastAPI server to process incoming GitHub webhooks:
```bash
uv run python -m webhook_service.main
```
Expose local port `8080` instantly to GitHub without any account signups via SSH tunneling:
```bash
ssh -R 80:localhost:8080 nokey@localhost.run
```
Copy the forwarding URL (`https://xxxx.localhost.run`) and paste it into your GitHub repository settings under **Settings** → **Webhooks** → **Add webhook** (Payload URL: `https://xxxx.localhost.run/webhook/github`).

---

## ☁️ Deployment to Google Cloud Run

Deploy the multi-agent service directly to Google Cloud Run as a scalable container:

```bash
gcloud run deploy github-pr-reviewer \
  --source . \
  --project your-gcp-project-id \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars="GCP_PROJECT_ID=your-gcp-project-id,GCP_REGION=us-central1,GOOGLE_GENAI_USE_VERTEXAI=1,GITHUB_WEBHOOK_SECRET=your_webhook_secret,ALLOWED_CODE_REPOS=owner/repo,DOCS_TARGET_REPO=owner/repo-docs" \
  --set-secrets="GITHUB_PERSONAL_ACCESS_TOKEN=GITHUB_PAT_SECRET:latest"
```
Once deployed, update your GitHub Webhook configuration with the assigned Cloud Run HTTPS URL (e.g., `https://github-pr-reviewer-xyz-uc.a.run.app/webhook/github`).
