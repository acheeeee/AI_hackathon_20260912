#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
deployment_dir="$(cd "${script_dir}/.." && pwd)"
repo_root="$(cd "${deployment_dir}/.." && pwd)"

fail() {
  echo "deployment validation failed: $*" >&2
  exit 1
}

require_text() {
  local file="$1"
  local text="$2"
  grep -Fq -- "${text}" "${file}" || fail "${file#${repo_root}/} lacks ${text}"
}

for script in "${deployment_dir}"/scripts/*.sh; do
  bash -n "${script}"
done

compose_json="$({
  docker compose \
    --project-directory "${deployment_dir}" \
    --env-file "${deployment_dir}/config.example" \
    --file "${deployment_dir}/compose.yaml" \
    config --format json
})"

COMPOSE_JSON="${compose_json}" python3 - <<'PY'
import json
import os

config = json.loads(os.environ['COMPOSE_JSON'])
services = config['services']
assert set(services) == {'caseapi', 'legacy-api', 'web'}
assert 'ports' not in services['caseapi']
assert 'ports' not in services['legacy-api']
web_ports = services['web'].get('ports', [])
assert len(web_ports) == 1
assert int(web_ports[0]['target']) == 8080
for service in services.values():
    assert service.get('read_only') is True
    assert service.get('cap_drop') == ['ALL']
    assert service.get('security_opt') == ['no-new-privileges:true']
PY

cloudformation="${deployment_dir}/aws/cloudformation.yaml"
require_text "${cloudformation}" 'CidrIp: 60.250.71.45/32'
require_text "${cloudformation}" 'CidrIp: 61.222.117.53/32'
require_text "${cloudformation}" 'CidrIp: 59.125.121.41/32'
require_text "${cloudformation}" 'CidrIp: 60.250.71.43/32'
ingress_cidr_count="$(
  sed -n '/SecurityGroupIngress:/,/SecurityGroupEgress:/p' "${cloudformation}" \
    | grep -c '^[[:space:]]*CidrIp:'
)"
[[ "${ingress_cidr_count}" -eq 4 ]] \
  || fail 'CloudFormation ingress must contain exactly the four approved CIDRs'
require_text "${cloudformation}" 'CreationPolicy:'
require_text "${cloudformation}" 'ResourceSignal:'
require_text "${cloudformation}" '/opt/aws/bin/cfn-signal'
require_text "${cloudformation}" 'HttpTokens: required'
require_text "${cloudformation}" '- DemoDefaultRoute'
require_text "${cloudformation}" '- DemoPublicSubnetRouteAssociation'
require_text "${cloudformation}" 'systemctl is-active --quiet amazon-ssm-agent'
require_text "${cloudformation}" 'chown -R ec2-user:ec2-user /opt/ai-hackathon'

require_text "${deployment_dir}/scripts/deploy.sh" 'WEB_PORT='
require_text "${deployment_dir}/scripts/deploy.sh" 'BASE_URL='
require_text "${deployment_dir}/scripts/smoke.sh" '/api/v1/cases?limit=1'
require_text "${deployment_dir}/scripts/publish-bundle.sh" 'head-object'
require_text "${deployment_dir}/scripts/publish-bundle.sh" '.sha256'
require_text "${deployment_dir}/scripts/publish-bundle.sh" 'refusing to publish a bundle from a dirty worktree'
require_text "${deployment_dir}/scripts/publish-images.sh" 'refusing to publish images from a dirty worktree'
require_text "${deployment_dir}/scripts/deploy.sh" 'immutable demo-vX.Y.Z tag in us-west-2 ECR'

if grep -Eq '^[[:space:]]*(export[[:space:]]+)?AWS_(ACCESS_KEY_ID|SECRET_ACCESS_KEY|SESSION_TOKEN)=' \
  "${deployment_dir}/config.example"; then
  fail 'config.example must not contain AWS credentials, even empty placeholders'
fi

echo 'deployment validation passed'
