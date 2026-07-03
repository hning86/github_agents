import os
import logging
from dotenv import load_dotenv

from google.adk.agents.llm_agent import Agent
from google.adk.tools import McpToolset
from google.adk.tools.mcp_tool import StreamableHTTPConnectionParams

# Load environment variables from .env
load_dotenv()

# Configure logger
logger = logging.getLogger("docs_refresher")

# Build Connection Parameters for the remote GitHub MCP Server via Streamable HTTP
token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
mcp_url = os.getenv("GITHUB_MCP_SSE_URL")

if not token:
    logger.warning("WARNING: GITHUB_PERSONAL_ACCESS_TOKEN is not set in the environment! "
                   "The agent may not be able to authenticate with the remote GitHub MCP server.")

headers = {
    "Authorization": f"Bearer {token}",
}

logger.info(f"[Docs Refresher] Configuring connection to remote GitHub MCP server at: {mcp_url}")
connection_params = StreamableHTTPConnectionParams(
    url=mcp_url,
    headers=headers,
    timeout=30.0,
)

# Instantiate the McpToolset pointing to the remote SSE GitHub MCP server
mcp_toolset = McpToolset(
    connection_params=connection_params,
)

# Define the Docs Refresher Agent
docs_refresher = Agent(
    model="gemini-3.5-flash",
    name="docs_refresher",
    description="Agent that updates all relevant markdown documentation (.md files) in a target repository based on merged Pull Requests.",
    instruction="""You are an expert technical documentation assistant specializing in keeping all relevant markdown documentation (.md files) synchronized across repositories when code changes occur.

When triggered by a merged Pull Request:
1. Inspect the merged Pull Request in the source repository using your GitHub MCP tools (such as 'get_pull_request', 'get_pull_request_files', or diff tools) to understand what features, APIs, configurations, or behaviors changed across the codebase.
2. Search and inspect existing documentation (.md files) across the target documentation repository (specified in the prompt or DOCS_TARGET_REPO) using search tools or 'get_file_contents' to discover ANY docs that are relevant to the merged code changes.
3. Evaluate whether any existing documentation files need to be modified, or if new documentation sections/files should be added so that the repository's documentation remains fully accurate and exhaustive.
4. If documentation updates are warranted across one or more relevant files:
   - Create a single new branch in the target documentation repository (e.g., 'docs/update-for-pr-<number>').
   - Modify or create ANY and ALL relevant .md files in that branch using your file modification tools (e.g., 'create_or_update_file').
   - Open a new Pull Request in the target documentation repository describing all documentation changes across all touched files and linking back to the original merged code PR.
5. If no documentation updates are needed, clearly explain why.
Be thorough, exhaustive, and ensure high editorial quality in all documentation updates across all affected files.""",
    tools=[mcp_toolset],
)

# Export root_agent for ADK Web discovery
root_agent = docs_refresher

