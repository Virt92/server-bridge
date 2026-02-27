#!/usr/bin/env bash
# Auto-refresh ANTHROPIC_API_KEY from Claude Code OAuth credentials
set -euo pipefail

AGENT_ENV=/root/core/.agent.env
CREDS=/root/.claude/.credentials.json

TOKEN=$(python3 -c "import json; print(json.load(open('$CREDS'))['claudeAiOauth']['accessToken'])" 2>/dev/null || echo "")

if [ -z "$TOKEN" ]; then
  echo "[refresh-token] ERROR: could not read token from $CREDS"
  exit 1
fi

if grep -q "^ANTHROPIC_API_KEY=" "$AGENT_ENV"; then
  sed -i "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=$TOKEN|" "$AGENT_ENV"
else
  echo "ANTHROPIC_API_KEY=$TOKEN" >> "$AGENT_ENV"
fi

echo "[refresh-token] $(date -u +%Y-%m-%dT%H:%M:%SZ) token updated (${#TOKEN} chars), reloading agents"
/root/core/agent restart >/dev/null 2>&1 || true
