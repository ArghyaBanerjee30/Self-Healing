#!/bin/bash
set -e

# ── Usage ─────────────────────────────────────────────────────────────────────
# ./deploy.sh <path-to-repo>
#
# Example:
# ./deploy.sh /Users/arghyabanerjee/Desktop/developer-joi-delivery-python

REPO_PATH="${1}"

if [ -z "$REPO_PATH" ]; then
  echo "Usage: ./deploy.sh <path-to-repo>"
  exit 1
fi

if [ ! -d "$REPO_PATH" ]; then
  echo "Error: repo path does not exist: $REPO_PATH"
  exit 1
fi

echo ""
echo "=== Self-Healing Loader ==="
echo "    Repo    : $REPO_PATH"
echo "    Project : my_project"
echo ""

# ── Step 1: Start Neo4j (if not already running) ──────────────────────────────
echo ">>> Starting Neo4j ..."
docker compose up -d neo4j

# ── Step 2: Copy repo into the named volume so the loader container can read it
echo ">>> Copying repo into Docker volume ..."
docker run --rm \
  -v "$(realpath "$REPO_PATH"):/source:ro" \
  -v "self-healing_repo_code:/repo" \
  alpine sh -c "cp -r /source/. /repo/"

# ── Step 3: Wait for Neo4j to be healthy, then run the loader ─────────────────
echo ">>> Running loader (parse + upload to Neo4j) ..."
docker compose run --rm loader

echo ""
echo "=== Done ==="
echo "    Neo4j browser : http://localhost:7474  (neo4j / password123)"
echo ""
