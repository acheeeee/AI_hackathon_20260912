# 案件、AI 協作與修改提案 API 契約

日期：2026-09-12｜v1.0 設計，端點尚未實作

## 1. 共通規約

新 API 基底為 `/api/v1`。下表相對路徑以 `C = /api/v1/cases/{case_id}` 表示；實作不能把字母 C 當實際 URL。舊 `app/api.py` 的 `/api/analyze`／`/api/draft` 不是新契約，前端切換時一併更換 client。

JSON 欄位 `snake_case`；時間使用 UTC RFC 3339，日曆日期使用西元 `YYYY-MM-DD`，前端可轉民國年。未知值為 `null`，不以空字串／0 代替。ID 為 opaque 字串，`case_revision` 為整數。

成功／失敗沿用統一 envelope：`{success, data, error, meta}`。成功的 `error: null`；失敗的 `data: null`。`meta.request_id` 必填；目前案件回應另帶 `meta.case_revision`。HTTP 狀態仍反映錯誤，不以 200 包住所有失敗。

除建立新案件外，會改正式案件狀態的請求必填 `expected_case_revision`；直接修改既有資源另填 `base_resource_revision`。提案採用的各資源基底由 immutable preview 提供，不另重複填寫。AI 請求雖不改正式內容，仍須核對 expected case revision 與 target revision 才凍結輸入。以 payload 做樂觀鎖，v1 不另混用 If-Match。缺版本欄位回 422，版本衝突回 409。

所有產生工作、訊息、提案預覽或正式變更的 POST，以及正式 PATCH，要求 `Idempotency-Key`。同 key 同內容重送回原結果；同 key 不同內容回 `IDEMPOTENCY_KEY_REUSED`。生存期初版至少 7 日，過期策略由部署明示；proposal application 的去重紀錄與歷史同壽命。

身分來自伺服器會話；每個案件、run、proposal、來源都檢查權限與所屬案件。不得接受客戶端指定 actor 來冒充他人。不存在與無權讀取的跨案 ID，對外一致回 404，內部記原因。

## 2. 核心物件

### TargetRef

共同欄位：`kind, resource_id, resource_revision`。case ID 由路由取得並驗證；保存到內部 target 時補上 `case_id`。kind 限 `draft_block/fact_field/gate_result/source_span/annotation/document`。

- draft_block：另帶 `block_id, char_start, char_end, selected_text, selected_text_sha256`；文字位置按 Unicode code point，左含右不含。
- fact_field：另帶 allowlist `field_path`。
- gate_result：另帶 `analysis_id, gate_id, issue_scope_id`（無分項為 null）。
- source_span：另帶前處理定義的 `source_ref`，不能作 replace_text 目標。
- annotation：使用明確註記版本。
- document：指定可編輯工作文件，供完整重生。

`selected_text_sha256` 使用選取原字串 UTF-8 的小寫十六進位 SHA-256，不先正規化。後端從指定版本重建文字並核對，不相信 DOM offset 或前端傳入文字即是原文。

### EvidenceRef

`evidence_id, source_ref, quote, source_exists, quote_matches, support_status, assessed_by, temporal_status, opened_event_id`。source_ref 包含 `kb_release_id` 或本案文件版本、`document_id, extraction_version, source_spans`；每個 span 以 page／line／字元範圍定位。

外部來源另有 `url, retrieved_at, snapshot_id, content_hash`。同一工具搜尋結果與已開啟來源要分開，`opened_event_id` 不能指向 search 事件。無法逐字定位的模型概述放 answer，不放 quote。

### Proposal

`id, case_id, origin, run_id, mode, base_case_revision, target, dependencies, change_groups, state, created_at`。`origin` 為 `ai/reversion`；人工撤回提案的 `run_id` 為 null，另帶 `reverts_mutation_id`，不可偽造 AI 執行紀錄。

- mode：`local/full`。
- dependencies：明列 resource revisions、必要欄位 hash、KB／規則版本；伺服器補足模型漏列的必要依賴。
- change_groups：每組 `id, change_class, operations, depends_on_group_ids, reason, evidence_ids`。
- operations allowlist：`replace_text/replace_fact/add_citation/remove_citation/replace_document`；含 typed target、before value／hash、after value。
- state：`ready/partially_applied/applied/rejected/conflicted/invalidated`。

AI 可提出 human review 的說明草案，但不能用 patch 更新 human_review／workflow_state／audit／role。真正覆核由下表的人工端點處理。

`replace_document` 不可拆組；完整候選的逐組模式由伺服器轉成 `replace_text` 區塊操作，包含明確的 `block_change: update/insert/delete/move` 與順序錨點。`revise_selection` 只允許 update 已選文字；結構操作只限明確授權的全文範圍，模型不能藉此越界。

### Run

`id, case_id, kind, state, base_case_revision, context_manifest, proposal_ids, last_event_sequence, error`。kind 含 `chat/regenerate/analysis`；state 使用 `queued/running/completed/failed/cancelled/needs_input`。run 完成不表示提案已套用。

## 3. 案件與直接編輯端點

| 方法 | 路徑 | 契約重點 |
|---|---|---|
| POST | `/api/v1/cases` | 建立案件；201，回 case ID、revision 與 Location |
| GET | `/api/v1/cases?cursor=...&limit=20` | 僅回授權案件；上限 100，回 `next_cursor` |
| GET | `C` | workflow、active heads、freshness、case revision |
| POST | `C/documents` | multipart 上傳，role=`appeal/disposition/evidence`；202 回抽文工作 ID |
| GET | `C/resources/{resource_id}?revision=...` | 取得草稿／事實等指定版本，省略 revision 取目前 heads |
| PATCH | `C/facts` | typed field_changes、理由、來源／human_asserted 標記；保存＋202 重算 job 或 200 無需重算 |
| PATCH | `C/drafts/{draft_id}` | 人工 block 編輯，版本與引用校驗；200 回新版本、stale 狀態 |
| PATCH | `C/selections` | 依據 ID 清單＋KB 版本；保存新 selections revision |
| POST | `C/annotations` | 建 TargetRef 註記；201，不直接改 case revision |
| PATCH | `C/annotations/{id}` | 依 expected annotation revision 編修／resolve；200 |
| GET | `C/annotations?resource_id=...` | 註記、目前定位及 orphaned 狀態 |
| POST | `C/analyses` | 凍結目前依賴，跑規則／推薦等指定範圍；202 |
| POST | `C/human-reviews` | 款別／範圍、分析版本、outcome、理由、證據；201 並重算分流 |
| POST | `C/drafts/{draft_id}/reviews` | 針對目前依賴保存人工重新覆核；有未完成必要分析仍不可解除 stale |
| POST | `C/submissions` | expected revision＋已確認未決事項；201 建內部送審快照 |
| GET | `C/submissions/{submission_id}` | 固定送審版本與確認紀錄 |
| GET | `C/submissions/{submission_id}/exports/docx` | 匯出該快照，不讀目前工作 heads |
| POST | `C/reversions` | 指定要撤回的 mutation；先回 proposal，經預覽採用，不直接回退所有 heads |
| GET | `C/versions?resource_id=...` | 版本、parent、來源與操作者 |
| GET | `C/audit?cursor=...` | 分頁稽核紀錄 |
| GET | `C/drafts/{draft_id}/exports/docx?revision=...` | 下載指定已保存版本，見 §8 |

新案件建立可以先沒有文件；上傳完成後以 server 核准的 MIME、大小、hash 檢查保存。前端註記中的 PDF／草稿連結由來源 API 解析，不能直接提交任意本機路徑要求伺服器讀取。

## 4. AI 對話與來源端點

| 方法 | 路徑 | 行為 |
|---|---|---|
| POST | `C/chat-threads` | 建同案對話，201 |
| GET | `C/chat-threads/{thread_id}/messages?cursor=...` | 讀歷史訊息與提案狀態 |
| POST | `C/chat-threads/{thread_id}/messages` | 訊息、intent、target、指定註記 ID／revision；202 回 message ID、run ID |
| POST | `C/drafts/{draft_id}/generation-runs` | 完整重生入口；202；內部仍產生同一 Proposal 物件 |
| GET | `C/runs/{run_id}` | 查看結果、狀態、候選 IDs |
| GET | `C/runs/{run_id}/events` | SSE；可依 Last-Event-ID 補送 |
| POST | `C/runs/{run_id}/cancellations` | 取消尚未完成 run；完成的 run 回 409 |
| GET | `C/evidence/{evidence_id}` | 原文引用、版本、檢查結果與受控預覽連結 |
| GET | `C/documents/{document_id}/pages/{page}` | 本案來源頁預覽／行座標；案件權限檢查 |

`needs_input` 的 run 可顯示具體問題；下一次使用者訊息帶 `reply_to_run_id`，建立新 run，不把回答塞進舊的已凍結 context。

### 局部修改請求範例

以下是合成資料的請求形狀；文字 `原句。` 的 hash 與範圍相符，ID 用於 fixture，不代表真實案件。

```json
{
  "expected_case_revision": 42,
  "intent": "revise_selection",
  "content": "把這一句改得更正式，保留原意與引用。",
  "target": {
    "kind": "draft_block",
    "resource_id": "draft_demo",
    "resource_revision": "draft-r7",
    "block_id": "reason-3",
    "char_start": 0,
    "char_end": 3,
    "selected_text": "原句。",
    "selected_text_sha256": "1bddf8c4c811ad4e772d501df041f5e8ccd901bd61a95132acb0fe464f13edab"
  },
  "annotation_refs": []
}
```

```json
{
  "success": true,
  "data": {
    "message_id": "msg_demo_1",
    "run_id": "run_demo_1",
    "state": "queued"
  },
  "error": null,
  "meta": {"request_id": "req_demo_1", "case_revision": 42}
}
```

完整重生請求另帶 `preserve_human_blocks: true/false`、target document 與 expected case revision；不接受「順便重設人工覆核」欄位。

## 5. 修改預覽、合併與採用

| 方法 | 路徑 | 行為 |
|---|---|---|
| GET | `C/proposals/{proposal_id}` | base、candidate、修改組與狀態 |
| POST | `C/proposals/{proposal_id}/merge-previews` | expected current revision、選定組；回三方 diff、衝突與 preview hash |
| POST | `C/proposals/{proposal_id}/merge-previews/{preview_id}/resolutions` | 使用者整合衝突後，建立新 immutable preview；不改舊 preview |
| POST | `C/proposals/{proposal_id}/applications` | preview ID／hash、expected case revision；交易採用 |
| POST | `C/proposals/{proposal_id}/rejections` | 拒絕未採用部分，保留歷史與已採用組 |

merge preview 可在 proposal.base 與 current 不同時建立，但請求中的 expected current 必須與伺服器一致。成功建立含衝突的預覽回 201，`can_apply: false` 並列衝突；輸入已過期回 409。衝突解法不能用 `force: true` 略過驗證。

apply 請求：

```json
{
  "expected_case_revision": 43,
  "preview_id": "preview_demo_2",
  "preview_hash": "fixture-preview-hash",
  "accepted_group_ids": ["group_wording_1"]
}
```

此處 `fixture-preview-hash` 是示意值；實際值由伺服器對預覽固定序列化內容計算 SHA-256，前端原樣回傳。accepted groups 必須與預覽完全一致，不能臨時增刪組。

成功回 200：`mutation_id, applied_group_ids, resulting_case_revision, resource_revisions, invalidated_resources, analysis_job_ids`。第一個成功回應與同 key 重送一致；同 group 新 key 重複採用回 `PROPOSAL_ALREADY_APPLIED`，不再變更內容。

## 6. SSE 事件

事件型別：`run.started/tool.started/tool.completed/tool.failed/source.opened/answer.delta/proposal.ready/run.completed/run.failed/run.cancelled/run.needs_input`。事件 `id` 為該 run 單調遞增整數；data 含 `run_id, sequence, timestamp, payload`。屬文字串流的 answer.delta 不單獨成為正式消息版本。

```text
id: 7
event: source.opened
data: {"run_id":"run_demo_1","sequence":7,"timestamp":"2026-09-12T06:00:00Z","payload":{"tool_call_id":"tool_demo_2","evidence_id":"evidence_demo_1"}}
```

tool 事件由伺服器執行層產生。`run.completed` 包含最終 message／proposal IDs；沒有 proposal.ready 就不能顯示採用鈕。非 SSE client 可輪詢 GET run 及讀事件紀錄；需提供 `?after_sequence=...&format=json` 的事件分頁回應。

串流使用與案件 API 相同會話授權；不把 token 放 URL query。重新連線先驗權限、回補已保存事件，不能因重連再次呼叫模型。已打開的串流出錯透過 run.failed 事件表示，初始連線拒絕仍使用正常 HTTP 錯誤。

## 7. 錯誤契約

| HTTP | code | 前端動作 |
|---|---|---|
| 400 | `MALFORMED_REQUEST` | 修正格式 |
| 401 | `AUTH_REQUIRED` | 重新登入，保留未保存緩衝 |
| 404 | `RESOURCE_NOT_FOUND` | 不顯示跨案資源細節 |
| 409 | `REVISION_CONFLICT` | 取 current、重做 diff；不自動重送覆蓋 |
| 409 | `DEPENDENCY_STALE` | 顯示變動依賴，重算／新 run／人工重驗 |
| 409 | `TARGET_MOVED` | 重新定位，禁止猜測替換 |
| 409 | `WORKFLOW_BLOCKED` | 顯示需覆核項目，仍可聊天／加註 |
| 409 | `IDEMPOTENCY_KEY_REUSED`／`PROPOSAL_ALREADY_APPLIED` | 取得原結果或修正請求 |
| 422 | `INVALID_FIELD`／`OUT_OF_SCOPE_PATCH`／`INVALID_CITATION` | 顯示具體欄位或提案驗證失敗 |
| 429 | `RUN_LIMIT_EXCEEDED` | 依 Retry-After 等待／取消舊工作 |
| 503 | `PROVIDER_UNAVAILABLE`／`DATABASE_BUSY` | 可重試；人工操作按可用能力繼續 |

error 形狀：`{code, message, details, retryable}`。details 僅含使用者可讀的版本、資源與欄位，不含堆疊、SQL、憑證或其他案件內容。

## 8. 匯出、完整性與契約交付

DOCX 匯出指定 resource revision；未保存內容先儲存。過期工作草稿可下載但清楚標工作稿／待重查，不能冒充目前有效送審稿。送審版本以 submission ID 另取固定快照，後續編輯不改其內容。binary 回應不包 JSON envelope。

實作時以共用 Pydantic schema 產出 OpenAPI，再產生／核對 TypeScript 型別。需提供上述合成 fixtures、401／409／422／斷線事件及成功採用的契約測試，不把本 Markdown 當成已產生的 OpenAPI。

版本、依賴與交易細節由 [03](03-後端SQLite與版本合併.md) 定義；AI 行為由 [02](02-AI側邊欄與查證編修.md) 定義。
