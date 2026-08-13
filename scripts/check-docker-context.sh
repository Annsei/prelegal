#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DOCKERIGNORE="$REPO_ROOT/.dockerignore"

if [[ "${1:-}" == "--dockerignore" ]]; then
  if [[ $# -ne 2 ]]; then
    printf 'usage: %s [--dockerignore PATH]\n' "$0" >&2
    exit 2
  fi
  DOCKERIGNORE="$2"
elif [[ $# -ne 0 ]]; then
  printf 'usage: %s [--dockerignore PATH]\n' "$0" >&2
  exit 2
fi

if [[ ! -f "$DOCKERIGNORE" ]]; then
  printf 'docker_context_check_error=dockerignore_missing\n' >&2
  exit 2
fi

TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/prelegal-docker-context.XXXXXX")"
trap 'rm -rf "$TEMP_ROOT"' EXIT
CONTEXT="$TEMP_ROOT/context"
OUTPUT="$TEMP_ROOT/output"
mkdir -p "$CONTEXT"
cp "$DOCKERIGNORE" "$CONTEXT/.dockerignore"

EXCLUDED_PATHS=(
  ".codex/config.toml"
  "prelegal.code-workspace"
  "templates/sources/civil-code/PROVENANCE.md"
  "templates/sources/civil-code/sample.pdf"
  "templates/sources/civil-code/sample.txt"
  ".claude/canary.txt"
  ".env"
)

REQUIRED_PATHS=(
  "templates/manifests/pilot-agreement.json"
  "templates/pilot-agreement/standard_terms.md"
  "backend/app/main.py"
  "frontend/package.json"
  "templates/sources/professional-services-agreement/PROVENANCE.md"
  "templates/sources/professional-services-agreement/GF-2025-1001-委托合同-原文捕获.txt"
  "templates/sources/data-processing-agreement/PROVENANCE.md"
  "templates/sources/data-processing-agreement/GF-2025-2616-数据委托处理服务合同-原文捕获.txt"
)

for path in "${EXCLUDED_PATHS[@]}" "${REQUIRED_PATHS[@]}"; do
  mkdir -p "$CONTEXT/$(dirname "$path")"
  printf 'synthetic-canary\n' > "$CONTEXT/$path"
done

printf '%s\n' 'FROM scratch' 'COPY . /context/' > "$CONTEXT/Dockerfile"

if ! docker buildx build \
  --file "$CONTEXT/Dockerfile" \
  --output "type=local,dest=$OUTPUT" \
  "$CONTEXT" >/dev/null 2>&1; then
  printf 'docker_context_build=failed\n' >&2
  exit 2
fi

failed=0
for path in "${EXCLUDED_PATHS[@]}"; do
  if [[ -e "$OUTPUT/context/$path" ]]; then
    printf '%s=present\n' "$path"
    failed=1
  else
    printf '%s=absent\n' "$path"
  fi
done

for path in "${REQUIRED_PATHS[@]}"; do
  if [[ -e "$OUTPUT/context/$path" ]]; then
    printf '%s=present\n' "$path"
  else
    printf '%s=absent\n' "$path"
    failed=1
  fi
done

if [[ "$failed" -ne 0 ]]; then
  printf 'docker_context_check=failed\n' >&2
  exit 1
fi

printf 'docker_context_check=passed\n'
