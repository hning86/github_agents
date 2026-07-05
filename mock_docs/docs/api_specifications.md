# ADK GitHub Webhook & Agent API Specifications

This document formalizes the HTTP endpoints, webhook ingestion schemas, and Server-Sent Events (SSE) broadcasting protocols used across the `webhook_service` and live dashboard frontends.

---

## 1. HTTP API Endpoints (`webhook_service/main.py`)

| Method | Path | Response Type | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | `text/html` | Serves the standalone live streaming dashboard UI (`dashboard.html`). |
| `GET` | `/favicon.svg` | `image/svg+xml` | Serves the application favicon for browser tabs and bookmarks. |
| `GET` | `/health` | `application/json` | Health check endpoint required for Google Cloud Run container checks. |
| `GET` | `/api/stream` | `text/event-stream` | Server-Sent Events (SSE) stream delivering real-time agent telemetry. |
| `POST` | `/api/clear` | `application/json` | Clears the server-side ring buffer of historical broadcast events. |
| `POST` | `/webhook/github` | `application/json` | Ingests GitHub repository webhooks and triggers background agents. |

---

## 2. GitHub Webhook Ingestion (`POST /webhook/github`)

### 2.1 Headers Required
- `X-GitHub-Event`: Must be `pull_request`.
- `X-Hub-Signature-256`: HMAC SHA-256 signature calculated using `GITHUB_WEBHOOK_SECRET` (`sha256=<hex_digest>`).

### 2.2 Accepted Action Types
The webhook handler processes the following JSON payload `action` fields:
1. **`opened` / `synchronize`**: Triggers the **PR Reviewer Agent** (`PR_REVIEWER_ENGINE_ID`) to conduct automated code reviews.
2. **`closed` (`merged: true`)**: Triggers the **Docs Refresher Agent** (`DOCS_REFRESHER_ENGINE_ID`) to synchronize repository documentation across target docs branches.

---

## 3. Server-Sent Events (SSE) Protocol (`GET /api/stream`)

The `webhook_service` streams formatted JSON telemetry events over `/api/stream` to update connected browser clients in real time without polling.

### 3.1 SSE Message Format
Every message yielded over the SSE stream follows the standard structure:
```http
data: {"timestamp": "2026-07-04T20:35:12Z", "level": "INFO", "event_type": "TOOL_CALL", "source": "PR Reviewer", "message": "Invoking MCP tool get_pull_request_files for #14", "metadata": {"pr": 14, "repo": "owner/repo"}}

```

### 3.2 Event Types (`event_type`)
- **`WEBHOOK`**: Ingestion of a verified GitHub repository event payload.
- **`AGENT_START`**: Initiation of a remote Reasoning Engine invocation in `BackgroundTasks`.
- **`TOOL_CALL`**: Execution of a GitHub MCP or Vertex AI Reasoning tool.
- **`AGENT_DONE`**: Successful completion of a background agent review or docs refresh cycle.
- **`AGENT_FAIL` / `ERROR`**: Exception encountered during webhook verification or agent execution.
