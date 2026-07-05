#!/usr/bin/env python3
"""
ingest_to_rag_engine.py

Ingests all markdown (.md) documentation files from the `mock_docs/` directory
into a Google Cloud Vertex AI RAG Engine corpus in the `us-east5` region.

Usage:
    uv run python3 mock_docs/ingest_to_rag_engine.py
"""

import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# Ensure parent directory (project root) is on sys.path and load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("rag_ingestion")

try:
    import vertexai
    from vertexai.preview import rag
except ImportError as e:
    logger.error(f"Failed to import vertexai RAG SDK: {e}")
    logger.error("Please ensure dependencies are installed via `uv sync`.")
    sys.exit(1)


# --- Configuration ---
PROJECT_ID = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT", "ninghai-ccai")
REGION = "us-east5"  # Explicitly set to us-east5 as requested
CORPUS_DISPLAY_NAME = "ADK PR Reviewer Mock Docs"
CORPUS_DESCRIPTION = "Architecture documentation, Python style guides, and PR review instructions for ADK Agent RAG context."
MOCK_DOCS_DIR = Path(__file__).resolve().parent / "docs"


def get_or_create_corpus() -> str:
    """Check for an existing RagCorpus by display_name in us-east5, or create one if it does not exist."""
    logger.info(f"Checking existing RAG corpora in project={PROJECT_ID}, location={REGION}...")
    try:
        existing_corpora = rag.list_corpora()
        for c in existing_corpora:
            if getattr(c, "display_name", "") == CORPUS_DISPLAY_NAME:
                logger.info(f"✅ Found existing RagCorpus: '{CORPUS_DISPLAY_NAME}' ({c.name})")
                return c.name
    except Exception as e:
        logger.warning(f"Could not list existing corpora (or none exist): {e}")

    logger.info(f"✨ Creating new RagCorpus '{CORPUS_DISPLAY_NAME}' in {REGION}...")
    corpus = rag.create_corpus(
        display_name=CORPUS_DISPLAY_NAME,
        description=CORPUS_DESCRIPTION,
    )
    logger.info(f"✅ Successfully created RagCorpus: {corpus.name}")
    return corpus.name


def ingest_markdown_files(corpus_name: str):
    """Finds all .md files in mock_docs and uploads them to the specified RagCorpus."""
    md_files = sorted(list(MOCK_DOCS_DIR.glob("*.md")))
    if not md_files:
        logger.error(f"No .md files found in {MOCK_DOCS_DIR}")
        return

    logger.info(f"Found {len(md_files)} markdown files in {MOCK_DOCS_DIR} to ingest.")

    # Configure optimal semantic chunking for documentation and guidelines
    chunk_config = rag.TransformationConfig(
        chunking_config=rag.ChunkingConfig(chunk_size=1024, chunk_overlap=200)
    )

    for md_file in md_files:
        logger.info(f"📤 Uploading {md_file.name} to corpus {corpus_name}...")
        try:
            rag_file = rag.upload_file(
                corpus_name=corpus_name,
                path=str(md_file),
                display_name=md_file.name,
                description=f"Automated ingestion of {md_file.name}",
                transformation_config=chunk_config,
            )
            logger.info(f"  -> ✅ Uploaded {md_file.name} (ID: {rag_file.name})")
        except Exception as e:
            logger.error(f"  -> ❌ Failed to upload {md_file.name}: {e}")


def test_retrieval(corpus_name: str):
    """Runs a quick verification query against the newly populated RagCorpus."""
    test_query = "What package manager must be used for Python dependencies, and how should blocking I/O be handled in async functions?"
    logger.info("\n" + "=" * 60)
    logger.info(f"🔍 Running test retrieval query against {corpus_name}...")
    logger.info(f"Query: \"{test_query}\"")
    logger.info("=" * 60)

    try:
        response = rag.retrieval_query(
            text=test_query,
            rag_resources=[rag.RagResource(rag_corpus=corpus_name)],
            rag_retrieval_config=rag.RagRetrievalConfig(top_k=2),
        )

        contexts = []
        if hasattr(response, "contexts") and hasattr(response.contexts, "contexts"):
            for ctx in response.contexts.contexts:
                contexts.append(ctx.text)
        elif hasattr(response, "contexts"):
            for ctx in response.contexts:
                contexts.append(ctx.text)

        if not contexts:
            logger.warning("No contexts returned from test query.")
        else:
            for idx, text in enumerate(contexts, 1):
                logger.info(f"\n--- Result #{idx} ---")
                logger.info(text.strip()[:400] + ("..." if len(text) > 400 else ""))

    except Exception as e:
        logger.error(f"Test retrieval query failed: {e}")


def main():
    print("\n" + "=" * 60)
    print("      VERTEX AI RAG ENGINE INGESTION (mock_docs)")
    print("=" * 60)
    print(f"Target Project ID: {PROJECT_ID}")
    print(f"Target Region:     {REGION}")
    print(f"Source Directory:  {MOCK_DOCS_DIR}")
    print("=" * 60 + "\n")

    if not PROJECT_ID:
        logger.error("GCP_PROJECT_ID is not set! Please verify your .env file.")
        sys.exit(1)

    # Initialize Vertex AI SDK in us-east5
    logger.info(f"Initializing Vertex AI in project={PROJECT_ID}, location={REGION}...")
    vertexai.init(project=PROJECT_ID, location=REGION)

    # 1. Get or create the RagCorpus
    corpus_name = get_or_create_corpus()

    # 2. Ingest markdown files
    ingest_markdown_files(corpus_name)

    # 3. Test retrieval
    test_retrieval(corpus_name)

    print("\n" + "=" * 60)
    print("🎉 INGESTION COMPLETE!")
    print("=" * 60)
    print("To use this RAG Corpus in your PR Reviewer agent or .env file, save:")
    print(f"RAG_CORPUS_NAME={corpus_name}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
