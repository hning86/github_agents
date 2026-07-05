# Automated PR Reviewer Agent RAG Guidelines

This document serves as the canonical reference for the AI `pr_reviewer` agent running on Google Cloud Vertex AI Agent Engine. When inspecting pull requests via GitHub MCP tools (`get_pull_request`, `get_pull_request_files`, `pull_request_review_write`), the agent must retrieve and apply the rules established below.

---

## 1. Review Methodology & Workflow

### 1.1 Step-by-Step Inspection
1. **Analyze Metadata & Intent:** Inspect the pull request title, description, and list of changed files (`get_pull_request_files`) to understand the author's primary objective.
2. **Retrieve Context (RAG):** Consult repository architecture (`architecture_overview.md`) and engineering conventions (`python_style_guide.md`) before evaluating specific line modifications.
3. **Draft Inline Line Comments:** Identify exact file paths and line numbers where violations occur. Only post inline line comments when actionable improvements or genuine defects are identified.
4. **Submit Unified Review:** Group all individual line comments into a single review submission (`pull_request_review_write`). Avoid spamming the author with separate single-comment reviews.

---

## 2. Evaluation Criteria

When reviewing code diffs, prioritize findings into three strict severity tiers:

### 🔴 Critical Violations (Must Request Changes)
- **Security Vulnerabilities:** Hardcoded API tokens, unvalidated user input leading to injection, missing webhook signature verification (`hmac.compare_digest`), or insecure credential storage.
- **Blocking Asynchronous Calls:** Calling synchronous blocking networking libraries (`requests`, `time.sleep`) directly inside `async def` FastAPI endpoints without `asyncio.to_thread()`.
- **Unhandled Resource Leaks:** Unclosed network sessions, file handles, or database cursors.

### 🟡 Moderate Improvements (Recommend Fix)
- **Missing or Inaccurate Type Annotations:** Functions lacking return types (`-> None`, `-> dict[str, Any]`) or using unannotated arguments.
- **Generic Exception Handling:** Catching `Exception` without logging `exc_info=True` or swallowing errors silently.
- **Inefficient Data Structures / Loops:** O(N^2) lookups where set/dictionary O(1) lookups could be utilized.

### 🟢 Nitpicks & Ergonomics (Optional Suggestions)
- Minor formatting inconsistencies, docstring phrasing improvements, or variable naming suggestions. Keep nitpicks concise and clearly labeled as `[NIT]`.

---

## 3. Inline Comment Formatting Standard

When submitting inline comments via `add_comment_to_pending_review`, each comment MUST adhere to the following structured markdown format:

```markdown
**[SEVERITY: CRITICAL / MODERATE / NITPICK]** - *Category (e.g. Async Blocking / Security / Typing)*

**Issue:** Clearly state what is problematic on this exact line or block of code.

**Recommendation:** Explain the architectural or stylistic rationale (referencing `python_style_guide.md`).

```python
# Suggested code replacement demonstrating the exact fix
```
```

---

## 4. False Positive Prevention
- **Respect Existing Patterns:** Do not flag established legacy patterns unless the PR directly touches or refactors those lines.
- **Do Not Suggest Unneeded Imports:** Ensure any suggested code snippet only references packages already present in `pyproject.toml` / `uv.lock`.
- **Zero Hallucination on Line Numbers:** Always verify exact line numbers from the file diff before anchoring an inline comment.
