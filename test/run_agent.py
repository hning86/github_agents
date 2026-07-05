import asyncio
import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# Ensure parent directory (project root) is on sys.path so local modules (e.g. pr_reviewer) can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("run_agent")

def check_env():
    """Verify and print status of essential environment variables."""
    gcp_project = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    pat = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
    
    print("\n" + "="*50)
    print("           ADK GITHUB AGENT RUNNER")
    print("="*50)
    
    if not gcp_project:
        print("❌ GCP_PROJECT_ID: NOT SET!")
        print("   -> Set GCP_PROJECT_ID in your .env file to enable Vertex AI.")
    else:
        print(f"✅ GCP_PROJECT_ID: {gcp_project}")
        
    if not pat:
        print("❌ GITHUB_PERSONAL_ACCESS_TOKEN: NOT SET!")
        print("   -> Provide a GitHub Personal Access Token (PAT) in your .env file.")
    else:
        print(f"✅ GITHUB_PERSONAL_ACCESS_TOKEN: {pat[:8]}... (Configured)")
        
    print(f"✅ GOOGLE_GENAI_USE_VERTEXAI: {os.getenv('GOOGLE_GENAI_USE_VERTEXAI', '1')}")
    print("="*50 + "\n")
    
    if not gcp_project or not pat:
        print("⚠️  Warning: Missing credentials. The agent run may fail or request settings.")
        print("Please check your .env file or copy .env.example to set up.\n")

async def run_query(query: str):
    """Run a single query through the ADK InMemoryRunner."""
    try:
        from pr_reviewer.agent import pr_reviewer

        from google.adk.runners import InMemoryRunner
        from google.adk.agents.run_config import RunConfig
        from google.genai import types
    except ImportError as e:
        logger.error(f"Failed to import ADK modules: {e}")
        logger.error("Please make sure you have run 'uv sync' to install dependencies.")
        sys.exit(1)
        
    # Configure runner
    logger.info("Initializing InMemoryRunner...")
    runner = InMemoryRunner(agent=pr_reviewer)

    runner.auto_create_session = True
    
    run_config = RunConfig()
    
    print(f"Sending Query to Agent: \"{query}\"\n")
    print("Agent Output Stream:")
    print("-"*50)
    
    user_message = types.Content(
        role="user",
        parts=[types.Part(text=query)]
    )
    
    try:
        async for event in runner.run_async(
            user_id="local_user",
            session_id="local_session",
            new_message=user_message,
            run_config=run_config
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        print(part.text, end="", flush=True)
                    if part.function_call:
                        print(f"\n⚙️  [Tool Call]: {part.function_call.name}(args={part.function_call.args})")
                    if part.function_response:
                        print(f"\n📥 [Tool Response] {part.function_response.name}: Completed successfully.")
        print()
    except Exception as e:
        logger.error(f"An error occurred during agent execution: {e}")
    
    print("-"*50)

def main():
    check_env()
    
    # Check if prompt is supplied from command line
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = "Show my GitHub profile info and repositories list"
        print(f"No prompt provided. Using default query: '{query}'\n")
        
    asyncio.run(run_query(query))

if __name__ == "__main__":
    main()
