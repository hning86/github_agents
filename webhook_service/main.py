import os
import json
import hmac
import hashlib
import asyncio
import logging
import datetime
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env before starting service
load_dotenv()

import vertexai
from vertexai.preview import reasoning_engines
from google.cloud.aiplatform_v1beta1.types import reasoning_engine_execution_service as aip_types

from fastapi import FastAPI, Request, HTTPException, Header, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("webhook_service")

app = FastAPI(
    title="ADK GitHub PR Reviewer Webhook Service",
    description="Listens for GitHub pull_request webhooks and invokes the ADK GitHub Agent on GCP Agent Engine to conduct automated code reviews."
)

# Event Broadcaster for Live Web UI Dashboard
_event_listeners = set()
_event_history = []
_MAX_HISTORY = 150

def broadcast_event(level: str, event_type: str, agent: str, message: str, pr_info: Optional[dict] = None):
    """Broadcast real-time log event to all connected SSE web clients and save to ring buffer."""
    evt = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "level": level,
        "event_type": event_type,
        "agent": agent,
        "message": message,
        "pr_info": pr_info or {}
    }
    _event_history.append(evt)
    if len(_event_history) > _MAX_HISTORY:
        _event_history.pop(0)
    
    # Log to standard Python logger as well
    log_msg = f"[{agent}] {message}"
    if level == "ERROR":
        logger.error(log_msg)
    elif level == "WARNING":
        logger.warning(log_msg)
    else:
        logger.info(log_msg)

    # Send to active subscribers
    for queue in list(_event_listeners):
        try:
            queue.put_nowait(evt)
        except asyncio.QueueFull:
            pass

def verify_signature(payload: bytes, signature: Optional[str], secret: str) -> bool:
    """Verify HMAC SHA-256 webhook signature from GitHub."""
    if not secret:
        broadcast_event("WARNING", "SECURITY", "Webhook Service", "No GITHUB_WEBHOOK_SECRET set; skipping signature verification.")
        return True
        
    if not signature:
        return False
        
    mac = hmac.new(secret.encode("utf-8"), msg=payload, digestmod=hashlib.sha256)
    expected = "sha256=" + mac.hexdigest()
    return hmac.compare_digest(expected, signature)

# Cache for remote reasoning engines
_remote_engines_cache = {}

def get_remote_engine(display_name: str, env_var_name: Optional[str] = None) -> Optional[reasoning_engines.ReasoningEngine]:
    """Discover and return a ReasoningEngine instance by display_name or env var ID, caching the result."""
    if display_name in _remote_engines_cache:
        return _remote_engines_cache[display_name]
        
    project_id = os.getenv("GCP_PROJECT_ID", "ninghai-ccai")
    region = os.getenv("GCP_REGION", "us-central1")
    vertexai.init(project=project_id, location=region)
    
    # 1. Check if explicit engine ID/name is provided via env var (e.g. PR_REVIEWER_ENGINE_ID)
    if env_var_name and os.getenv(env_var_name):
        eng_id = os.getenv(env_var_name).strip()
        resource_name = eng_id if "projects/" in eng_id else f"projects/{project_id}/locations/{region}/reasoningEngines/{eng_id}"
        broadcast_event("INFO", "ENGINE_CONNECT", "Vertex AI", f"Connecting to remote engine '{display_name}' via {env_var_name}: {resource_name}")
        eng = reasoning_engines.ReasoningEngine(resource_name)
        _remote_engines_cache[display_name] = eng
        return eng
        
    # 2. Otherwise list reasoning engines in registry and match by display_name
    broadcast_event("INFO", "ENGINE_CONNECT", "Vertex AI", f"Searching GCP Agent Registry ({project_id}/{region}) for '{display_name}'...")
    all_engines = reasoning_engines.ReasoningEngine.list()
    for summary_eng in all_engines:
        if summary_eng.display_name == display_name:
            eng = reasoning_engines.ReasoningEngine(summary_eng.resource_name)
            _remote_engines_cache[display_name] = eng
            broadcast_event("INFO", "ENGINE_CONNECT", "Vertex AI", f"Found remote engine '{display_name}' at {eng.resource_name}")
            return eng
            
    broadcast_event("ERROR", "ENGINE_CONNECT", "Vertex AI", f"Reasoning engine '{display_name}' not found in GCP Agent Registry.")
    return None

def query_remote_agent(engine: reasoning_engines.ReasoningEngine, message: str, user_id: str, agent_name: str, pr_info: dict) -> str:
    """Helper to query an ADK agent on Agent Engine via stream_query."""
    broadcast_event("INFO", "QUERY_START", agent_name, f"Streaming prompt to GCP Agent Engine ({engine.resource_name})...", pr_info)
    resp = engine.execution_api_client.stream_query_reasoning_engine(
        request=aip_types.StreamQueryReasoningEngineRequest(
            name=engine.resource_name,
            input={"message": message, "user_id": user_id},
            class_method="async_stream_query"
        )
    )
    
    full_text = []
    for chunk in resp:
        if hasattr(chunk, "data") and chunk.data:
            try:
                data = json.loads(chunk.data)
                parts = data.get("content", {}).get("parts", [])
                for part in parts:
                    if "function_call" in part:
                        fn_name = part['function_call'].get('name')
                        fn_args = part['function_call'].get('args', {})
                        broadcast_event("INFO", "TOOL_CALL", agent_name, f"⚙️ Executing GitHub MCP Tool: {fn_name}", {**pr_info, "tool": fn_name, "args": fn_args})
                    if "text" in part and part["text"].strip():
                        full_text.append(part["text"])
                        # Broadcast reasoning chunk summary if concise
                        txt_snippet = part["text"].strip()
                        if len(txt_snippet) > 120:
                            txt_snippet = txt_snippet[:117] + "..."
                        broadcast_event("INFO", "AGENT_REASONING", agent_name, f"💬 Reasoning chunk: {txt_snippet}", pr_info)
            except json.JSONDecodeError:
                pass
    return "".join(full_text)

async def run_agent_pr_review(repo_full_name: str, pr_number: int, pr_title: str):
    """Run the ADK agent autonomously in the background on Agent Engine to review and comment on the PR."""
    pr_info = {"repo": repo_full_name, "pr": pr_number, "title": pr_title, "type": "PR Review"}
    broadcast_event("INFO", "AGENT_START", "PR Reviewer", f"🚀 Starting background Agent Engine code review for {repo_full_name} PR #{pr_number}: '{pr_title}'", pr_info)
    
    prompt = (
        f"A new Pull Request #{pr_number} ('{pr_title}') was just created in repository '{repo_full_name}'.\n"
        f"Please perform an automated code review on this PR:\n"
        f"1. Use your GitHub MCP tools (like 'get_pull_request' and 'get_pull_request_files') to inspect the Pull Request details and code changes.\n"
        f"2. Analyze the file diffs carefully. If you deem any specific lines of code require comments (such as potential bugs, code smell, edge cases, or improvements), generate specific line comments on those exact lines using your PR review workflow (create a pending review with 'pull_request_review_write', add inline line comments with 'add_comment_to_pending_review', and submit).\n"
        f"3. In addition to any inline line comments, create an overall summary review or comment directly on Pull Request #{pr_number}.\n"
        f"IMPORTANT: Make sure you actually execute the tool(s) to post your review and comments on the Pull Request before ending!"
    )

    try:
        eng = await asyncio.to_thread(get_remote_engine, "ADK GitHub PR Reviewer", "PR_REVIEWER_ENGINE_ID")
        if not eng:
            broadcast_event("ERROR", "AGENT_ERROR", "PR Reviewer", f"❌ Could not find remote Agent Engine for ADK GitHub PR Reviewer", pr_info)
            return
            
        user_id = f"github_webhook_service_{repo_full_name.replace('/', '_')}_{pr_number}"
        answer = await asyncio.to_thread(query_remote_agent, eng, prompt, user_id, "PR Reviewer", pr_info)
        broadcast_event("SUCCESS", "AGENT_COMPLETE", "PR Reviewer", f"✅ Successfully finished PR review for {repo_full_name} #{pr_number}", {**pr_info, "response": answer})
    except Exception as e:
        broadcast_event("ERROR", "AGENT_ERROR", "PR Reviewer", f"❌ Error during Agent Engine review of PR #{pr_number}: {e}", pr_info)
        logger.error(f"Error during PR review #{pr_number}: {e}", exc_info=True)


async def run_agent_docs_refresher(source_repo: str, pr_number: int, pr_title: str, target_docs_repo: str):
    """Run docs_refresher agent in background on Agent Engine to update documentation across all relevant files based on a merged PR."""
    pr_info = {"repo": source_repo, "pr": pr_number, "title": pr_title, "target_docs": target_docs_repo, "type": "Docs Refresh"}
    broadcast_event("INFO", "AGENT_START", "Docs Refresher", f"🚀 Starting background docs refresher for merged PR #{pr_number} ('{pr_title}') -> Target Docs Repo: {target_docs_repo}", pr_info)
    
    prompt = (
        f"Pull Request #{pr_number} ('{pr_title}') was just MERGED in repository '{source_repo}'.\n"
        f"Please synchronize all relevant documentation in target repository '{target_docs_repo}':\n"
        f"1. Inspect the merged Pull Request #{pr_number} in '{source_repo}' using your GitHub MCP tools to see what changed across the codebase.\n"
        f"2. Inspect existing markdown documentation (.md files) in '{target_docs_repo}' to locate ANY and ALL documentation relevant to the changes.\n"
        f"3. If any documentation updates or new documentation sections are needed to exhaustively reflect the merged changes across one or more files, create a single branch in '{target_docs_repo}', update/create all relevant .md files, and open a Pull Request in '{target_docs_repo}'.\n"
        f"If no updates are needed across any documentation files, summarize your findings."
    )
    
    try:
        eng = await asyncio.to_thread(get_remote_engine, "ADK GitHub Docs Refresher", "DOCS_REFRESHER_ENGINE_ID")
        if not eng:
            broadcast_event("ERROR", "AGENT_ERROR", "Docs Refresher", f"❌ Could not find remote Agent Engine for ADK GitHub Docs Refresher", pr_info)
            return
            
        user_id = f"github_webhook_service_docs_{source_repo.replace('/', '_')}_{pr_number}"
        answer = await asyncio.to_thread(query_remote_agent, eng, prompt, user_id, "Docs Refresher", pr_info)
        broadcast_event("SUCCESS", "AGENT_COMPLETE", "Docs Refresher", f"✅ Successfully finished docs refresh for merged PR #{pr_number}", {**pr_info, "response": answer})
    except Exception as e:
        broadcast_event("ERROR", "AGENT_ERROR", "Docs Refresher", f"❌ Error during Agent Engine docs refresh for PR #{pr_number}: {e}", pr_info)
        logger.error(f"Error during docs refresh #{pr_number}: {e}", exc_info=True)


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ADK Autonomous Agent Live Dashboard</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #080c14;
            --bg-secondary: #0e1626;
            --bg-card: rgba(18, 28, 48, 0.65);
            --border-color: rgba(255, 255, 255, 0.08);
            --accent-blue: #3b82f6;
            --accent-purple: #8b5cf6;
            --accent-cyan: #06b6d4;
            --accent-green: #10b981;
            --accent-amber: #f59e0b;
            --accent-pink: #ec4899;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background-color: var(--bg-primary);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            overflow-x: hidden;
            background-image: 
                radial-gradient(at 0% 0%, rgba(59, 130, 246, 0.12) 0px, transparent 50%),
                radial-gradient(at 100% 100%, rgba(139, 92, 246, 0.12) 0px, transparent 50%);
        }

        /* Top Navigation Header */
        .navbar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1rem 2rem;
            background: rgba(14, 22, 38, 0.8);
            backdrop-filter: blur(16px);
            border-bottom: 1px solid var(--border-color);
            position: sticky;
            top: 0;
            z-index: 50;
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .logo-icon {
            width: 36px;
            height: 36px;
            border-radius: 10px;
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 1.1rem;
            color: #fff;
            box-shadow: 0 0 15px rgba(59, 130, 246, 0.4);
        }

        .brand-title {
            font-size: 1.25rem;
            font-weight: 600;
            background: linear-gradient(to right, #fff, #94a3b8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .connection-status {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.4rem 0.9rem;
            border-radius: 9999px;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--border-color);
            font-size: 0.85rem;
            font-weight: 500;
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: var(--accent-green);
            box-shadow: 0 0 10px var(--accent-green);
            animation: pulse 2s infinite;
        }

        @keyframes pulse {
            0% { transform: scale(0.95); opacity: 0.8; }
            50% { transform: scale(1.15); opacity: 1; }
            100% { transform: scale(0.95); opacity: 0.8; }
        }

        /* Main Dashboard Grid */
        .dashboard-grid {
            display: grid;
            grid-template-columns: 1fr 1.6fr;
            gap: 1.5rem;
            padding: 1.5rem 2rem;
            flex: 1;
            max-height: calc(100vh - 70px);
        }

        @media (max-width: 1024px) {
            .dashboard-grid {
                grid-template-columns: 1fr;
                max-height: none;
            }
        }

        /* Pane Layout */
        .pane {
            background: var(--bg-card);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
        }

        .pane-header {
            padding: 1.25rem 1.5rem;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: rgba(255, 255, 255, 0.02);
        }

        .pane-title {
            font-size: 1.05rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        /* Activity Cards Section */
        .activity-feed {
            padding: 1.25rem;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 1rem;
            flex: 1;
        }

        .activity-card {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.25rem;
            transition: all 0.25s ease;
            animation: fadeIn 0.4s ease forwards;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .activity-card:hover {
            border-color: rgba(59, 130, 246, 0.4);
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(0, 0, 0, 0.4);
        }

        .card-top {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 0.75rem;
        }

        .badge {
            padding: 0.25rem 0.65rem;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .badge-pr { background: rgba(59, 130, 246, 0.15); color: var(--accent-blue); border: 1px solid rgba(59, 130, 246, 0.3); }
        .badge-docs { background: rgba(139, 92, 246, 0.15); color: var(--accent-purple); border: 1px solid rgba(139, 92, 246, 0.3); }
        .badge-webhook { background: rgba(245, 158, 11, 0.15); color: var(--accent-amber); border: 1px solid rgba(245, 158, 11, 0.3); }

        .card-title {
            font-size: 0.95rem;
            font-weight: 600;
            color: #fff;
            margin-bottom: 0.35rem;
            line-height: 1.4;
        }

        .card-meta {
            font-size: 0.8rem;
            color: var(--text-muted);
            display: flex;
            gap: 1rem;
        }

        .tool-chip {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.2rem 0.55rem;
            border-radius: 4px;
            background: rgba(6, 182, 212, 0.1);
            color: var(--accent-cyan);
            border: 1px solid rgba(6, 182, 212, 0.25);
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.75rem;
            margin-top: 0.75rem;
            margin-right: 0.4rem;
        }

        /* Live Terminal Log Section */
        .terminal-controls {
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
        }

        .filter-btn {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
            color: var(--text-muted);
            padding: 0.3rem 0.7rem;
            border-radius: 6px;
            font-size: 0.75rem;
            cursor: pointer;
            transition: all 0.2s;
        }

        .filter-btn.active, .filter-btn:hover {
            background: rgba(59, 130, 246, 0.2);
            color: #fff;
            border-color: var(--accent-blue);
        }

        .terminal-console {
            background: rgba(5, 8, 15, 0.85);
            padding: 1.25rem;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.82rem;
            line-height: 1.6;
            overflow-y: auto;
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 0.4rem;
        }

        .log-entry {
            display: flex;
            gap: 0.75rem;
            padding: 0.35rem 0.6rem;
            border-radius: 6px;
            border-left: 3px solid transparent;
            transition: background 0.15s;
        }

        .log-entry:hover {
            background: rgba(255, 255, 255, 0.02);
        }

        .log-timestamp {
            color: #64748b;
            flex-shrink: 0;
        }

        .log-agent {
            font-weight: 600;
            flex-shrink: 0;
            width: 125px;
        }

        .agent-webhook { color: var(--accent-amber); }
        .agent-pr { color: var(--accent-blue); }
        .agent-docs { color: var(--accent-purple); }
        .agent-vertex { color: var(--accent-cyan); }

        .log-msg {
            color: var(--text-main);
            word-break: break-word;
        }

        .log-entry.INFO { border-left-color: rgba(255, 255, 255, 0.2); }
        .log-entry.TOOL_CALL { border-left-color: var(--accent-cyan); background: rgba(6, 182, 212, 0.05); }
        .log-entry.SUCCESS { border-left-color: var(--accent-green); background: rgba(16, 185, 129, 0.05); }
        .log-entry.ERROR { border-left-color: #ef4444; background: rgba(239, 68, 68, 0.08); color: #fca5a5; }

        /* Scrollbar Styling */
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.15); border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(255, 255, 255, 0.3); }

        .empty-state {
            text-align: center;
            padding: 3rem 1rem;
            color: var(--text-muted);
            font-size: 0.9rem;
        }
    </style>
</head>
<body>
    <header class="navbar">
        <div class="brand">
            <div class="logo-icon">AI</div>
            <span class="brand-title">ADK Multi-Agent Execution Dashboard</span>
        </div>
        <div class="connection-status">
            <div class="status-dot" id="statusDot"></div>
            <span id="statusText">Connected to Cloud Run SSE Stream</span>
        </div>
    </header>

    <main class="dashboard-grid">
        <!-- Left Pane: Activity & PR Cards -->
        <section class="pane">
            <div class="pane-header">
                <div class="pane-title">🚀 Active Agent Workflows</div>
                <span class="badge badge-pr" id="workflowCount">0 Executions</span>
            </div>
            <div class="activity-feed" id="activityFeed">
                <div class="empty-state" id="emptyActivity">Waiting for GitHub pull_request webhooks...</div>
            </div>
        </section>

        <!-- Right Pane: Live Console Stream -->
        <section class="pane">
            <div class="pane-header">
                <div class="pane-title">⚡ Live Vertex AI Agent Engine Console</div>
                <div class="terminal-controls">
                    <button class="filter-btn active" onclick="filterLogs('ALL', this)">ALL</button>
                    <button class="filter-btn" onclick="filterLogs('PR Reviewer', this)">PR REVIEWER</button>
                    <button class="filter-btn" onclick="filterLogs('Docs Refresher', this)">DOCS REFRESHER</button>
                    <button class="filter-btn" onclick="filterLogs('TOOL_CALL', this)">TOOLS</button>
                    <button class="filter-btn" onclick="clearConsole()">CLEAR</button>
                </div>
            </div>
            <div class="terminal-console" id="consoleFeed">
                <div class="log-entry INFO">
                    <span class="log-timestamp">SYSTEM</span>
                    <span class="log-agent agent-vertex">Dashboard</span>
                    <span class="log-msg">Subscribing to real-time event stream from Cloud Run...</span>
                </div>
            </div>
        </section>
    </main>

    <script>
        const activityFeed = document.getElementById('activityFeed');
        const emptyActivity = document.getElementById('emptyActivity');
        const consoleFeed = document.getElementById('consoleFeed');
        const statusDot = document.getElementById('statusDot');
        const statusText = document.getElementById('statusText');
        const workflowCount = document.getElementById('workflowCount');

        let activeFilter = 'ALL';
        const workflows = new Map();

        // Connect Server-Sent Events
        const evtSource = new EventSource('/api/stream');

        evtSource.onopen = () => {
            statusDot.style.backgroundColor = '#10b981';
            statusDot.style.boxShadow = '0 0 10px #10b981';
            statusText.textContent = 'Connected to Cloud Run SSE Stream';
        };

        evtSource.onerror = () => {
            statusDot.style.backgroundColor = '#ef4444';
            statusDot.style.boxShadow = '0 0 10px #ef4444';
            statusText.textContent = 'Reconnecting to Event Stream...';
        };

        evtSource.onmessage = (e) => {
            if (e.data === 'heartbeat') return;
            try {
                const evt = JSON.parse(e.data);
                renderLogEntry(evt);
                updateWorkflows(evt);
            } catch (err) {
                console.error("Error parsing event:", err);
            }
        };

        function renderLogEntry(evt) {
            const entry = document.createElement('div');
            entry.className = `log-entry ${evt.event_type === 'TOOL_CALL' ? 'TOOL_CALL' : evt.level}`;
            entry.dataset.agent = evt.agent;
            entry.dataset.type = evt.event_type;

            if (activeFilter !== 'ALL') {
                if (activeFilter === 'TOOL_CALL' && evt.event_type !== 'TOOL_CALL') entry.style.display = 'none';
                else if (activeFilter !== 'TOOL_CALL' && evt.agent !== activeFilter) entry.style.display = 'none';
            }

            const timeStr = evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString() : 'NOW';
            let agentClass = 'agent-webhook';
            if (evt.agent === 'PR Reviewer') agentClass = 'agent-pr';
            else if (evt.agent === 'Docs Refresher') agentClass = 'agent-docs';
            else if (evt.agent === 'Vertex AI') agentClass = 'agent-vertex';

            entry.innerHTML = `
                <span class="log-timestamp">[${timeStr}]</span>
                <span class="log-agent ${agentClass}">${evt.agent}</span>
                <span class="log-msg">${evt.message}</span>
            `;

            consoleFeed.appendChild(entry);
            consoleFeed.scrollTop = consoleFeed.scrollHeight;
        }

        function updateWorkflows(evt) {
            if (!evt.pr_info || (!evt.pr_info.pr && !evt.pr_info.repo)) return;
            const prKey = `${evt.pr_info.repo}#${evt.pr_info.pr}`;
            
            if (emptyActivity) emptyActivity.style.display = 'none';

            let card = document.getElementById(`wf-${prKey}`);
            if (!card) {
                card = document.createElement('div');
                card.id = `wf-${prKey}`;
                card.className = 'activity-card';
                
                const badgeType = evt.pr_info.type === 'Docs Refresh' ? 'badge-docs' : 'badge-pr';
                
                card.innerHTML = `
                    <div class="card-top">
                        <span class="badge ${badgeType}">${evt.pr_info.type || evt.agent}</span>
                        <span class="badge" id="status-${prKey}" style="background:rgba(255,255,255,0.05)">IN PROGRESS</span>
                    </div>
                    <div class="card-title">${evt.pr_info.title || `Pull Request #${evt.pr_info.pr}`}</div>
                    <div class="card-meta">
                        <span>📦 ${evt.pr_info.repo}</span>
                        <span>PR #${evt.pr_info.pr}</span>
                    </div>
                    <div id="tools-${prKey}" style="display:flex; flex-wrap:wrap;"></div>
                `;
                activityFeed.prepend(card);
                workflows.set(prKey, true);
                workflowCount.textContent = `${workflows.size} Executions`;
            }

            // Add tool badge if tool call
            if (evt.event_type === 'TOOL_CALL' && evt.pr_info.tool) {
                const toolsContainer = document.getElementById(`tools-${prKey}`);
                const chip = document.createElement('span');
                chip.className = 'tool-chip';
                chip.innerHTML = `⚡ ${evt.pr_info.tool}`;
                toolsContainer.appendChild(chip);
            }

            // Update status on completion
            if (evt.level === 'SUCCESS') {
                const statusBadge = document.getElementById(`status-${prKey}`);
                if (statusBadge) {
                    statusBadge.style.background = 'rgba(16, 185, 129, 0.2)';
                    statusBadge.style.color = '#10b981';
                    statusBadge.textContent = 'COMPLETE';
                }
            } else if (evt.level === 'ERROR') {
                const statusBadge = document.getElementById(`status-${prKey}`);
                if (statusBadge) {
                    statusBadge.style.background = 'rgba(239, 68, 68, 0.2)';
                    statusBadge.style.color = '#ef4444';
                    statusBadge.textContent = 'ERROR';
                }
            }
        }

        function filterLogs(filter, btn) {
            activeFilter = filter;
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            document.querySelectorAll('.log-entry').forEach(entry => {
                if (filter === 'ALL') entry.style.display = 'flex';
                else if (filter === 'TOOL_CALL') entry.style.display = entry.dataset.type === 'TOOL_CALL' ? 'flex' : 'none';
                else entry.style.display = entry.dataset.agent === filter ? 'flex' : 'none';
            });
        }

        function clearConsole() {
            consoleFeed.innerHTML = '';
        }
    </script>
</body>
</html>
"""

@app.get("/api/stream")
async def stream_events(request: Request):
    """Server-Sent Events (SSE) stream for real-time dashboard updates."""
    async def event_generator():
        # Send existing history first
        for evt in _event_history:
            yield f"data: {json.dumps(evt)}\n\n"
        
        # Create queue for live stream
        queue = asyncio.Queue(maxsize=200)
        _event_listeners.add(queue)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(evt)}\n\n"
                except asyncio.TimeoutError:
                    # Send heartbeat ping to keep connection alive
                    yield f": heartbeat\n\n"
        finally:
            _event_listeners.discard(queue)
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/health")
async def health_check():
    """Health check endpoint required for Google Cloud Run deployment."""
    return {"status": "healthy", "service": "ADK GitHub PR Reviewer & Docs Refresher Webhook"}

@app.get("/", response_class=HTMLResponse)
async def web_ui():
    """Serve the stunning live streaming dashboard."""
    return HTMLResponse(content=DASHBOARD_HTML)

@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: Optional[str] = Header(None),
    x_hub_signature_256: Optional[str] = Header(None),
):
    """Endpoint receiving webhook deliveries from GitHub."""
    body = await request.body()
    webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET", "").strip()
    
    # 1. Verify GitHub HMAC signature
    if not verify_signature(body, x_hub_signature_256, webhook_secret):
        broadcast_event("ERROR", "SECURITY", "Webhook Service", "Received webhook with invalid HMAC signature.")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    
    payload = await request.json()
    
    # 2. Filter for pull_request events
    if x_github_event == "pull_request":
        action = payload.get("action")
        repo_name = payload.get("repository", {}).get("full_name", "")
        broadcast_event("INFO", "WEBHOOK", "Webhook Service", f"Received pull_request webhook action '{action}' for repo '{repo_name}'", {"repo": repo_name, "action": action})
        
        # Check against ALLOWED_CODE_REPOS if configured
        allowed_repos_env = os.getenv("ALLOWED_CODE_REPOS", "").strip()
        if allowed_repos_env:
            allowed_repos = [r.strip().lower() for r in allowed_repos_env.split(",") if r.strip()]
            if repo_name.lower() not in allowed_repos:
                broadcast_event("WARNING", "WEBHOOK", "Webhook Service", f"Ignoring pull_request from repo '{repo_name}' (not listed in ALLOWED_CODE_REPOS).")
                return {"status": "ignored", "reason": f"Repository '{repo_name}' is not in ALLOWED_CODE_REPOS"}
        
        # Trigger review on new PRs or updated PR pushes
        if action in ["opened", "synchronize"]:
            pr_num = payload["pull_request"]["number"]
            pr_title = payload["pull_request"]["title"]
            
            broadcast_event("INFO", "WEBHOOK", "Webhook Service", f"Queuing background PR review task for {repo_name} #{pr_num}", {"repo": repo_name, "pr": pr_num, "title": pr_title, "type": "PR Review"})
            background_tasks.add_task(run_agent_pr_review, repo_name, pr_num, pr_title)
            return {
                "status": "accepted", 
                "message": f"PR review queued for {repo_name} #{pr_num}"
            }
        # Trigger docs_refresher when a PR is closed and merged
        elif action == "closed" and payload.get("pull_request", {}).get("merged") is True:
            pr_num = payload["pull_request"]["number"]
            pr_title = payload["pull_request"]["title"]
            target_docs_repo = (os.getenv("DOCS_TARGET_REPO") or f"{repo_name}-docs").strip()
            
            broadcast_event("INFO", "WEBHOOK", "Webhook Service", f"PR #{pr_num} merged in {repo_name}. Queuing docs_refresher for {target_docs_repo}...", {"repo": repo_name, "pr": pr_num, "title": pr_title, "target_docs": target_docs_repo, "type": "Docs Refresh"})
            background_tasks.add_task(run_agent_docs_refresher, repo_name, pr_num, pr_title, target_docs_repo)
            return {
                "status": "accepted",
                "message": f"Docs refresh queued for {target_docs_repo} based on merged PR #{pr_num}"
            }
        else:
            return {"status": "ignored", "reason": f"Action '{action}' (merged={payload.get('pull_request', {}).get('merged')}) does not trigger action"}
            
    elif x_github_event == "ping":
        broadcast_event("INFO", "WEBHOOK", "Webhook Service", "Received GitHub webhook ping event.")
        return {"status": "pong", "zen": payload.get("zen")}
        
    return {"status": "ignored", "reason": f"Event '{x_github_event}' ignored"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
