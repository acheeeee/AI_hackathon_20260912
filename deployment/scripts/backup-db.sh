#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
deployment_dir="$(cd "${script_dir}/.." && pwd)"
environment_file="${DEPLOYMENT_ENV_FILE:-${deployment_dir}/.env}"
compose=(docker compose --project-directory "${deployment_dir}" --env-file "${environment_file}" --file "${deployment_dir}/compose.yaml")

if [[ -z "$("${compose[@]}" ps --quiet caseapi)" ]]; then
  echo "caseapi is not running; no SQLite backup was created"
  exit 0
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_path="/var/lib/caseapi/backups/caseapi-${timestamp}.db"

"${compose[@]}" exec -T caseapi python - "${backup_path}" <<'PY'
import sqlite3
import sys
from pathlib import Path

source_path = Path('/var/lib/caseapi/caseapi.db')
backup_path = Path(sys.argv[1])
if not source_path.is_file():
    print('caseapi database does not exist; no backup was created')
    raise SystemExit(0)
backup_path.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(source_path) as source, sqlite3.connect(backup_path) as target:
    source.backup(target)
print(backup_path)
PY
