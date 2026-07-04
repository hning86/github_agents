import os
import hmac
import hashlib
import asyncio
import logging
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env before starting service
load_dotenv()

from fastapi import FastAPI, Request, HTTPException, Header, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse

from .broadcaster import broadcast_event, sse_event_generator
from .engine_client import get_remote_engine, query_remote_agent

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

UI_DIR = Path(__file__).parent / "ui"
DASHBOARD_HTML_PATH = UI_DIR / "dashboard.html"

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


@app.get("/api/stream")
async def stream_events(request: Request):
    """Server-Sent Events (SSE) stream for real-time dashboard updates."""
    return StreamingResponse(sse_event_generator(request.is_disconnected), media_type="text/event-stream")

@app.get("/health")
async def health_check():
    """Health check endpoint required for Google Cloud Run deployment."""
    return {"status": "healthy", "service": "ADK GitHub PR Reviewer & Docs Refresher Webhook"}

@app.get("/", response_class=HTMLResponse)
async def web_ui():
    """Serve the standalone live streaming dashboard HTML."""
    html_content = DASHBOARD_HTML_PATH.read_text(encoding="utf-8")
    return HTMLResponse(content=html_content)

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
    uvicorn.run("webhook_service.main:app", host="0.0.0.0", port=port)
