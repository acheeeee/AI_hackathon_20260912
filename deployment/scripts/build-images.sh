#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"
version="${1:-}"

if [[ -z "${version}" ]]; then
  echo "usage: $0 <version>" >&2
  echo "example: $0 demo-v0.1.0" >&2
  exit 2
fi

if [[ ! "${version}" =~ ^demo-v[0-9]+\.[0-9]+\.[0-9]+([.-][a-z0-9]+)*$ ]]; then
  echo "version must look like demo-v0.2.0 or demo-v0.2.0-rc1" >&2
  exit 2
fi

if [[ "${ALLOW_DIRTY_BUILD:-0}" != "1" ]] \
  && [[ -n "$(git -C "${repo_root}" status --porcelain --untracked-files=normal)" ]]; then
  echo "refusing to publish an ambiguous build from a dirty worktree" >&2
  echo "commit the intended release, or set ALLOW_DIRTY_BUILD=1 for local verification only" >&2
  exit 1
fi

revision="$(git -C "${repo_root}" rev-parse HEAD)"
platform="${DOCKER_PLATFORM:-linux/amd64}"
backend_image="${LOCAL_BACKEND_IMAGE:-ai-hackathon-backend:${version}}"
frontend_image="${LOCAL_FRONTEND_IMAGE:-ai-hackathon-frontend:${version}}"
build_options=()
if [[ "${DOCKER_NO_CACHE:-0}" == "1" ]]; then
  build_options+=(--no-cache)
fi

docker build \
  "${build_options[@]}" \
  --platform "${platform}" \
  --file "${repo_root}/deployment/docker/backend.Dockerfile" \
  --build-arg "APP_VERSION=${version}" \
  --build-arg "VCS_REF=${revision}" \
  --tag "${backend_image}" \
  "${repo_root}"

docker build \
  "${build_options[@]}" \
  --platform "${platform}" \
  --file "${repo_root}/deployment/docker/frontend.Dockerfile" \
  --build-arg "APP_VERSION=${version}" \
  --build-arg "VCS_REF=${revision}" \
  --tag "${frontend_image}" \
  "${repo_root}"

echo "built ${backend_image}"
echo "built ${frontend_image}"
echo "platform ${platform}"
