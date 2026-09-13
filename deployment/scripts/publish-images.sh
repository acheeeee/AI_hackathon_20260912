#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
version="${1:-}"
region="${AWS_DEFAULT_REGION:-us-west-2}"
repository_prefix="${ECR_REPOSITORY_PREFIX:-ai-hackathon-demo}"

if [[ -z "${version}" ]]; then
  echo "usage: $0 <version>" >&2
  exit 2
fi

if [[ ! "${version}" =~ ^demo-v[0-9]+\.[0-9]+\.[0-9]+([.-][a-z0-9]+)*$ ]]; then
  echo "version must look like demo-v0.2.0 or demo-v0.2.0-rc1" >&2
  exit 2
fi

if [[ "${region}" != "us-west-2" ]]; then
  echo "this demo stack is fixed to us-west-2; refusing region ${region}" >&2
  exit 1
fi

if [[ -n "$(git -C "${repo_root}" status --porcelain --untracked-files=normal)" ]]; then
  echo "refusing to publish images from a dirty worktree" >&2
  exit 1
fi

account_id="$(aws sts get-caller-identity --query Account --output text)"
registry="${account_id}.dkr.ecr.${region}.amazonaws.com"
backend_repository="${repository_prefix}-backend"
frontend_repository="${repository_prefix}-frontend"
local_backend="${LOCAL_BACKEND_IMAGE:-ai-hackathon-backend:${version}}"
local_frontend="${LOCAL_FRONTEND_IMAGE:-ai-hackathon-frontend:${version}}"
remote_backend="${registry}/${backend_repository}:${version}"
remote_frontend="${registry}/${frontend_repository}:${version}"

aws ecr describe-repositories \
  --region "${region}" \
  --repository-names "${backend_repository}" "${frontend_repository}" >/dev/null

aws ecr get-login-password --region "${region}" \
  | docker login --username AWS --password-stdin "${registry}"

docker image inspect "${local_backend}" >/dev/null
docker image inspect "${local_frontend}" >/dev/null

revision="$(git -C "${repo_root}" rev-parse HEAD)"
for image in "${local_backend}" "${local_frontend}"; do
  image_version="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.version"}}' "${image}")"
  image_revision="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "${image}")"
  if [[ "${image_version}" != "${version}" || "${image_revision}" != "${revision}" ]]; then
    echo "${image} was not built for ${version} from current commit ${revision}" >&2
    exit 1
  fi
done

docker tag "${local_backend}" "${remote_backend}"
docker tag "${local_frontend}" "${remote_frontend}"
docker push "${remote_backend}"
docker push "${remote_frontend}"

echo "BACKEND_IMAGE=${remote_backend}"
echo "FRONTEND_IMAGE=${remote_frontend}"
