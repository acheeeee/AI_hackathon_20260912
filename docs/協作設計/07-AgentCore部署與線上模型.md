# AgentCore 部署與線上模型

日期：2026-09-13｜狀態：已部署一個可用的 demo runtime，並用真實請求跑通全鏈路

## 1. 架構決定：AgentCore 只做「把答案寫出來」

檢索、開啟原文、驗證 quote 這幾件事**完全留在本機**，走既有的 `EvidenceToolAdapter`
與 r3 `EvidenceRepository`（[06 §3 規則 14](06-交接與下一步.md)）；`caseapi/ai/agentcore_provider.py`
的 `AgentCoreModelProvider` 只在 `search_knowledge`／`open_source`／
`read_selection_context` 已經回傳「已驗證過的內容」之後，才把這段內容當
`context` 送進部署在 AWS 上的代理，請它組成一段自然語言回答。

這樣做的原因：

- 案件資料庫、案件隔離、evidence 原子寫入這些邊界都是本機交易保護的
  （[06 §3](06-交接與下一步.md) 規則 1–14）；把它們搬到雲端等於要幫 AgentCore
  開一條能連回本機 SQLite 的通道，risk 和工程量都不成比例。
- 使用者要求 AWS 後台看得到 AgentCore 真的被呼叫，不是只呼叫 Bedrock 模型
  端點；這個切法讓 AgentCore Runtime 的 invocation 紀錄是真的，同時不用把
  证据邊界搬上雲。
- `ModelProvider`／`ToolGatewayLike` 這兩個既有介面完全夠用，`AgentCoreModelProvider`
  與 `FixedModelProvider` 是同一組單元測試風格可以覆蓋的兩個實作
  （見 `tests/test_agentcore_provider.py`），不需要為了線上模型改動
  `ai/runner.py` 或任何路由。

## 2. 已部署的資源（2026-09-13，us-west-2，帳號 056244671443）

由 `backend/scripts/deploy_agentcore.py` 建立，全部可重跑（role／bucket 已存在會重用，
runtime 已存在會呼叫 `update_agent_runtime`）：

| 資源 | 名稱／ARN |
|---|---|
| IAM 執行角色 | `caseapi-agentcore-execution-role` |
| S3 bucket（direct code deploy 用） | `bedrock-agentcore-code-056244671443-us-west-2` |
| AgentCore Runtime | `caseapi_demo_agent`（`arn:aws:bedrock-agentcore:us-west-2:056244671443:runtime/caseapi_demo_agent-U5MbLcD6hz`） |

部署當下用 smoke test 實際呼叫過一次，答案正確；另外用完整 FastAPI 應用（`CASEAPI_MODEL_PROVIDER=agentcore`）跑過一次 `verify` intent 的端到端請求，run 狀態 `completed`，事件序列為
`run.started → tool.started → tool.completed → tool.started → source.opened → tool.completed → answer.delta → run.completed`，
assistant 訊息內容來自 AgentCore 的真實回覆，不是任何 fixture。

`.env` 已加入（未進 Git，屬本機設定）：

```bash
CASEAPI_AGENTCORE_RUNTIME_ARN=arn:aws:bedrock-agentcore:us-west-2:056244671443:runtime/caseapi_demo_agent-U5MbLcD6hz
CASEAPI_MODEL_PROVIDER=agentcore
```

## 3. 部署的代理長什麼樣子

`backend/agentcore_app/agent.py` 是**唯一**被打包上傳的檔案，加上 boto3／botocore
及其純 Python 依賴（無編譯過的擴充套件，打包後約 16 MB，遠低於 direct code
deploy 的 250 MB 上限）。刻意不用 `bedrock_agentcore` SDK 的 `BedrockAgentCoreApp`：
那個套件依賴 pydantic-core／uvicorn／websockets，這些都需要編譯，要打包成
AgentCore 要求的 arm64 執行環境得處理跨平台 wheel，對一個只需要「收 JSON、
呼叫一次 Bedrock、回 JSON」的代理不划算。改用標準函式庫的 `http.server`
直接實作 [HTTP 契約](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html) 要求的兩個路徑：

- `GET /ping` → `{"status": "Healthy"}`
- `POST /invocations`：收 `{"prompt": ..., "context": ...}`，呼叫 Bedrock
  `converse` API（預設模型 `us.anthropic.claude-haiku-4-5-20251001-v1:0`，
  這是**推論設定檔（inference profile）ID**，不是裸模型 ID——直接傳裸模型
  ID 會被 Bedrock 拒絕並要求改用推論設定檔，這是這次部署踩到的第一個坑），
  system prompt 明確要求「只能依據 context 作答，answer 不足就明說，不要
  編造」，回 `{"response": "...", "status": "success"}`。

## 4. 怎麼重新部署／改代理程式碼

```bash
cd backend
set -a && source ../.env && set +a   # 需要有效的 AWS_* 憑證（STS session token 會過期）
.venv/bin/python scripts/deploy_agentcore.py
```

改了 `agentcore_app/agent.py` 之後重跑同一支腳本即可；它會偵測 runtime 已存在
並呼叫 `update_agent_runtime`，不會建出第二個 runtime。腳本本身有清楚的
逐步印出訊息，出錯會停在該步驟，不會半途留下不完整的資源後繼續往下跑。

## 5. 怎麼切換 provider

`caseapi/config.py` 的 `CASEAPI_MODEL_PROVIDER` 決定 `caseapi/main.py`
的 `_build_model_provider` 組出哪個 `ModelProvider`：

- 未設定或設 `fixed`（預設）：`FixedModelProvider`，無網路、無憑證需求，
  斷網或 AWS 憑證過期時 demo 仍能完整跑完。
- 設 `agentcore`：`AgentCoreModelProvider`，需要同時設定
  `CASEAPI_AGENTCORE_RUNTIME_ARN`；沒設就在 `create_app()` 當場丟
  `ValueError`，不會靜靜地退回固定模型讓人誤以為在用線上模型。
  `CASEAPI_AGENTCORE_REGION` 沒設時退回 `AWS_DEFAULT_REGION`，兩者都沒有
  才用寫死的 `us-west-2`。

## 6. 護欄與範圍邊界

- **逾時**：`AgentCoreModelProvider` 建立 boto3 client 時設定
  `connect_timeout=5s`、`read_timeout=30s`（`botocore.config.Config`），
  一次卡住的呼叫不會無限期占住背景工作。
- **工具呼叫次數**：沒有額外的預算計數器。`verify`／`explain` 兩個 intent
  各自最多呼叫兩個工具（search+open，或 read_selection_context 一次），
  邊界由程式結構天生限制住，不是靠執行期計數器，符合「demo 導向、不要
  過度工程」的專案硬規則。
- **run 取消的競態不需要 provider 自己再處理一次**。原本規劃是讓
  provider 在每輪工具呼叫之間檢查 run 是否已被取消，但那需要 provider
  拿到 DB 連線或案件 repository，直接違反 [06 §3 規則 15](06-交接與下一步.md)
  的邊界。重新檢視後決定不做：[B3 收尾的 `fail_run` 修正](06-交接與下一步.md)
  已經保證不管 provider 什麼時候把結果寫回，run 的最終狀態都正確、不會
  留下多餘的 proposal 或訊息，這個正確性保證與 provider 是 fixed 還是
  agentcore 無關。
- **成本**：AgentCore Runtime 是用量計費（vCPU-hour／GB-hour，無固定費用），
  `lifecycleConfiguration` 設定 `idleRuntimeSessionTimeout=300`、
  `maxLifetime=1800`，閒置或超過 30 分鐘的 session 會自動回收。
- **不做真串流**。這點與 [06 §4](06-交接與下一步.md) 提到的 SSE 限制一致：
  `/invocations` 回應是一次性 JSON，不是 SSE；前端要呈現「思考中→查詢中→
  完成」的漸進效果，用假的時間軸配合已存的 run 事件即可，不必等後端真的
  串流。

## 7. Demo 結束後的清理

`deploy_agentcore.py` 執行完會印出對應的清理指令；也可以手動執行：

```bash
aws bedrock-agentcore-control delete-agent-runtime \
  --agent-runtime-id caseapi_demo_agent-U5MbLcD6hz --region us-west-2
aws iam delete-role-policy --role-name caseapi-agentcore-execution-role \
  --policy-name caseapi-agentcore-execution-policy
aws iam delete-role --role-name caseapi-agentcore-execution-role
aws s3 rm s3://bedrock-agentcore-code-056244671443-us-west-2/caseapi_demo_agent/ --recursive
```

## 8. 部署過程中的兩個坑（留給下一次重部署或換帳號時參考）

1. **`iam:simulate-principal-policy` 對這個服務回報不可信。** 部署前用它
   模擬 `bedrock-agentcore-control:CreateAgentRuntime`，回報 `implicitDeny`，
   即使角色掛的是 `AdministratorAccess`。實際呼叫 `create_agent_runtime`
   卻直接成功。判斷是 IAM 模擬器對這個較新服務的動作目錄還不完整，不是
   真的權限不足。**遇到同樣情況時，不要只憑 simulate 的結果判斷卡關，
   要嘛直接嘗試唯讀操作（如 `list_agent_runtimes`）確認能不能連上服務，
   要嘛就直接做一次小規模的真實呼叫。**
2. **裸模型 ID 在這個帳號／region 不能直接用於 `converse`。** 較新的
   Claude 模型（Haiku 4.5 等）需要透過**推論設定檔**呼叫，也就是要加
   `us.` 或 `global.` 前綴的那個 ID（用
   `aws bedrock list-inference-profiles` 查），不是 `list-foundation-models`
   回傳的裸 `modelId`。混用會得到
   `ValidationException: ... isn't supported. Retry your request with the ID or ARN of an inference profile`。
