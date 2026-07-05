# ADK Python Style Guide & Engineering Standards

This document establishes mandatory coding standards, architectural patterns, and style conventions for all Python services within the `github_adk_agent` repository. Automated code review agents (`pr_reviewer`) and human engineers must enforce these standards across all pull requests.

---

## 1. Package & Dependency Management
- **Mandatory Package Manager:** Always use **`uv`** for dependency and environment management. Do NOT use standard `pip` or `virtualenv` directly when managing project dependencies.
- **Lockfile Enforcement:** All modifications to dependencies (`pyproject.toml`) must be accompanied by an updated `uv.lock` file generated via `uv lock` or `uv sync`.
- **Python Versioning:** Target Python 3.11+. Use modern language features (`match` statements, `typing.Union` syntax via `|`, and modern `asyncio` primitives).

---

## 2. Type Annotations & Type Safety
Every public function, method, class, and async handler MUST include precise type annotations.

### 2.1 Rules for Typing
- Use built-in generics where applicable (`list[str]`, `dict[str, Any]`, `tuple[int, ...]`) rather than importing from `typing` (`List`, `Dict`, `Tuple`).
- Explicitly annotate optional values as `Optional[T]` or `T | None`.
- Never use bare `Any` without an accompanying comment justifying why strict typing is impossible or impractical for that payload.

```python
# CORRECT
async def process_webhook_payload(
    payload: dict[str, Any],
    signature: str | None,
    secret: str
) -> bool:
    ...

# INCORRECT
def process_webhook_payload(payload, signature, secret):
    ...
```

---

## 3. Asynchronous Programming (`asyncio`)
FastAPI backend routes and agent execution handlers rely heavily on asynchronous event loops.

### 3.1 Blocking I/O & CPU-Intensive Tasks
- **Never perform synchronous blocking network calls** (e.g., `requests.get()`, synchronous `time.sleep()`, or blocking SDK initialization) directly inside `async def` endpoints or event loop tasks.
- Use `asyncio.to_thread(...)` or dedicated thread pools (`ThreadPoolExecutor`) when delegating heavy or synchronous SDK queries (such as Vertex AI Reasoning Engine invocations via `get_remote_engine()`).

```python
# CORRECT
eng = await asyncio.to_thread(get_remote_engine, "ADK GitHub PR Reviewer", engine_id)

# INCORRECT (Blocks the FastAPI event loop for all concurrent requests!)
eng = get_remote_engine("ADK GitHub PR Reviewer", engine_id)
```

---

## 4. Error Handling & Exception Management
- **Specific Catching:** Never use bare `except:` or `except Exception: pass` without structured logging and context reporting.
- **Logging Standards:** Use the configured logger instance (`logger = logging.getLogger(...)`). When catching exceptions in asynchronous tasks, always log the stack trace using `exc_info=True`.

```python
# CORRECT
try:
    await run_agent_workflow(repo_name, pr_num)
except Exception as e:
    logger.error(f"Failed to execute PR review agent for {repo_name} #{pr_num}: {e}", exc_info=True)
    broadcast_event("ERROR", "AGENT_FAIL", "Webhook Service", f"Task failed: {e}")
```

---

## 5. Security & Secrets Management
- **No Hardcoded Secrets:** Never hardcode API keys, tokens (`GITHUB_PERSONAL_ACCESS_TOKEN`), secrets (`GITHUB_WEBHOOK_SECRET`), or GCP Project IDs in source code.
- **Environment Retrieval:** Always retrieve configuration dynamically via `os.getenv()` after `load_dotenv()` or via configuration models, stripping extraneous whitespace (`os.getenv("KEY", "").strip()`).
- **Cryptographic Comparisons:** Always use `hmac.compare_digest()` when verifying webhook signatures or sensitive tokens to prevent timing attacks.
