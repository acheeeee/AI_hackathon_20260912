# QA 報告：r3

發布狀態：**validated**

## 計數

- input_pdf_count: 141
- excluded_non_corpus_count: 12
- unique_document_count: 141
- duplicate_count: 0
- page_count: 731
- section_count: 2627
- chunk_count: 3103
- index_eligible_chunk_count: 3002
- non_index_eligible_chunk_count: 101
- citation_count: 675
- citation_resolved_count: 588
- case_family_count: 101
- review_queue_count: 7

## 檢查項目

| 檢查 | 結果 | 明細 |
|---|---|---|
| 原件清點-PDF數 | PASS | input=141 baseline=141 |
| 原件清點-頁數 | PASS | unique_pages=731 baseline=731（含重複別名頁見備註） |
| 主鍵唯一-document_id | PASS | n=141 |
| 主鍵唯一-section_id | PASS | n=2627 |
| 主鍵唯一-chunk_id | PASS | n=3103 |
| 外鍵-chunk.section_id | PASS | dangling=0 |
| 外鍵-section.document_id | PASS | dangling=0 |
| span合法性/quote可重建-sections | PASS | mismatch_sections=0 |
| span合法性/quote可重建-chunks（全量） | PASS | mismatch_chunks=0/3103 |
| 法條邊界-附加條號存在 | PASS | 附加條號 section 數=238 |
| 法條邊界-條號可解析 | PASS | 無法解析 article_key 的條文 section=0 |
| 法條邊界-無空內容條文 | PASS | 空內容 statute_article=0（曾因分頁小工具假標題產生，見 segment.segment_statute） |
| 全文覆蓋-未歸屬行已記錄 | PASS | uncovered_lines_logged=0（進 review_queue，未靜默掉段） |
| index_eligible-布林 | PASS | non_bool=0 |
| chunk契約-chunking_version齊全 | PASS | missing=0/3103 |

## 人工待辦

- 低文字頁：7（須逐頁視覺判定）
- 未歸屬行：0（進 review_queue）
- 分頁小工具造成無法逐條切分：0 部法規（見 review_queue issue_type=toc_widget_merged_articles，內容未遺失但條號粒度不足）

> 解析輸出不等於已核對正確；11 部法規條號、101 件關鍵標籤（案件類型／主文結果為規則式，review_status=unreviewed）仍需人工回到 PDF 核對，才能作為 gold 或硬過濾條件。
> 引用解析僅對照本 release 內的法規條文；庫外來源、判解／函釋間引用一律 unresolved，不代表資料錯誤。
