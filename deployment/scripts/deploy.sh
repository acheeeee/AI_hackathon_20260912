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

if grep -Eq '^[[:space:]]*(export[[:space:]]+)?AWS_(ACCESS_KEY_ID|SECRET_ACCESS_KEY|SESSION_TOKEN)=' \
  "${environment_file}"; then
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
if [[ "${region}" != "us-west-2" ]]; then
  echo "this demo stack is fixed to us-west-2; refusing region ${region}" >&2
  exit 1
fi

web_port="$(sed -n 's/^WEB_PORT=//p' "${environment_file}" | tail -n 1)"
web_port="${web_port:-80}"
if [[ ! "${web_port}" =~ ^[0-9]+$ ]] || (( web_port < 1 || web_port > 65535 )); then
  echo "WEB_PORT must be an integer from 1 to 65535" >&2
  exit 1
fi

mapfile -t images < <("${compose[@]}" config --images | sort -u)
for image in "${images[@]}"; do
  if [[ ! "${image}" =~ ^[0-9]{12}\.dkr\.ecr\.us-west-2\.amazonaws\.com/[a-z0-9._/-]+:demo-v[0-9]+\.[0-9]+\.[0-9]+([.-][a-z0-9]+)*$ ]]; then
    echo "deployment image must be an immutable demo-vX.Y.Z tag in us-west-2 ECR: ${image}" >&2
    exit 1
  fi
done

mapfile -t registries < <(printf '%s\n' "${images[@]}" | awk -F/ '{print $1}' | sort -u)
if (( ${#registries[@]} != 1 )); then
  echo "backend and frontend images must come from one AWS account registry" >&2
  exit 1
fi

for registry in "${registries[@]}"; do
  aws ecr get-login-password --region "${region}" \
    | docker login --username AWS --password-stdin "${registry}"
done

"${script_dir}/backup-db.sh"
"${compose[@]}" pull

previous_backend=''
previous_frontend=''
caseapi_container="$("${compose[@]}" ps --quiet caseapi)"
web_container="$("${compose[@]}" ps --quiet web)"
if [[ -n "${caseapi_container}" && -n "${web_container}" ]]; then
  previous_backend="$(docker inspect --format '{{.Config.Image}}' "${caseapi_container}")"
  previous_frontend="$(docker inspect --format '{{.Config.Image}}' "${web_container}")"
fi

rollback_on_failure() {
  original_status=$?
  trap - ERR
  if [[ -n "${previous_backend}" && -n "${previous_frontend}" ]]; then
    echo "deployment failed; restoring the previously running images" >&2
    set +e
    env \
      BACKEND_IMAGE="${previous_backend}" \
      FRONTEND_IMAGE="${previous_frontend}" \
      "${compose[@]}" up --detach --no-build --remove-orphans --wait
    rollback_status=$?
    if (( rollback_status == 0 )); then
      BASE_URL="http://127.0.0.1:${web_port}" "${script_dir}/smoke.sh"
      rollback_status=$?
    fi
    set -e
    if (( rollback_status == 0 )); then
      echo "previous images restored; fix deployment/.env before retrying" >&2
    else
      echo "automatic image rollback failed; inspect the compose services over SSM" >&2
    fi
  else
    echo "deployment failed and no previous service set was available to restore" >&2
  fi
  exit "${original_status}"
}

trap rollback_on_failure ERR
"${compose[@]}" up --detach --no-build --remove-orphans --wait
BASE_URL="http://127.0.0.1:${web_port}" "${script_dir}/smoke.sh"
trap - ERR

echo "deployment completed"
