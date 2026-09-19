# syntax=docker/dockerfile:1
#
# Multi-stage build for API-processen. MCP-serveren kører IKKE som et separat
# netværks-image: den spawnes som en stdio-subprocess af agent-orchestratoren
# inden i denne container, ligesom Claude Code selv ville gøre det (se
# docs/adr/0001-hvorfor-mcp.md). Der er derfor ét runtime-image, ikke to.
#
# Builder-stadiet installerer afhængigheder med uv (hurtigere, deterministisk
# lockfile-baseret install); runtime-stadiet er slankt og kører som en
# non-root bruger.

FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir "uv>=0.8,<0.9"

WORKDIR /build
COPY pyproject.toml ./
RUN uv venv /opt/venv --python 3.12 && \
    . /opt/venv/bin/activate && \
    uv pip install -r pyproject.toml --no-cache

FROM python:3.12-slim AS runtime

# git er en runtime-afhængighed: MCP-serverens get_git_diff/get_repository_status
# tools kalder den faktiske git-binary (allowlisted, read-only — se
# agentops.security.commands) mod målrepositoryet.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system agentops && useradd --system --gid agentops --home-dir /app agentops

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY src/ src/
COPY evals/fixtures/ evals/fixtures/
COPY demo_repo/ demo_repo/
COPY migrations/ migrations/
COPY alembic.ini ./
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV AGENT_WORKSPACE_ROOT=/app/demo_repo

RUN mkdir -p /app/evals/results && chown -R agentops:agentops /app

USER agentops

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=3).status == 200 else 1)"

ENTRYPOINT ["entrypoint.sh"]
CMD ["uvicorn", "agentops.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
