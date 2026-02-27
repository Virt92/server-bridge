#!/usr/bin/env bash
# Periodic sync of /root/core → git repo core/ directory, then commit+push.
# Controlled by GIT_SYNC_INTERVAL_SEC (default 1800 = 30 min).

set -euo pipefail

REPO=/root/codex-workspaces/default/server-bridge
SRC=/root/core
DEST=$REPO/core
INTERVAL=${GIT_SYNC_INTERVAL_SEC:-1800}

log() { echo "[git-sync] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

log "started — interval=${INTERVAL}s repo=$REPO"

while true; do
    # ── 1. Sync live code into repo's core/ directory ────────────────────────
    rsync -a --delete \
        --exclude='.pm2/' \
        --exclude='data/' \
        --exclude='logs/' \
        --exclude='.agent.env' \
        --exclude='**/__pycache__/' \
        --exclude='**/*.pyc' \
        --exclude='orchestrator/memory.md' \
        --exclude='orchestrator/pm_memory.md' \
        --exclude='developers/*/memory.md' \
        --exclude='developers/*/logs/' \
        "$SRC/" "$DEST/"

    # ── 2. Commit + push if anything changed ─────────────────────────────────
    cd "$REPO"

    # Untrack files that are now gitignored but were previously committed
    git ls-files --ignored --exclude-standard -c -z | xargs -0 --no-run-if-empty git rm --cached --quiet -- 2>/dev/null || true

    git add -A

    if ! git diff --staged --quiet; then
        TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
        git commit -m "chore: auto-sync $TIMESTAMP"
        git push origin
        log "pushed — $(git log -1 --oneline)"
    else
        log "no changes, skip push"
    fi

    sleep "$INTERVAL"
done
