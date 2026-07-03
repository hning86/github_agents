# ADK GitHub Agent with Vertex AI & Remote MCP

A packaged Google ADK (Antigravity SDK) Agent that connects to the remote GitHub-hosted MCP server via SSE, powered by Gemini through the Vertex AI API.

## Features
- **Separation of Concerns**: The agent logic is encapsulated inside its own modular package (`github_agent`), completely decoupled from the runner script (`run_agent.py`).
- **Vertex AI Powered**: Uses a custom `VertexGemini` subclass to natively access Gemini models via the Vertex AI API (under `GOOGLE_GENAI_USE_VERTEXAI=1`).
- **Remote GitHub MCP**: Strictly connects to the remote GitHub MCP server using Server-Sent Events (SSE), utilizing standard Bearer authentication.

## Setup & Configuration

1. **Install Dependencies**:
   Initialize your virtual environment and synchronize dependencies:
   ```bash
   uv sync
   ```

2. **Configure Environment Variables**:
   Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
   Open `.env` and fill in the values:
   - `GCP_PROJECT_ID`: Your Google Cloud Project ID.
   - `GCP_REGION`: Your GCP Region (e.g. `us-central1`).
   - `GITHUB_PERSONAL_ACCESS_TOKEN`: Your GitHub Personal Access Token (PAT) with appropriate scopes (e.g., `repo`, `read:user`).
   - `GITHUB_MCP_SSE_URL` *(Optional)*: Override the remote GitHub MCP Server SSE endpoint if needed (defaults to `https://api.githubcopilot.com/mcp/sse`).

## How to Run

Execute the runner script using `uv run`, specifying your instruction/question as a command-line argument:

```bash
uv run run_agent.py "List my GitHub repositories"
```
```bash
uv run run_agent.py "What is the description of my repository 'voice-harmonizer'?"
```
