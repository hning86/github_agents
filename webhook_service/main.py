import os
import json
import hmac
import hashlib
import asyncio
import logging
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env before starting service
load_dotenv()

import vertexai
from vertexai.preview import reasoning_engines
from google.cloud.aiplatform_v1beta1.types import reasoning_engine_execution_service as aip_types

from fastapi import FastAPI, Request, HTTPException, Header, BackgroundTasks

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
        logger.info(f"Connecting to remote engine '{display_name}' via {env_var_name}: {resource_name}")
        eng = reasoning_engines.ReasoningEngine(resource_name)
        _remote_engines_cache[display_name] = eng
        return eng
        
    # 2. Otherwise list reasoning engines in registry and match by display_name
    logger.info(f"Searching GCP Agent Registry ({project_id}/{region}) for '{display_name}'...")
    all_engines = reasoning_engines.ReasoningEngine.list()
    for summary_eng in all_engines:
        if summary_eng.display_name == display_name:
            eng = reasoning_engines.ReasoningEngine(summary_eng.resource_name)
            _remote_engines_cache[display_name] = eng
            logger.info(f"Found remote engine '{display_name}' at {eng.resource_name}")
            return eng
            
    logger.error(f"Reasoning engine '{display_name}' not found in GCP Agent Registry.")
    return None

def query_remote_agent(engine: reasoning_engines.ReasoningEngine, message: str, user_id: str = "github_webhook_service") -> str:
    """Helper to query an ADK agent on Agent Engine via stream_query."""
    logger.info(f"Querying remote Agent Engine ({engine.resource_name}) for user '{user_id}'...")
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
                        logger.info(f"⚙️ Remote Agent executing tool: {part['function_call'].get('name')}")
                    if "text" in part:
                        full_text.append(part["text"])
            except json.JSONDecodeError:
                pass
    return "".join(full_text)

async def run_agent_pr_review(repo_full_name: str, pr_number: int, pr_title: str):
    """Run the ADK agent autonomously in the background on Agent Engine to review and comment on the PR."""
    logger.info(f"🚀 Starting background Agent Engine review for {repo_full_name} PR #{pr_number}: '{pr_title}'")
    
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
            logger.error(f"❌ Could not find remote Agent Engine for ADK GitHub PR Reviewer")
            return
            
        user_id = f"github_webhook_service_{repo_full_name.replace('/', '_')}_{pr_number}"
        answer = await asyncio.to_thread(query_remote_agent, eng, prompt, user_id)
        logger.info(f"🤖 Agent Engine Response for PR #{pr_number}:\n{answer}")
        logger.info(f"✅ Successfully completed Agent Engine review for {repo_full_name} PR #{pr_number}")
    except Exception as e:
        logger.error(f"❌ Error during Agent Engine review of PR #{pr_number}: {e}", exc_info=True)


async def run_agent_docs_refresher(source_repo: str, pr_number: int, pr_title: str, target_docs_repo: str):
    """Run docs_refresher agent in background on Agent Engine to update documentation across all relevant files based on a merged PR."""
    logger.info(f"🚀 Starting background Agent Engine docs_refresher for merged PR #{pr_number} ('{pr_title}') -> Target Docs Repo: {target_docs_repo}")
    
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
            logger.error(f"❌ Could not find remote Agent Engine for ADK GitHub Docs Refresher")
            return
            
        user_id = f"github_webhook_service_docs_{source_repo.replace('/', '_')}_{pr_number}"
        answer = await asyncio.to_thread(query_remote_agent, eng, prompt, user_id)
        logger.info(f"🤖 Agent Engine Response for Docs Refresh PR #{pr_number}:\n{answer}")
        logger.info(f"✅ Successfully completed Agent Engine docs refresh for merged PR #{pr_number}")
    except Exception as e:
        logger.error(f"❌ Error during Agent Engine docs refresh for PR #{pr_number}: {e}", exc_info=True)


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
