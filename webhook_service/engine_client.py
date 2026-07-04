"""Vertex AI Agent Engine discovery and streaming query client."""
import os
import json
import logging
from typing import Optional
import vertexai
from vertexai.preview import reasoning_engines
from google.cloud.aiplatform_v1beta1.types import reasoning_engine_execution_service as aip_types

from .broadcaster import broadcast_event

logger = logging.getLogger("webhook_service.engine_client")

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
