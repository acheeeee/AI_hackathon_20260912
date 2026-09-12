#!/usr/bin/env python3
"""一次性部署腳本：把 agentcore_app/agent.py 部署到 AWS Bedrock AgentCore Runtime。

**這支腳本會在使用者的 AWS 帳號建立真實資源**（IAM role、S3 bucket、一個
AgentCore Runtime），不是測試，不進 pytest，也不會被 CI 執行。手動執行：

    cd backend
    set -a && source ../.env && set +a
    .venv/bin/python scripts/deploy_agentcore.py

會建立／更新：
  - IAM role：`caseapi-agentcore-execution-role`（信任 bedrock-agentcore.amazonaws.com，
    只給 CloudWatch Logs、X-Ray、Bedrock InvokeModel 這幾個 runtime 執行必要的權限）
  - S3 bucket：`bedrock-agentcore-code-{account_id}-{region}`（direct code deploy 用）
  - AgentCore Runtime：`caseapi_demo_agent`（direct code deploy，不建 Docker image）

重跑這支腳本是安全的：role／bucket 已存在就重用，runtime 已存在就呼叫
`update_agent_runtime` 而不是重建。要整個刪除，見檔案最後的「清理」段落。

部署完成後把印出的 Runtime ARN 貼進 `.env` 的
`CASEAPI_AGENTCORE_RUNTIME_ARN`，並把 `CASEAPI_MODEL_PROVIDER=agentcore`
一起設定，`caseapi.main` 啟動時才會用線上 provider 取代固定假模型。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import boto3
import botocore

AGENT_NAME = 'caseapi_demo_agent'
ROLE_NAME = 'caseapi-agentcore-execution-role'
RUNTIME_PYTHON_VERSION = 'PYTHON_3_12'
IDLE_SESSION_TIMEOUT_SECONDS = 300
MAX_LIFETIME_SECONDS = 1800
ROLE_PROPAGATION_WAIT_SECONDS = 10
RUNTIME_READY_TIMEOUT_SECONDS = 240
RUNTIME_READY_POLL_SECONDS = 5

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_SOURCE = REPO_ROOT / 'agentcore_app' / 'agent.py'


def _account_and_region() -> tuple[str, str]:
    session = boto3.Session()
    region = session.region_name
    if not region:
        raise SystemExit('AWS_DEFAULT_REGION 未設定；先 source .env 再執行本腳本。')
    account_id = boto3.client('sts').get_caller_identity()['Account']
    return account_id, region


def _trust_policy(account_id: str, region: str) -> dict:
    return {
        'Version': '2012-10-17',
        'Statement': [
            {
                'Sid': 'AssumeRolePolicy',
                'Effect': 'Allow',
                'Principal': {'Service': 'bedrock-agentcore.amazonaws.com'},
                'Action': 'sts:AssumeRole',
                'Condition': {
                    'StringEquals': {'aws:SourceAccount': account_id},
                    'ArnLike': {'aws:SourceArn': f'arn:aws:bedrock-agentcore:{region}:{account_id}:*'},
                },
            }
        ],
    }


def _execution_policy(account_id: str, region: str) -> dict:
    log_group_prefix = f'arn:aws:logs:{region}:{account_id}:log-group:/aws/bedrock-agentcore/runtimes'
    return {
        'Version': '2012-10-17',
        'Statement': [
            {
                'Effect': 'Allow',
                'Action': ['logs:DescribeLogStreams', 'logs:CreateLogGroup'],
                'Resource': [f'{log_group_prefix}/*'],
            },
            {
                'Effect': 'Allow',
                'Action': ['logs:PutResourcePolicy'],
                'Resource': [f'{log_group_prefix}/{AGENT_NAME}-*'],
            },
            {
                'Effect': 'Allow',
                'Action': ['logs:DescribeLogGroups'],
                'Resource': [f'arn:aws:logs:{region}:{account_id}:log-group:*'],
            },
            {
                'Effect': 'Allow',
                'Action': ['logs:CreateLogStream', 'logs:PutLogEvents'],
                'Resource': [f'{log_group_prefix}/*:log-stream:*'],
            },
            {
                'Effect': 'Allow',
                'Action': [
                    'xray:PutTraceSegments',
                    'xray:PutTelemetryRecords',
                    'xray:GetSamplingRules',
                    'xray:GetSamplingTargets',
                ],
                'Resource': ['*'],
            },
            {
                'Effect': 'Allow',
                'Resource': '*',
                'Action': 'cloudwatch:PutMetricData',
                'Condition': {'StringEquals': {'cloudwatch:namespace': 'bedrock-agentcore'}},
            },
            {
                'Sid': 'BedrockModelInvocation',
                'Effect': 'Allow',
                'Action': ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
                'Resource': [
                    'arn:aws:bedrock:*::foundation-model/*',
                    f'arn:aws:bedrock:{region}:{account_id}:*',
                ],
            },
        ],
    }


def ensure_execution_role(account_id: str, region: str) -> str:
    iam = boto3.client('iam')
    trust = json.dumps(_trust_policy(account_id, region))
    try:
        role = iam.get_role(RoleName=ROLE_NAME)['Role']
        iam.update_assume_role_policy(RoleName=ROLE_NAME, PolicyDocument=trust)
        print(f'[iam] 重用既有 role: {role["Arn"]}')
        created = False
    except iam.exceptions.NoSuchEntityException:
        role = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=trust,
            Description='AgentCore Runtime execution role for the caseapi demo agent',
        )['Role']
        print(f'[iam] 建立新 role: {role["Arn"]}')
        created = True
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName='caseapi-agentcore-execution-policy',
        PolicyDocument=json.dumps(_execution_policy(account_id, region)),
    )
    if created:
        print(f'[iam] 等待 {ROLE_PROPAGATION_WAIT_SECONDS}s 讓新 role 在 AWS 內部傳播完成……')
        time.sleep(ROLE_PROPAGATION_WAIT_SECONDS)
    return role['Arn']


def ensure_bucket(account_id: str, region: str) -> str:
    bucket_name = f'bedrock-agentcore-code-{account_id}-{region}'
    s3 = boto3.client('s3', region_name=region)
    try:
        s3.head_bucket(Bucket=bucket_name)
        print(f'[s3] 重用既有 bucket: {bucket_name}')
    except botocore.exceptions.ClientError as exc:
        status = exc.response.get('ResponseMetadata', {}).get('HTTPStatusCode')
        if status != 404:
            raise
        create_kwargs = {'Bucket': bucket_name}
        if region != 'us-east-1':
            create_kwargs['CreateBucketConfiguration'] = {'LocationConstraint': region}
        s3.create_bucket(**create_kwargs)
        print(f'[s3] 建立新 bucket: {bucket_name}')
    return bucket_name


def build_deployment_zip(tmp_dir: Path) -> Path:
    """把 agent.py 與純 Python 的 boto3/botocore 依賴打包成 .zip。"""
    package_dir = tmp_dir / 'package'
    package_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, '-m', 'pip', 'install', '--quiet', '--target', str(package_dir), 'boto3'],
        check=True,
    )
    (package_dir / 'agent.py').write_bytes(AGENT_SOURCE.read_bytes())
    zip_path = tmp_dir / 'deployment_package.zip'
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for path in package_dir.rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                zf.write(path, path.relative_to(package_dir))
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f'[zip] 打包完成：{zip_path}（{size_mb:.1f} MB）')
    return zip_path


def upload_zip(bucket: str, region: str, zip_path: Path) -> str:
    key = f'{AGENT_NAME}/deployment_package.zip'
    s3 = boto3.client('s3', region_name=region)
    s3.upload_file(str(zip_path), bucket, key)
    print(f'[s3] 已上傳到 s3://{bucket}/{key}')
    return key


def _find_existing_runtime(control) -> dict | None:
    paginator = control.get_paginator('list_agent_runtimes')
    for page in paginator.paginate():
        for runtime in page.get('agentRuntimes', []):
            if runtime.get('agentRuntimeName') == AGENT_NAME:
                return runtime
    return None


def create_or_update_runtime(region: str, role_arn: str, bucket: str, key: str) -> str:
    control = boto3.client('bedrock-agentcore-control', region_name=region)
    artifact = {
        'codeConfiguration': {
            'code': {'s3': {'bucket': bucket, 'prefix': key}},
            'runtime': RUNTIME_PYTHON_VERSION,
            'entryPoint': ['agent.py'],
        }
    }
    existing = _find_existing_runtime(control)
    if existing is None:
        response = control.create_agent_runtime(
            agentRuntimeName=AGENT_NAME,
            agentRuntimeArtifact=artifact,
            roleArn=role_arn,
            networkConfiguration={'networkMode': 'PUBLIC'},
            lifecycleConfiguration={
                'idleRuntimeSessionTimeout': IDLE_SESSION_TIMEOUT_SECONDS,
                'maxLifetime': MAX_LIFETIME_SECONDS,
            },
            description='caseapi demo agent: turns local BM25 evidence into a natural-language answer',
        )
        print(f'[agentcore] 建立新 runtime：{response["agentRuntimeArn"]}')
        return response['agentRuntimeArn']
    response = control.update_agent_runtime(
        agentRuntimeId=existing['agentRuntimeId'],
        agentRuntimeArtifact=artifact,
        roleArn=role_arn,
        networkConfiguration={'networkMode': 'PUBLIC'},
    )
    print(f'[agentcore] 更新既有 runtime：{response["agentRuntimeArn"]}')
    return response['agentRuntimeArn']


def wait_until_ready(region: str, runtime_arn: str) -> None:
    control = boto3.client('bedrock-agentcore-control', region_name=region)
    runtime_id = runtime_arn.rsplit('/', 1)[-1]
    deadline = time.monotonic() + RUNTIME_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        status = control.get_agent_runtime(agentRuntimeId=runtime_id)['status']
        print(f'[agentcore] 狀態：{status}')
        if status == 'READY':
            return
        if status in {'CREATE_FAILED', 'UPDATE_FAILED'}:
            raise SystemExit(f'AgentCore runtime 進入失敗狀態：{status}')
        time.sleep(RUNTIME_READY_POLL_SECONDS)
    raise SystemExit('等待 AgentCore runtime 變成 READY 逾時；用 `agentcore status` 或主控台檢查。')


def smoke_invoke(region: str, runtime_arn: str) -> None:
    import uuid

    client = boto3.client('bedrock-agentcore', region_name=region)
    payload = json.dumps(
        {
            'prompt': '訴願的法定期間是多久？',
            'context': '訴願法第14條：訴願人應自行政處分達到或公告期滿之次日起三十日內提起訴願。',
        }
    ).encode('utf-8')
    response = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        runtimeSessionId=str(uuid.uuid4()) + '-' * 4,  # 至少 33 字元
        payload=payload,
        qualifier='DEFAULT',
    )
    body = json.loads(response['response'].read())
    print(f'[smoke test] 回應：{body}')


def main() -> None:
    account_id, region = _account_and_region()
    print(f'帳號：{account_id}｜區域：{region}')
    role_arn = ensure_execution_role(account_id, region)
    bucket = ensure_bucket(account_id, region)
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = build_deployment_zip(Path(tmp))
        key = upload_zip(bucket, region, zip_path)
    runtime_arn = create_or_update_runtime(region, role_arn, bucket, key)
    wait_until_ready(region, runtime_arn)
    smoke_invoke(region, runtime_arn)
    print()
    print('=== 部署完成 ===')
    print(f'CASEAPI_AGENTCORE_RUNTIME_ARN={runtime_arn}')
    print('把上面這行加進 .env，並設定 CASEAPI_MODEL_PROVIDER=agentcore。')
    print()
    print('清理方式（demo 結束後）：')
    print(f'  aws bedrock-agentcore-control delete-agent-runtime --agent-runtime-id {runtime_arn.rsplit("/", 1)[-1]} --region {region}')
    print(f'  aws iam delete-role-policy --role-name {ROLE_NAME} --policy-name caseapi-agentcore-execution-policy')
    print(f'  aws iam delete-role --role-name {ROLE_NAME}')
    print(f'  aws s3 rm s3://{bucket}/{AGENT_NAME}/ --recursive')


if __name__ == '__main__':
    main()
