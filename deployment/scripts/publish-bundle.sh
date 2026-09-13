#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
deployment_dir="$(cd "${script_dir}/.." && pwd)"
bucket="${1:-}"
version="${2:-}"

if [[ -z "${bucket}" || -z "${version}" ]]; then
  echo "usage: $0 <deployment-bucket> <version>" >&2
  exit 2
fi

temporary_dir="$(mktemp -d)"
trap 'rm -rf -- "${temporary_dir}"' EXIT
archive="${temporary_dir}/deployment-${version}.tar.gz"

tar -C "${deployment_dir}" -czf "${archive}" \
  compose.yaml \
  config.example \
  scripts/backup-db.sh \
  scripts/deploy.sh \
  scripts/smoke.sh

destination="s3://${bucket}/releases/${version}/deployment.tar.gz"
aws s3 cp "${archive}" "${destination}"
echo "uploaded ${destination}"

