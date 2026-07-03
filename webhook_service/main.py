import os
import hmac
import hashlib
import logging
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env before importing agent or starting service
load_dotenv()

from fastapi import FastAPI, Request, HTTPException, Header, BackgroundTasks
from google.adk.runners import InMemoryRunner
from google.genai import types
from pr_reviewer import root_agent as pr_reviewer_agent
from docs_refresher import root_agent as docs_refresher_agent






# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("webhook_service")

app = FastAPI(
    title="ADK GitHub PR Reviewer Webhook Service",
    description="Listens for GitHub pull_request webhooks and invokes the ADK GitHub Agent to conduct automated code reviews."
)

def verify_signature(payload: bytes, signature: Optional[str], secret: str) -> bool:
    """Verify HMAC SHA-256 webhook signature from GitHub."""
    if not secret:
        # If no secret is configured, bypass signature check (useful for local development)
        logger.warning("No GITHUB_WEBHOOK_SECRET set; skipping signature verification.")
        return True
        
    if not signature:
        return False
        
    mac = hmac.new(secret.encode("utf-8"), msg=payload, digestmod=hashlib.sha256)
    expected = "sha256=" + mac.hexdigest()
    return hmac.compare_digest(expected, signature)

async def run_agent_pr_review(repo_full_name: str, pr_number: int, pr_title: str):
    """Run the ADK agent autonomously in the background to review and comment on the PR."""
    logger.info(f"🚀 Starting background agent review for {repo_full_name} PR #{pr_number}: '{pr_title}'")
    runner = InMemoryRunner(agent=pr_reviewer_agent)
    runner.auto_create_session = True



    
    prompt = (
        f"A new Pull Request #{pr_number} ('{pr_title}') was just created in repository '{repo_full_name}'.\n"
        f"Please perform an automated code review on this PR:\n"
        f"1. Use your GitHub MCP tools (like 'get_pull_request' and 'get_pull_request_files') to inspect the Pull Request details and code changes.\n"
        f"2. Analyze the file diffs carefully. If you deem any specific lines of code require comments (such as potential bugs, code smell, edge cases, or improvements), generate specific line comments on those exact lines using your PR review workflow (create a pending review with 'pull_request_review_write', add inline line comments with 'add_comment_to_pending_review', and submit).\n"
        f"3. In addition to any inline line comments, create an overall summary review or comment directly on Pull Request #{pr_number}.\n"
        f"IMPORTANT: Make sure you actually execute the tool(s) to post your review and comments on the Pull Request before ending!"
    )

    user_message = types.Content(role="user", parts=[types.Part(text=prompt)])
    
    try:
        async for event in runner.run_async(
            user_id="github_webhook_service",
            session_id=f"pr_review_{repo_full_name.replace('/', '_')}_{pr_number}",
            new_message=user_message
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.function_call:
                        logger.info(f"⚙️ Agent executing tool: {part.function_call.name}")
        logger.info(f"✅ Successfully completed review for {repo_full_name} PR #{pr_number}")
    except Exception as e:
        logger.error(f"❌ Error during agent review of PR #{pr_number}: {e}", exc_info=True)


async def run_agent_docs_refresher(source_repo: str, pr_number: int, pr_title: str, target_docs_repo: str):
    """Run docs_refresher agent in background to update documentation across all relevant files based on a merged PR."""
    logger.info(f"🚀 Starting docs_refresher for merged PR #{pr_number} ('{pr_title}') -> Target Docs Repo: {target_docs_repo}")
    
    runner = InMemoryRunner(agent=docs_refresher_agent)
    runner.auto_create_session = True
    
    prompt = (
        f"Pull Request #{pr_number} ('{pr_title}') was just MERGED in repository '{source_repo}'.\n"
        f"Please synchronize all relevant documentation in target repository '{target_docs_repo}':\n"
        f"1. Inspect the merged Pull Request #{pr_number} in '{source_repo}' using your GitHub MCP tools to see what changed across the codebase.\n"
        f"2. Inspect existing markdown documentation (.md files) in '{target_docs_repo}' to locate ANY and ALL documentation relevant to the changes.\n"
        f"3. If any documentation updates or new documentation sections are needed to exhaustively reflect the merged changes across one or more files, create a single branch in '{target_docs_repo}', update/create all relevant .md files, and open a Pull Request in '{target_docs_repo}'.\n"
        f"If no updates are needed across any documentation files, summarize your findings."
    )
    
    user_message = types.Content(role="user", parts=[types.Part(text=prompt)])
    
    try:
        async for event in runner.run_async(
            user_id="github_webhook_service",
            session_id=f"docs_refresh_{source_repo.replace('/', '_')}_{pr_number}",
            new_message=user_message
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.function_call:
                        logger.info(f"⚙️ Docs Refresher executing tool: {part.function_call.name}")
        logger.info(f"✅ Successfully completed docs refresh for merged PR #{pr_number}")
    except Exception as e:
        logger.error(f"❌ Error during docs refresh for PR #{pr_number}: {e}", exc_info=True)


@app.get("/")
@app.get("/health")
async def health_check():
    """Health check endpoint required for Google Cloud Run deployment."""
    return {"status": "healthy", "service": "ADK GitHub PR Reviewer & Docs Refresher Webhook"}


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
        logger.error("Received webhook with invalid HMAC signature.")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    
    payload = await request.json()
    
    # 2. Filter for pull_request events
    if x_github_event == "pull_request":
        action = payload.get("action")
        repo_name = payload.get("repository", {}).get("full_name", "")
        logger.info(f"Received pull_request webhook action '{action}' for repo '{repo_name}'")
        
        # Check against ALLOWED_CODE_REPOS if configured
        allowed_repos_env = os.getenv("ALLOWED_CODE_REPOS", "").strip()
        if allowed_repos_env:
            allowed_repos = [r.strip().lower() for r in allowed_repos_env.split(",") if r.strip()]
            if repo_name.lower() not in allowed_repos:
                logger.info(f"Ignoring pull_request from repo '{repo_name}' (not listed in ALLOWED_CODE_REPOS).")
                return {"status": "ignored", "reason": f"Repository '{repo_name}' is not in ALLOWED_CODE_REPOS"}
        
        # Trigger review on new PRs or updated PR pushes
        if action in ["opened", "synchronize"]:
            pr_num = payload["pull_request"]["number"]
            pr_title = payload["pull_request"]["title"]
            
            # Queue background task so we return 202 Accepted within GitHub's 10s timeout
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
            
            logger.info(f"PR #{pr_num} merged in {repo_name}. Queuing docs_refresher for {target_docs_repo}...")
            background_tasks.add_task(run_agent_docs_refresher, repo_name, pr_num, pr_title, target_docs_repo)
            return {
                "status": "accepted",
                "message": f"Docs refresh queued for {target_docs_repo} based on merged PR #{pr_num}"
            }
        else:
            return {"status": "ignored", "reason": f"Action '{action}' (merged={payload.get('pull_request', {}).get('merged')}) does not trigger action"}

            
    # Also handle ping events when connecting webhook in GitHub UI

    elif x_github_event == "ping":
        logger.info("Received GitHub webhook ping event.")
        return {"status": "pong", "zen": payload.get("zen")}
        
    return {"status": "ignored", "reason": f"Event '{x_github_event}' ignored"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
