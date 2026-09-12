# QA 報告：r1

發布狀態：**validated**

## 計數

- input_pdf_count: 141
- unique_document_count: 141
- duplicate_count: 0
- page_count: 731
- section_count: 2623
- chunk_count: 3106
- citation_count: 675
- review_queue_count: 7

## 檢查項目

| 檢查 | 結果 | 明細 |
|---|---|---|
| 原件清點-PDF數 | PASS | input=141 baseline=141 |
| 原件清點-頁數 | PASS | unique_pages=731 baseline=731（含重複別名頁見備註） |
| 主鍵唯一-document_id | PASS | n=141 |
| 主鍵唯一-section_id | PASS | n=2623 |
| 主鍵唯一-chunk_id | PASS | n=3106 |
| 外鍵-chunk.section_id | PASS | dangling=0 |
| 外鍵-section.document_id | PASS | dangling=0 |
| span合法性 | PASS | illegal_spans=0 |
| quote可重建 | PASS | mismatch_sections=0 |
| 法條邊界-附加條號存在 | PASS | 附加條號 section 數=238 |
| 法條邊界-條號可解析 | PASS | 無法解析 article_key 的條文 section=0 |
| 全文覆蓋-未歸屬行已記錄 | PASS | uncovered_lines_logged=0（進 review_queue，未靜默掉段） |
| index_eligible-布林 | PASS | non_bool=0 |

## 人工待辦

- 低文字頁：7（須逐頁視覺判定）
- 未歸屬行：0（進 review_queue）

> 解析輸出不等於已核對正確；11 部法規條號、101 件關鍵標籤仍需人工回到 PDF 核對。
