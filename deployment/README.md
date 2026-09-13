# AWS 競賽 Demo 部署

這個目錄把目前 repo 部署成單機、單操作員的 AWS Demo：

- Region：Oregon（`us-west-2`）
- 一台 `t3.medium` EC2、Elastic IP、Docker Compose
- Nginx 對外提供 Vue，並分流 `/api/v1/*` 與舊 `/api/*`
- `caseapi` 與 legacy API 都固定一個 worker
- r3 BM25 語料包在後端 image；SQLite 與上傳 PDF 放在 Docker volume
- `caseapi` 透過 EC2 instance role 呼叫既有 Bedrock AgentCore Runtime
- Images 固定建成 `linux/amd64`，對應 `t3.medium` 的 x86_64 架構
- 不開 SSH；維運走 SSM Session Manager
- TCP/80 只允許大會提供的四個 `/32` IPv4

這是無網域、無 HTTPS、無正式登入的 mock-data Demo，不是正式環境。主辦方電腦的
實際對外 IPv4 必須是 allowlist 其中之一，否則連線會被 Security Group 擋下。

## 目錄

```text
deployment/
├── aws/cloudformation.yaml       # VPC、EC2、EIP、SG、ECR、S3、IAM
├── compose.yaml                  # web、caseapi、legacy-api
├── config.example               # EC2 設定範本；不含 access key
├── docker/                       # 前後端 image
├── nginx/nginx.conf              # SPA 與兩套 API 反向代理
└── scripts/                      # build、publish、backup、deploy、smoke
```

## 1. 本機驗證 image

正式 release 必須從乾淨且已提交的工作樹建置：

```bash
deployment/scripts/build-images.sh demo-v0.1.0
```

前端目前既有的 oxlint plugin peer 版本不一致，乾淨 `npm ci` 會拒絕安裝；Dockerfile
明確使用 lockfile 加 `--legacy-peer-deps` 進行 production build，不修改 Claude Code
正在使用的 `package.json`／`package-lock.json`。這只處理建置工具的 peer 檢查，正式
bundle 仍會執行專案原本的 type check 與 Vite build。

目前若只是檢查尚未提交的協作結果，可以明確標成 dirty build；這種 image 不得推到
ECR 當正式 Demo release：

```bash
ALLOW_DIRTY_BUILD=1 deployment/scripts/build-images.sh local-check
COMPOSE_PROJECT_NAME=ai-hackathon-local-check \
BACKEND_IMAGE=ai-hackathon-backend:local-check \
FRONTEND_IMAGE=ai-hackathon-frontend:local-check \
CASEAPI_MODEL_PROVIDER=fixed \
WEB_PORT=18080 \
  docker compose -f deployment/compose.yaml up -d --no-build --wait
BASE_URL=http://127.0.0.1:18080 deployment/scripts/smoke.sh
COMPOSE_PROJECT_NAME=ai-hackathon-local-check WEB_PORT=18080 \
  docker compose -f deployment/compose.yaml down
```

不要加 `-v`；`down -v` 會刪掉 SQLite volume。

## 2. 建立 AWS 基礎設施

AgentCore Runtime 維持獨立生命週期，不由這份 stack 重建。先複製參數檔並填入已存在
的 Runtime ARN：

```bash
cp deployment/aws/parameters.example.json /tmp/ai-hackathon-parameters.json
# 編輯 /tmp/ai-hackathon-parameters.json，替換 ACCOUNT_ID 與 RUNTIME_ID
aws cloudformation deploy \
  --region us-west-2 \
  --stack-name ai-hackathon-demo \
  --template-file deployment/aws/cloudformation.yaml \
  --parameter-overrides file:///tmp/ai-hackathon-parameters.json \
  --capabilities CAPABILITY_IAM
```

Stack 會建立：

- 專用 VPC／public subnet／Internet Gateway
- 僅允許四個指定 IP 連 TCP/80 的 Security Group
- 不開 22 的 EC2 與 Elastic IP
- 使用 IMDSv2 的 instance role：SSM、ECR read、指定 AgentCore Runtime invoke、
  deployment bundle S3 read
- 兩個 ECR repository，immutable tag、push scan、只保留最新十版
- 私有、加密、版本化的 deployment bundle S3 bucket

查詢輸出：

```bash
aws cloudformation describe-stacks \
  --region us-west-2 \
  --stack-name ai-hackathon-demo \
  --query 'Stacks[0].Outputs' \
  --output table
```

## 3. 推送 v0.1 images 與 deployment bundle

先完成乾淨工作樹的 build，再推 ECR。ECR repository 由 stack 建立；相同版本不能覆寫：

```bash
deployment/scripts/build-images.sh demo-v0.1.0
AWS_DEFAULT_REGION=us-west-2 \
  deployment/scripts/publish-images.sh demo-v0.1.0
```

將 `publish-images.sh` 印出的兩個 image URI 填入 `deployment/config.example` 的副本，
不要改範本本身。再把不含 secret 的執行檔上傳至 stack 輸出的 bucket：

```bash
deployment/scripts/publish-bundle.sh DEPLOYMENT_BUCKET_NAME demo-v0.1.0
```

## 4. 在 EC2 啟動

用 stack 輸出的 `SsmSessionCommand` 進入主機，不需要 SSH key：

```bash
sudo -iu ec2-user
mkdir -p /opt/ai-hackathon/deployment
aws s3 cp \
  s3://DEPLOYMENT_BUCKET_NAME/releases/demo-v0.1.0/deployment.tar.gz \
  /tmp/deployment.tar.gz
tar -xzf /tmp/deployment.tar.gz -C /opt/ai-hackathon/deployment
cd /opt/ai-hackathon/deployment
cp config.example .env
# 編輯 .env：填入兩個 ECR image URI 與 AgentCore Runtime ARN
scripts/deploy.sh
```

`.env` 不得放 `AWS_ACCESS_KEY_ID`、`AWS_SECRET_ACCESS_KEY` 或
`AWS_SESSION_TOKEN`；`deploy.sh` 發現這些欄位會拒絕執行。

成功後，從四個允許 IP 的其中一台電腦開 stack 輸出的 `WebUrl`。同一台機器也要實測：

1. 上傳 mock PDF。
2. 走到法規選取、AgentCore 回答、草稿生成。
3. 重新整理，確認案件與草稿仍存在。
4. 檢查瀏覽器 console 沒有 error。

## 5. 更新到 v0.2

每次更新都使用新 tag，不覆寫舊 image：

```bash
deployment/scripts/build-images.sh demo-v0.2.0
deployment/scripts/publish-images.sh demo-v0.2.0
```

在 EC2 的 `.env` 把兩個 image URI 改成 `demo-v0.2.0`，再執行：

```bash
scripts/deploy.sh
```

`deploy.sh` 會先用 SQLite online backup 建立一致備份，再 pull、重啟與 smoke test。更新期間
會短暫中斷；請在上台前完成，不做多機 blue/green。

如果新版本失敗，把 `.env` 的兩個 image URI 改回上一版後再執行 `scripts/deploy.sh`。
若新版包含不可逆資料庫 migration，單純切回舊 image 不夠，還要先還原更新前的 SQLite
備份。mock Demo 可以選擇重建資料，但不能假裝 image rollback 等於 database rollback。

## 6. AgentCore 更新與離線備援

AgentCore 程式不包在 EC2 image。修改 `backend/agentcore_app/agent.py` 後，依
`docs/協作設計/07-AgentCore部署與線上模型.md` 重跑：

```bash
cd backend
set -a && source ../.env && set +a
.venv/bin/python scripts/deploy_agentcore.py
```

EC2 只需要 `bedrock-agentcore:InvokeAgentRuntime`，IAM policy 限定到設定的 Runtime ARN。
若比賽當天 AgentCore 暫時無法使用，可把 EC2 `.env` 改成
`CASEAPI_MODEL_PROVIDER=fixed` 再執行 `scripts/deploy.sh`。這是明確的離線備援；展示時不得
把 fixed provider 說成 AgentCore 成功呼叫。

## 7. 安全與已知限制

- 無 domain／TLS，僅適用指定來源 IP、mock PDF、短期展示。
- 沒有正式登入；server 固定單一 `actor_demo`，不能開放給一般網路。
- legacy API 有 process-global `_last`，所以固定一個 worker、一次只操作一案。
- API container 不對 host publish 8000／8001；外部只能經過 Nginx 的 port 80。
- Nginx 限制單檔請求 25 MB；caseapi 另外限制每份 PDF 20 MB。
- SQLite volume 位於 EC2 root EBS，container 更新與 instance stop/start 不會清掉；但
  termination／instance replacement 會刪除 root EBS。重大更新前仍應做 EBS snapshot。
- Docker log 有 10 MB × 3 檔輪替；不要在應用 log 寫入 PDF 內容或憑證。
- 實際 AWS 建立、ECR push、AgentCore invoke 與大會 IP 外部連線都必須另外留下實跑證據；
  本文件與 template 本身不等於已部署。

## 8. Demo 後清理

CloudFormation stack 不管理既有 AgentCore Runtime；先確認它是否仍有其他用途，再依
`docs/協作設計/07-AgentCore部署與線上模型.md` 決定是否刪除。這份 stack 可用下列指令
移除 EC2、Elastic IP、root EBS、VPC 與 ECR images：

```bash
aws cloudformation delete-stack \
  --region us-west-2 \
  --stack-name ai-hackathon-demo
```

Deployment bundle 的 S3 bucket 刻意保留，bundle 版本會在 14 天後自動到期。若確定不再
需要，先清空 bucket，再手動刪除，避免留下持續計費的資源。
