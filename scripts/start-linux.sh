#!/usr/bin/env bash
# Build and start the Prelegal container on Linux.
# DB is recreated from scratch on every run — by design.
set -euo pipefail

IMAGE="prelegal:latest"
CONTAINER="prelegal"
PORT="8000"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "[prelegal] Building image: $IMAGE"
docker build -t "$IMAGE" .

docker rm -f "$CONTAINER" >/dev/null 2>&1 || true

echo "[prelegal] Starting container on http://localhost:$PORT"
docker run -d --name "$CONTAINER" -p "${PORT}:8000" "$IMAGE" >/dev/null

echo "[prelegal] Up. Tail logs with: docker logs -f $CONTAINER"
