#!/usr/bin/env bash
set -euo pipefail

base_url="${BASE_URL:-http://127.0.0.1}"

index_html="$(curl --fail --silent --show-error "${base_url}/")"
if [[ "${index_html}" != *'id="app"'* ]]; then
  echo "frontend smoke failed: ${base_url}/ does not contain the Vue mount point" >&2
  exit 1
fi

curl --fail --silent --show-error "${base_url}/healthz" >/dev/null
curl --fail --silent --show-error "${base_url}/api/health" >/dev/null
curl --fail --silent --show-error "${base_url}/api/v1/openapi.json" >/dev/null
curl --fail --silent --show-error "${base_url}/api/v1/cases?limit=1" >/dev/null

echo "smoke passed: ${base_url}"
