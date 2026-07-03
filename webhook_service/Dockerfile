# Build from the repository root:
# docker build -f webhook_service/Dockerfile -t github-pr-reviewer .
FROM python:3.13-slim

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory inside container
WORKDIR /app

# Copy dependency files first to leverage Docker layer caching
COPY pyproject.toml README.md ./

# Install project dependencies without installing the project root yet
RUN uv sync --no-dev --no-install-project

# Copy the entire project code into the container
COPY pr_reviewer/ ./pr_reviewer/
COPY docs_refresher/ ./docs_refresher/

COPY webhook_service/ ./webhook_service/


# Install the local project package
RUN uv sync --no-dev

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PORT=8080

# Cloud Run defaults to port 8080
EXPOSE 8080

# Run the FastAPI server using uvicorn
CMD ["uvicorn", "webhook_service.main:app", "--host", "0.0.0.0", "--port", "8080"]
