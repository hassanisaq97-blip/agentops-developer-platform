#!/bin/sh
# Sikrer at det konfigurerede agent-workspace er et git-repository, før API'en
# starter — MCP-serverens get_git_diff/get_repository_status tools kræver det.
# Nødvendigt fordi workspacet typisk er et bind-mount (se compose.yaml), som
# ikke arver .git fra et Docker-image-lag.
set -e

WORKSPACE="${AGENT_WORKSPACE_ROOT:-/app/demo_repo}"

if [ ! -d "$WORKSPACE/.git" ]; then
    git -C "$WORKSPACE" init -q
    git -C "$WORKSPACE" config user.email "agentops@local"
    git -C "$WORKSPACE" config user.name "AgentOps Developer Platform"
    git -C "$WORKSPACE" add -A
    git -C "$WORKSPACE" commit -q -m "initial workspace state"
fi

exec "$@"
