# 後端案件管理、SQLite 與版本合併

日期：2026-09-12｜v1.0 工程方案｜階段 A、B1 run／事件與 B2 evidence 寫入已實作；未完成項見 05 §6

## 1. 架構與責任

以 Python／FastAPI 提供案件 API，SQLite 保存案件狀態、不可變版本、提案、討論與稽核。原始 PDF 及資料團隊的 release 使用檔案保存，資料庫保存受控路徑與 hash。索引可重建，不是案件狀態的唯一來源。

```text
Vue 工作畫面／AI 側邊欄
  → 案件 API（授權、版本、冪等）
    → CaseService：人工編輯、覆核、採用與送審
    → AnalysisService：確定性規則與依賴重算
    → AIOrchestrator：讀取、工具、候選提案
    → EvidenceRepository：已發布語料與來源
    → SQLite＋不可變原件／release
```

沿用舊程式可重用的函式經測試接入；現有 `backend/api.py` 的 `_last` 不進新流程。v1 使用單機服務與可恢復的資料庫工作佇列，不增加外部訊息服務；實際處理速率以測試決定。

## 2. 版本與來源的共同定義

| 名稱 | 意義 | 何時改變 |
|---|---|---|
| `case_revision` | 案件正式工作狀態的單調遞增整數 | 事實、草稿、勾選、有效人工覆核、正式分析／流程頭指標更新 |
| `resource_revision` | 單一資源的不可變版本 ID | 該資源內容變動，例如 `draft-r8` |
| `analysis_id` | 某次分析完整輸入與輸出快照 | 每次規則運算完成產生新 ID |
| `run_id` | 一次 AI／重生工作 | 重試若非冪等重送則新建 |
| `proposal_id` | 未採用的修改候選 | 新候選或重新產生時新建 |
| `kb_release_id/ruleset_version` | 語料與規則的凍結版本 | 明確切換版本時 |

聊天、工具事件、未採用提案與普通註記保存自己的版本，不增加 `case_revision`；將註記採為事實／覆核才增加。run 凍結自己讀取過的註記版本，註記後來改了不會回頭改寫歷史脈絡。

案件的 `case_id` 是系統產生的 opaque ID，不直接拿官方案號作唯一鍵。來源的 `document_id/chunk_id/source_spans` 沿用資料交接契約；工作草稿另有 stable block ID。

## 3. SQLite 最小資料模型

表名與欄位是實作目標，並非現已存在的 migration。

| 表 | 核心欄位／責任 |
|---|---|
| `cases` | `id, owner_id, case_revision, workflow_state, active_heads_json, created_at, updated_at` |
| `case_snapshots` | `case_id, revision, heads_json, parent_revision, mutation_id, actor_id, created_at`；每次正式變更一筆 |
| `resource_versions` | `id, case_id, resource_id, resource_kind, parent_id, content_json, content_hash, origin, dependencies_json`；事實、勾選、草稿、覆核等不可變內容 |
| `case_documents` | `id, case_id, source_file, source_sha256, document_role, extraction_version`；原件與工作副本分開 |
| `analyses` | `id, case_id, input_heads_json, input_hash, ruleset_version, outputs_json, created_at`；結果不可改寫 |
| `annotations` | `id, case_id, target_json, current_revision, status`；每次編修內容存 resource version |
| `chat_threads/messages` | `case_id, thread_id, message_id, role, content, target_json, run_id, created_at`；訊息以新增保存，更正有關聯 |
| `ai_runs` | `id, case_id, state, context_manifest_json, prompt_version, provider_config_json, lease_until, error_code` |
| `jobs` | `id, case_id, run_id, kind, input_refs_json, state, attempt, lease_until`；抽文／規則／AI 工作排程，輸入凍結，重試保留紀錄 |
| `run_events` | `run_id, sequence, event_type, tool_call_id, payload_json, created_at`；序號唯一，用於串流補送 |
| `evidence_records` | `id, case_id, run_id, source_ref_json, quote, quote_hash, verification_json`；B2 只允許 `open_source` 在同一交易與 `source.opened` 一起寫程式驗證值；外部來源另含 URL／快照 |
| `proposals` | `id, case_id, origin, run_id, reverts_mutation_id, base_case_revision, candidate_json, dependency_hash, state`；人工撤回的 run 可為 null |
| `merge_previews` | `id, proposal_id, current_case_revision, selected_groups_json, resolved_candidate_json, preview_hash, conflict_json` |
| `proposal_applications` | `proposal_id, group_id, mutation_id, resulting_revision`；防止同組套用兩次 |
| `submissions` | `id, case_id, case_revision, snapshot_refs_json, actor_id, acknowledged_issues_json, created_at`；不可變內部送審快照 |
| `audit_entries` | `case_id, sequence, mutation_id, actor_id, action, before_refs, after_refs, reason, evidence_refs, prev_hash, entry_hash` |
| `idempotency_records` | `actor_id, case_id, endpoint, key, request_hash, state, stored_response` |

全表主鍵、外鍵與必要唯一鍵寫 migration。跨資源關係同時檢查 `case_id`，不能只驗證 ID 存在。所有 JSON payload 進庫前經 schema 驗證；SQLite 本身不替代應用層資料契約。

`origin` 可為 `extracted/rule/human/ai/merged`，並保存細分來源；使用者手改一個區塊，不得把整份文件都標 AI 生成，也不把已採用 AI 候選的原始 run 丟掉。

## 4. 狀態與過期是不同維度

`workflow_state` 見 [01](01-人工操作與案件流程.md)。分析／草稿另有 `freshness: current/stale/needs_review`。舊內容能看、能比對，但不能因畫面仍看得到就當目前有效。

每個產物保存依賴資源版本或欄位 hash；後端依變更路徑建立失效集合：

| 已保存的變更 | 應更新／標過期 | 不需重跑的項目 |
|---|---|---|
| 日期、送達方式、與規則相關事實 | 依賴該欄位的計算／gate／覆核、分流、依賴結果的草稿 | 不相關法條原文 |
| 案件類型、處分依據、爭點 | 推薦／相似案例、相關分析與草稿 | 未受影響的原件抽文 |
| 勾選依據 | 依據選取相關的草稿與引用檢查 | 已確認事實、無關的期間算式 |
| 純文字潤飾 | 新草稿版本與引用／意義變更檢查 | 事實／期間計算 |
| 普通註記、聊天 | 新註記／訊息版本 | 不直接改有效事實或分流 |
| 切換語料／規則版本 | 明確受影響產物列待重查 | 歷史 run 與已送審快照仍保留原版 |

依賴不足以精確判別時保守標記相關產物 stale，不能假稱「只改文句」來繞過。一般知識庫發布新 release 不自動把所有案件切到新版；案件採用新版才更新 heads 與失效集合，並顯示「本案仍使用舊快照」提示。

人工文字編輯或局部 AI 採用不自動解除既有 stale。只有完成必要重算／證據檢查及針對新依賴的覆核後，才可標 current；可透過 API 保存「已依新事實覆核此草稿」的新版本並附理由，不能單改旗標。

## 5. 直接編輯與規則重算

人工儲存事實時，一個交易內保存新事實版本、更新 case revision、追加稽核、標記依賴失效並建立重算 job。交易完成即回應，畫面立即呈現新值與「分析更新中」。

規則 worker 使用凍結輸入運算；完成後如果依賴仍相同，保存 analysis 並更新 system-result 頭指標與分流。若輸入已變，只保存歷史結果，不回寫目前 heads。模型法律建議不走這條自動確定性結果更新通道。

人工覆核保存單款／爭點範圍、before／after outcome、理由、證據狀態及所依事實／規則版本。系統結果永遠留著。覆核的相關依賴變動時，該覆核不再覆蓋新系統結果，畫面標「需再次確認」。

## 6. 三方 diff 與合併

三方定義：`base` 是 AI 開始工作時的版本，`current` 是現在正式版本，`candidate` 是 AI 提案。diff 是展示，merge 是產生新的候選結果，apply 才是正式保存。

### 6.1 合併規則

1. `base == current`：依 before hash 檢查後可直接預覽 candidate。
2. 文字在不同 stable block 修改且依賴未變：可自動計算合併預覽，保留 current 的其他修改，仍由使用者採用。
3. 同 block 的不重疊字元範圍：只有能用明確位置映射證明無碰撞才自動預覽；v1 可保守視為 conflict。
4. 同範圍／同事實 path 的不同修改、區塊被刪除／移動而不能唯一定位：conflict。
5. 文字雖未變但事實、規則、引用／勾選依賴已變：`dependency_stale`，需新 run 或人工重新驗證，不能只因文字 diff 乾淨就套用。
6. 純 wording 修改若宣告依賴未變且只與無關區塊版本差異，可在新 current 上預覽；不得由模型自行宣稱依賴不重要。

衝突解法保存成新的 `merge_preview`：保留 current、採 candidate、人工整合後文字三選一。人工整合也要經 schema／引用／依賴檢查；改到新事實時另走事實修改，不以文字合併偷偷改計算值。

### 6.2 逐組採用

`change_groups` 是最小採用單元。一組包含互相依賴的文字與引用，可以全選／拒絕；組間有依賴時先檢查依賴閉包。UI 可以顯示逐句 diff，但不能允許只採一句造成必要引用未加入。

採用部分組後記 `partially_applied`，每個已採用 group 記 resulting revision。剩餘組基於新的 current 重做預覽；不要把原始 candidate 改寫成新的 base。全部採用為 `applied`；拒絕未採用部分為 `rejected` 並保留已採用紀錄。

完整文件替換不是特殊的無版本覆寫端點。`replace_document` 是不可拆的單一修改組，不能與同文件的局部操作混用；需要逐組採用時，由伺服器把完整候選轉成互不重疊的區塊操作（增刪／移動需明確 before／after 結構），再經同一驗證流程。完整生成中任何一段未完成／驗證失敗，就不能提供「整份採用」。

## 7. 正式採用的交易邊界

前端先提交 proposal、選定組與 current revision，取得不可變合併預覽；使用者按採用時提供 `preview_id/preview_hash/expected_case_revision` 與冪等鍵。

伺服器在短交易內：

1. 驗權限、預覽所屬案件、提案可採用狀態、尚未套用的 group。
2. 核對 expected revision、before hash、依賴版本、引用與預覽 hash。
3. 保存合併後資源版本與 case snapshot。
4. 以 `WHERE case_revision = expected` 更新案件頭指標，必須恰好更新一筆。
5. 寫 applications、稽核、依賴失效與重算工作。
6. 寫冪等成功回應，提交交易。

任何一步失敗全部 rollback，不能先改草稿再補寫 audit。交易外完成模型生成、遠端檢索與昂貴驗證；交易內只做必要的版本／hash／權限複核，避免等待模型時鎖住 SQLite。

如果回應遺失但交易已提交，同 key 同 request hash 重送回原成功結果，不再套用。相同 key 不同 payload 返回 409。key 由使用者身分、案件與端點共同限定，不能跨案重用舊成功結果。

## 8. SQLite 執行與恢復

SQLite 同一時間只有一個 writer，WAL 可讓讀取與寫入並行；所以本設計採短交易，不以 WAL 當作多人同時無衝突寫入的保證。[SQLite isolation](https://www.sqlite.org/isolation.html)

每個連線明確啟用並檢查 `PRAGMA foreign_keys=ON`；migration 與交易測試驗證跨案／懸空引用會失敗。[SQLite foreign keys](https://www.sqlite.org/foreignkeys.html)

v1 部署在單機本地磁碟，設定有界 busy timeout 與重試；鎖競爭超限回可重試錯誤，不直接丟掉使用者內容。DB 連線不在並發請求間任意共用未完成交易。

ai_runs／jobs 有 claim、lease 與重啟恢復策略：重啟後檢查逾期 running 工作，重算可安全重排；AI 外部呼叫結果不明時標失敗／需重試，不假稱 exactly-once 模型執行。正式 apply 仍由冪等紀錄保證不重複生效。

備份使用一致性備份機制並驗證能還原，備份涵蓋 DB 及其引用的原件／release。運行中的資料庫不只隨意複製單個 `.db` 檔。[SQLite backup API](https://www.sqlite.org/backup.html)

資料庫含案件、對話與人工身分，不進 Git。可提交的是 migrations、schema、合成 fixtures；原始憑證不寫 DB／log。角色由伺服器會話判定，客戶端送來的 `actor_id` 不作權限依據。

## 9. 歷史、撤回與內部送審

撤回修改是建立新的補償版本，不刪除已採用歷史。舊版本恢復也要對目前依賴重新驗證；有後續修改時先給 diff，不直接倒退指標吞掉他人變更。

v1 提案撤回限 allowlist 可表達的事實、草稿與引用修改；人工覆核、勾選或其他狀態須走對應人工端點建立新紀錄，不擴大 AI patch 權限。不支援的撤回回 422 並指明替代操作；已送審快照不刪除。

送審生成不可變 submission snapshot，固定事實、有效分析／人工覆核、草稿、勾選與引用版本。送審後再編輯，建立新工作版本並標需重新送審；原送審快照仍可查，不暗中更新。與外部公文／簽核系統的正式連接不在本次實作契約內。

稽核採 append-only 資料模型與每案 hash chain；chain 可偵測未同步重算雜湊的內容更動，但具有整庫寫權的人仍可能重寫全鏈。沒有外部可信錨定前，不宣稱絕對防竄改。v1 優先確保交易完整、版本可追溯及可恢復。

## 10. 後端驗收

測試兩案交錯、兩分頁同改、提案與事實並行更新、交易中斷、回應遺失後重送、工作重啟、過期覆核、整份重生保留人工稿、逐組採用與撤回。每項均檢查 DB 狀態、case revision、audit 與 UI 回應一致。

資料傳輸與錯誤物件見 [04](04-API契約.md)；所有實作結果記在 [05](05-實作順序與驗收.md)。
