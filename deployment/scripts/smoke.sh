#!/usr/bin/env bash
set -euo pipefail

base_url="${BASE_URL:-http://127.0.0.1}"

curl --fail --silent --show-error "${base_url}/healthz" >/dev/null
curl --fail --silent --show-error "${base_url}/api/health" >/dev/null
curl --fail --silent --show-error "${base_url}/api/v1/openapi.json" >/dev/null

echo "smoke passed: ${base_url}"

