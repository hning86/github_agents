import os
import logging
from functools import cached_property
from typing import AsyncGenerator
from dotenv import load_dotenv

from google.adk.models import Gemini
from google.adk.models.llm_response import LlmResponse
from google.adk.agents.llm_agent import Agent
from google.adk.tools import McpToolset
from google.adk.tools.mcp_tool import StreamableHTTPConnectionParams
from google.genai import Client

# Load environment variables from .env
load_dotenv()

# Configure logger
logger = logging.getLogger("pr_reviewer")



# Build Connection Parameters for the remote GitHub MCP Server via Streamable HTTP
token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
mcp_url = os.getenv("GITHUB_MCP_SSE_URL")

if not token:
    logger.warning("WARNING: GITHUB_PERSONAL_ACCESS_TOKEN is not set in the environment! "
                   "The agent may not be able to authenticate with the remote GitHub MCP server.")

headers = {
    "Authorization": f"Bearer {token}",
}

logger.info(f"[GitHub Agent] Configuring connection to remote GitHub MCP server at: {mcp_url}")
connection_params = StreamableHTTPConnectionParams(
    url=mcp_url,
    headers=headers,
    timeout=30.0,
)

# Instantiate the McpToolset pointing to the remote SSE GitHub MCP server
mcp_toolset = McpToolset(
    connection_params=connection_params,
)

# Define the GitHub Helper Agent
pr_reviewer = Agent(
    model="gemini-3.5-flash",
    name="pr_reviewer",
    description="Agent with access to the remote GitHub-hosted MCP tools to review Pull Requests.",
    instruction="""You are an expert GitHub assistant. 
You specialize in managing, query, and interacting with the user's GitHub repositories, issues, pull requests, files, and users.
You MUST utilize your GitHub MCP tools whenever the user asks to fetch, update, list, create, or modify repositories or related objects. Do not guess or hallucinate any data.
If the GITHUB_PERSONAL_ACCESS_TOKEN is missing, invalid, or expired, kindly and professionally request the user to update the PAT in their .env file.

When conducting automated Pull Request code reviews:
1. Inspect the PR diffs and changed files thoroughly.
2. If you identify specific lines of code that require comments (such as potential bugs, code improvements, or security risks), generate inline comments for those specific lines using the GitHub PR review workflow:
   - First, create a pending review using 'pull_request_review_write' with method 'create'.
   - Next, add specific comments to lines of changed files using 'add_comment_to_pending_review' (providing path, line number or position, and body).
   - Finally, submit the review along with your overall summary using 'pull_request_review_write' with method 'submit_pending'.
3. If no specific line comments are deemed necessary, submit a general overall review or comment directly on the Pull Request.
Be clear, accurate, and concise in your explanations and status updates.""",
    tools=[mcp_toolset],
)


# Export root_agent for ADK Web discovery
root_agent = pr_reviewer


