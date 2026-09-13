#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
deployment_dir="$(cd "${script_dir}/.." && pwd)"
repo_root="$(cd "${deployment_dir}/.." && pwd)"
bucket="${1:-}"
version="${2:-}"

if [[ -z "${bucket}" || -z "${version}" ]]; then
  echo "usage: $0 <deployment-bucket> <version>" >&2
  exit 2
fi

if [[ ! "${version}" =~ ^demo-v[0-9]+\.[0-9]+\.[0-9]+([.-][a-z0-9]+)*$ ]]; then
  echo "version must look like demo-v0.2.0 or demo-v0.2.0-rc1" >&2
  exit 2
fi

if [[ -n "$(git -C "${repo_root}" status --porcelain --untracked-files=normal)" ]]; then
  echo "refusing to publish a bundle from a dirty worktree" >&2
  exit 1
fi

temporary_dir="$(mktemp -d)"
trap 'rm -rf -- "${temporary_dir}"' EXIT
archive="${temporary_dir}/deployment-${version}.tar.gz"
checksum_file="${temporary_dir}/deployment.tar.gz.sha256"

tar -C "${deployment_dir}" -czf "${archive}" \
  compose.yaml \
  config.example \
  scripts/backup-db.sh \
  scripts/deploy.sh \
  scripts/smoke.sh

if command -v sha256sum >/dev/null 2>&1; then
  checksum="$(sha256sum "${archive}" | awk '{print $1}')"
else
  checksum="$(shasum -a 256 "${archive}" | awk '{print $1}')"
fi
printf '%s  %s\n' "${checksum}" 'deployment.tar.gz' >"${checksum_file}"

key_prefix="releases/${version}"
for key in "${key_prefix}/deployment.tar.gz" "${key_prefix}/deployment.tar.gz.sha256"; do
  if aws s3api head-object --bucket "${bucket}" --key "${key}" >/dev/null 2>&1; then
    echo "refusing to overwrite existing s3://${bucket}/${key}" >&2
    exit 1
  fi
done

destination="s3://${bucket}/${key_prefix}/deployment.tar.gz"
checksum_destination="${destination}.sha256"
aws s3 cp "${archive}" "${destination}"
aws s3 cp "${checksum_file}" "${checksum_destination}"
echo "uploaded ${destination}"
echo "uploaded ${checksum_destination}"
