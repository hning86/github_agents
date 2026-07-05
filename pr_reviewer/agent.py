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

# Configure ADK's built-in VertexAiRagRetrieval tool for RAG context
rag_corpus_name = os.getenv("RAG_CORPUS_NAME", "").strip()

if rag_corpus_name:
    try:
        import vertexai
        parts = rag_corpus_name.split("/")
        if len(parts) >= 4:
            vertexai.init(project=parts[1], location=parts[3])
    except Exception as e:
        logger.warning(f"Could not initialize vertexai location from RAG_CORPUS_NAME: {e}")

    from google.adk.tools.retrieval import VertexAiRagRetrieval
    rag_tool = VertexAiRagRetrieval(
        name="retrieve_pr_review_rag_context",
        description="Retrieves repository architecture, Python style guidelines, and PR review evaluation rules from the Vertex AI RAG Engine corpus.",
        rag_corpora=[rag_corpus_name],
        similarity_top_k=4,
    )
    agent_tools = [mcp_toolset, rag_tool]
else:
    agent_tools = [mcp_toolset]


# Define the GitHub Helper Agent
pr_reviewer = Agent(
    model="gemini-2.5-pro",
    name="pr_reviewer",
    description="Agent with access to the remote GitHub-hosted MCP tools and Vertex AI RAG Engine to conduct standards-enforced Pull Request reviews.",
    instruction="""You are an expert GitHub assistant and automated PR Reviewer agent on Google Cloud Vertex AI Agent Engine.
You specialize in managing, querying, and interacting with the user's GitHub repositories, issues, pull requests, files, and users.
You MUST utilize your GitHub MCP tools whenever the user asks to fetch, update, list, create, or modify repositories or related objects. Do not guess or hallucinate any data.
If the GITHUB_PERSONAL_ACCESS_TOKEN is missing, invalid, or expired, kindly and professionally request the user to update the PAT in their .env file.

When conducting automated Pull Request code reviews:
1. First, call your 'retrieve_pr_review_rag_context' tool with targeted queries (such as 'Python style guide and async rules', 'PR review evaluation guidelines and severity tiers', or 'architecture overview and security conventions') to retrieve repository-specific RAG context and rules from our Vertex AI RAG Engine.
2. Inspect the PR diffs and changed files thoroughly using your GitHub MCP tools ('get_pull_request_files', 'get_pull_request').
3. Evaluate every modified line strictly against the retrieved RAG context (checking for mandatory 'uv' package management, precise type hints, non-blocking 'asyncio.to_thread' usage, structured exception logging with 'exc_info=True', security verification like 'hmac.compare_digest', and severity categorization).
4. If you identify specific lines of code that violate our RAG standards or require improvements, generate inline comments for those exact lines using the GitHub PR review workflow:
   - First, create a pending review using 'pull_request_review_write' with method 'create'.
   - Next, add specific comments to lines of changed files using 'add_comment_to_pending_review' (providing path, line number or position, and body formatted according to our RAG severity guidelines: [SEVERITY: CRITICAL / MODERATE / NITPICK]).
   - Finally, submit the review along with your overall summary using 'pull_request_review_write' with method 'submit_pending'.
5. If no specific line comments are deemed necessary after RAG evaluation, submit a general overall review approving the PR or comment directly on the Pull Request.
Be clear, accurate, and concise in your explanations and status updates.""",
    tools=agent_tools,
)


# Export root_agent for ADK Web discovery
root_agent = pr_reviewer


