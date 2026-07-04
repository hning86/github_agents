# ADK Automated GitHub PR Reviewer & Docs Refresher

An intelligent, multi-agent AI system built on the **Google Agent Development Kit (ADK)** and **Gemini 3.5 Flash via Vertex AI**. This service integrates directly with remote GitHub MCP servers over Streamable HTTP to autonomously review Pull Requests and keep repository documentation synchronized.

---

## 🏗️ System Architecture & End-to-End Workflow

The system decouples event handling from heavy LLM agent execution by leveraging **GCP Cloud Run** for instantaneous webhook processing and **GCP Vertex AI Agent Engine** for autonomous reasoning and MCP tool execution.

```mermaid
flowchart TD
    GH["GitHub Webhook (PR Event)"] -->|POST /webhook/github| CR["Cloud Run (FastAPI Webhook Service)"]
    
    subgraph CR_Service ["GCP Cloud Run Runtime"]
        CR -->|"1. Verify HMAC Signature"| Auth["Signature Verification"]
        Auth -->|"2. Check Repo Allowlist"| Dispatch["Async Background Task Queue"]
    end

    subgraph AE ["GCP Vertex AI Agent Engine"]
        Dispatch -->|"3a. PR Opened / Updated (stream_query)"| PR_Agent["ADK GitHub PR Reviewer"]
        Dispatch -->|"3b. PR Merged (stream_query)"| Docs_Agent["ADK GitHub Docs Refresher"]
    end

    subgraph MCP ["Model Context Protocol over SSE"]
        PR_Agent <-->|"4. Remote Tool Calls"| MCP_Server["Remote GitHub MCP Server"]
        Docs_Agent <-->|"4. Remote Tool Calls"| MCP_Server
    end

    MCP_Server -->|"5a. Post Inline Reviews & Comments"| Source_Repo["Source Code Repository"]
    MCP_Server -->|"5b. Branch & Open PR with Updated Docs"| Docs_Repo["Target Documentation Repository"]
```

### Detailed Workflow Details
1. **Instantaneous Event Ingestion**: When a developer opens, updates, or merges a Pull Request on GitHub, GitHub posts an event payload (`pull_request`) to the webhook service hosted on **GCP Cloud Run**.
2. **Security & Validation**: The Cloud Run service verifies the request integrity using HMAC SHA-256 signatures (`GITHUB_WEBHOOK_SECRET`) and checks if the source repository is authorized (`ALLOWED_CODE_REPOS`).
3. **Asynchronous Dispatch**: To comply with GitHub's strict 10-second webhook timeout, Cloud Run immediately returns `202 Accepted` to GitHub and queues a non-blocking asyncio background task (`asyncio.to_thread`) to stream the prompt to the remote reasoning engine.
4. **Autonomous Reasoning on Agent Engine**:
   - **On PR Open / Push (`opened` / `synchronize`)**: Queries the deployed `ADK GitHub PR Reviewer` instance on Vertex AI Agent Engine. The agent connects to the remote GitHub MCP server (`api.githubcopilot.com/mcp/sse`), analyzes line diffs, and submits line-by-line inline review comments directly onto the Pull Request.
   - **On PR Merge (`closed` + `merged`)**: Queries the deployed `ADK GitHub Docs Refresher` instance on Vertex AI Agent Engine. The agent inspects the merged diffs, explores existing `.md` files in the target repository (`DOCS_TARGET_REPO`), creates a new branch, commits necessary documentation updates, and opens a documentation pull request.

---

## 🎬 End-to-End Demo Walkthrough

Below is the complete 15-step lifecycle of an autonomous code review and documentation refresh sequence:

### Phase 1: Automated Pull Request Review
1. **Developer Code Change**: A user makes code modifications in a feature branch (e.g., `dev`) of the source repository (`gcp-scratch`).
2. **Git Commit**: The user commits the changes locally or via IDE.
3. **PR Creation**: The user creates a Pull Request from `dev` to the `main` branch.
4. **PR Submission**: The user submits the Pull Request on GitHub.
5. **Webhook Dispatch**: GitHub fires an HTTP POST webhook event (`pull_request` action: `opened`) to the Cloud Run endpoint.
6. **Agent Engine Invocation**: Cloud Run verifies HMAC signatures and asynchronously invokes the deployed `ADK GitHub PR Reviewer` on Vertex AI Agent Engine.
7. **Retrieve PR Details**: The PR Reviewer agent queries the remote GitHub MCP server (`get_pull_request`, `get_pull_request_files`) over SSE to retrieve the file diffs and metadata.
8. **LLM Code Review**: The PR Reviewer passes the diffs to Gemini 3.5 Flash to evaluate code quality, detect potential bugs, and generate both high-level summary review comments and exact line-by-line code suggestions.
9. **Register Review Comments**: The PR Reviewer invokes GitHub MCP tools (`pull_request_review_write`, `add_comment_to_pending_review`) to post the review and inline comments directly onto the Pull Request in GitHub.

### Phase 2: Autonomous Documentation Synchronization
10. **PR Merge**: The developer addresses the review feedback and merges the Pull Request into `main`.
11. **Second Webhook Dispatch**: GitHub sends a second webhook event (`pull_request` action: `closed`, `merged: true`) to Cloud Run.
12. **Docs Refresher Invocation**: Cloud Run detects the merge event and asynchronously invokes the deployed `ADK GitHub Docs Refresher` on Vertex AI Agent Engine.
13. **Retrieve Current Docs & Diffs**: The Docs Refresher agent queries the remote GitHub MCP server to inspect the merged code changes and fetch existing markdown files from the target documentation repository (`gcp-scratch-docs`).
14. **LLM Documentation Generation**: The Docs Refresher calls Gemini 3.5 Flash to synthesize required documentation updates, reference guides, or new architecture summaries reflecting the merged changes.
15. **Open Docs PR**: The Docs Refresher invokes GitHub MCP server tools to create a new branch in `gcp-scratch-docs`, commit the updated markdown files, and submit a new documentation Pull Request for final human approval.

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

### 3. Live Webhook Server & Observability Dashboard
Start the local FastAPI server to process incoming GitHub webhooks and serve the built-in real-time web dashboard:
```bash
uv run python -m webhook_service.main
```
- **Live Web UI Dashboard**: Open `http://localhost:8080/` in any browser to watch real-time SSE streaming logs, active PR workflow cards, and remote GitHub MCP tool executions during demos.
- **Local GitHub Tunneling**: Expose local port `8080` instantly to GitHub via SSH tunneling:
  ```bash
  ssh -R 80:localhost:8080 nokey@localhost.run
  ```
  Copy the forwarding URL (`https://xxxx.localhost.run`) and paste it into your GitHub repository settings under **Settings** → **Webhooks** → **Add webhook** (Payload URL: `https://xxxx.localhost.run/webhook/github`).

---

## ☁️ Deployment to GCP (Vertex AI Agent Engine & Cloud Run)

### 1. Deploy Reasoning Engines to Vertex AI Agent Engine (with OpenTelemetry)
Deploy the autonomous agents to Vertex AI Agent Engine using the provided scripts:
```bash
# Deploy PR Reviewer (with OpenTelemetry enabled)
./deploy_pr_reviewer_to_ae.sh

# Deploy Docs Refresher (with OpenTelemetry enabled)
./deploy_docs_refresher_to_ae.sh
```
These scripts automatically pass `--otel_to_cloud` to enable native OpenTelemetry observability (exporting spans, traces, and metrics directly to GCP Cloud Trace and Cloud Logging) and inject `GOOGLE_API_USE_MTLS_ENDPOINT=never` into the container environment to ensure trace exporters authenticate reliably over standard OAuth2 REST endpoints without mTLS certificate verification failures.

After deploying, copy the returned `Agent Engine ID` values into your `.env` file as `PR_REVIEWER_ENGINE_ID` and `DOCS_REFRESHER_ENGINE_ID`.

### 2. Deploy Webhook Service to Cloud Run
Deploy the lightweight FastAPI event handler to Cloud Run using the automated deployment script:
```bash
./deploy_webhook_to_cr.sh
```
Once deployed, update your GitHub Webhook configuration with the assigned Cloud Run HTTPS URL (e.g., `https://github-webhook-service-xyz-uc.a.run.app/webhook/github`).
