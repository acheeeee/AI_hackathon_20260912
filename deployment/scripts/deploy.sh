#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
deployment_dir="$(cd "${script_dir}/.." && pwd)"
environment_file="${DEPLOYMENT_ENV_FILE:-${deployment_dir}/.env}"
compose=(docker compose --project-directory "${deployment_dir}" --env-file "${environment_file}" --file "${deployment_dir}/compose.yaml")

if [[ ! -f "${environment_file}" ]]; then
  echo "missing ${environment_file}; copy config.example and replace all placeholders" >&2
  exit 1
fi

if grep -Eq '^AWS_(ACCESS_KEY_ID|SECRET_ACCESS_KEY|SESSION_TOKEN)=' "${environment_file}"; then
  echo "do not store AWS access keys in deployment/.env; use the EC2 instance role" >&2
  exit 1
fi

if grep -Eq 'ACCOUNT_ID|RUNTIME_ID' "${environment_file}"; then
  echo "deployment/.env still contains placeholders" >&2
  exit 1
fi

"${compose[@]}" config --quiet

region="$(sed -n 's/^AWS_DEFAULT_REGION=//p' "${environment_file}" | tail -n 1)"
region="${region:-us-west-2}"
mapfile -t registries < <(
  "${compose[@]}" config --images \
    | awk -F/ '/\.dkr\.ecr\./ {print $1}' \
    | sort -u
)
for registry in "${registries[@]}"; do
  aws ecr get-login-password --region "${region}" \
    | docker login --username AWS --password-stdin "${registry}"
done

"${script_dir}/backup-db.sh"
"${compose[@]}" pull
"${compose[@]}" up --detach --no-build --remove-orphans --wait
"${script_dir}/smoke.sh"

echo "deployment completed"
