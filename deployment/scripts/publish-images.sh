#!/usr/bin/env bash
set -euo pipefail

version="${1:-}"
region="${AWS_DEFAULT_REGION:-us-west-2}"
repository_prefix="${ECR_REPOSITORY_PREFIX:-ai-hackathon-demo}"

if [[ -z "${version}" ]]; then
  echo "usage: $0 <version>" >&2
  exit 2
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
docker tag "${local_backend}" "${remote_backend}"
docker tag "${local_frontend}" "${remote_frontend}"
docker push "${remote_backend}"
docker push "${remote_frontend}"

echo "BACKEND_IMAGE=${remote_backend}"
echo "FRONTEND_IMAGE=${remote_frontend}"

