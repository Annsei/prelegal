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

# Forward OPENROUTER_API_KEY (used by the AI chat) into the container.
# Prefer the project's .env file via --env-file, fall back to whatever is in
# the current shell. Missing key is OK — the chat endpoint will return 502
# with a clear message until one is configured.
ENV_FLAGS=()
if [[ -f "$ROOT/.env" ]]; then
  ENV_FLAGS+=(--env-file "$ROOT/.env")
elif [[ -n "${OPENROUTER_API_KEY:-}" ]]; then
  ENV_FLAGS+=(-e "OPENROUTER_API_KEY=$OPENROUTER_API_KEY")
fi

echo "[prelegal] Starting container on http://localhost:$PORT"
docker run -d --name "$CONTAINER" -p "${PORT}:8000" "${ENV_FLAGS[@]}" "$IMAGE" >/dev/null

echo "[prelegal] Up. Tail logs with: docker logs -f $CONTAINER"
