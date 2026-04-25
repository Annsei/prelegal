#!/usr/bin/env bash
# Stop and remove the Prelegal container on Linux.
set -euo pipefail

CONTAINER="prelegal"

if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
  echo "[prelegal] Stopping $CONTAINER"
  docker rm -f "$CONTAINER" >/dev/null
else
  echo "[prelegal] No container named $CONTAINER is running."
fi
