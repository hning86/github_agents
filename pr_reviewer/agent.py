import os
os.environ["GOOGLE_API_USE_MTLS_ENDPOINT"] = "never"
os.environ["GOOGLE_API_USE_CLIENT_CERTIFICATE"] = "false"

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

def retrieve_pr_review_rag_context(query: str) -> str:
    """
    Retrieves relevant engineering standards, architectural documentation, and PR review guidelines from the Vertex AI RAG Engine corpus in us-east5.
    Call this tool BEFORE reviewing code changes to ensure all inline comments strictly enforce repository-specific conventions (e.g. uv package management, type hints, non-blocking asyncio, logging, and security).
    """
    # WHY WE USE A CUSTOM PYTHON FUNCTION TOOL INSTEAD OF ADK's VertexAiRagRetrieval:
    # ADK's built-in `VertexAiRagRetrieval` tool automatically converts into Gemini's native `types.Retrieval(vertex_rag_store=...)` parameter at request time for Gemini 2.x models.
    # However, Gemini's built-in regional `vertex_rag_store` API requires the `RagCorpus` to exist inside the EXACT SAME GCP region (`us-central1`) as the model prediction endpoint.
    # Because our Reasoning Engine runs in `us-central1` but our RagCorpus resides in `us-east5`, passing a cross-region `vertex_rag_store` triggers a `400 INVALID_ARGUMENT` API error from Gemini.
    # By implementing this custom Python function (`rag.retrieval_query`), the Python SDK inside our container handles the cross-region REST/gRPC lookup cleanly and returns pure string context without regional API rejection.
    rag_corpus_name = os.getenv("RAG_CORPUS_NAME", "").strip()
    if not rag_corpus_name:
        return "No RAG_CORPUS_NAME set in environment. Proceeding with standard review."

    try:
        import vertexai
        from vertexai.preview import rag

        # Extract project and location from corpus resource name: projects/{project}/locations/{location}/ragCorpora/{id}
        parts = rag_corpus_name.split("/")
        if len(parts) >= 4:
            project_id = parts[1]
            location = parts[3]
            vertexai.init(project=project_id, location=location)

        response = rag.retrieval_query(
            text=query,
            rag_resources=[rag.RagResource(rag_corpus=rag_corpus_name)],
            rag_retrieval_config=rag.RagRetrievalConfig(top_k=4),
        )

        contexts = []
        if hasattr(response, "contexts") and hasattr(response.contexts, "contexts"):
            for ctx in response.contexts.contexts:
                contexts.append(ctx.text)
        elif hasattr(response, "contexts"):
            for ctx in response.contexts:
                contexts.append(ctx.text)

        if not contexts:
            return "No relevant RAG contexts found for query."

        return "\n\n---\n\n".join(contexts)
    except Exception as e:
        logger.error(f"Error retrieving RAG context: {e}", exc_info=True)
        return f"Error retrieving RAG context: {e}"


agent_tools = [mcp_toolset, retrieve_pr_review_rag_context]


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


