#!/usr/bin/env python3
"""
Test script to discover and test ADK agents deployed to Google Cloud Vertex AI Agent Engine.
"""
import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv

# Suppress local method registration warnings
logging.basicConfig(level=logging.ERROR)

import vertexai
from vertexai.preview import reasoning_engines
from google.cloud.aiplatform_v1beta1.types import reasoning_engine_execution_service as aip_types

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "ninghai-ccai")
REGION = os.getenv("GCP_REGION", "us-central1")

def query_remote_agent(engine: reasoning_engines.ReasoningEngine, message: str, user_id: str = "tester") -> str:
    """Helper to query an ADK agent on Agent Engine via stream_query."""
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
                    if "text" in part:
                        full_text.append(part["text"])
            except json.JSONDecodeError:
                pass
    return "".join(full_text)

def main():
    print("============================================================")
    print(f" 🔍 Discovering Deployed Agents in GCP Agent Registry")
    print(f"    Project: {PROJECT_ID} | Region: {REGION}")
    print("============================================================")
    
    vertexai.init(project=PROJECT_ID, location=REGION)
    
    # 1. List all reasoning engines in the registry
    all_engines = reasoning_engines.ReasoningEngine.list()
    
    target_names = ["ADK GitHub PR Reviewer", "ADK GitHub Docs Refresher"]
    found_engines = {}
    
    print("\nAvailable Reasoning Engines:")
    for eng in all_engines:
        print(f"  • {eng.display_name:<30} | {eng.resource_name}")
        if eng.display_name in target_names and eng.display_name not in found_engines:
            found_engines[eng.display_name] = eng

    # 2. Test each target agent
    print("\n============================================================")
    print(" 🧪 Live Testing Deployed Agents")
    print("============================================================")
    
    for name in target_names:
        if name in found_engines:
            summary_eng = found_engines[name]
            eng = reasoning_engines.ReasoningEngine(summary_eng.resource_name)
            print(f"\n🚀 Testing [{name}] ({eng.resource_name})...")

            prompt = "Please confirm you are online and explain your role in one concise sentence."
            print(f"💬 Prompt: \"{prompt}\"")
            try:
                answer = query_remote_agent(eng, message=prompt)
                print(f"🤖 Response: {answer}")
            except Exception as e:
                print(f"❌ Error querying {name}: {e}")
        else:
            print(f"\n⚠️ Agent '{name}' was not found in the active registry.")

    print("\n✅ Live test completed!")

if __name__ == "__main__":
    main()
