#!/usr/bin/env bash
# Run DeckEngine (foreground). For production, use the systemd unit below.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
source .venv/bin/activate

export DECKENGINE_PREVIEW="${DECKENGINE_PREVIEW:-soffice}"   # Linux preview path
: "${OPENAI_API_KEY:=${ANTHROPIC_API_KEY:-}}"
if [ -z "${OPENAI_API_KEY:-}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "WARN: no LLM key set — the Describe path will error; JSON-spec path still works."
fi
if [ -z "${DECKENGINE_API_KEY:-}" ]; then
  echo "WARN: DECKENGINE_API_KEY not set — endpoints are OPEN. Set it before public exposure."
fi

# Bind to localhost; put nginx/Caddy in front for TLS on your domain.
exec .venv/bin/uvicorn deckengine.api.main:app \
  --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}" --workers "${WORKERS:-1}"
