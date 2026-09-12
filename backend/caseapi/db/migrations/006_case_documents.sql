-- 上傳建案：保存原始 PDF 位元組與抽取快取，供「原檔展開」與規則式抽欄位使用。
-- 原件與工作副本分開（見設計 03）：這張表只存原始上傳檔案，不存編輯結果；
-- 抽取出的事實欄位另外寫進 resource_versions（facts 資源），不在這裡。

CREATE TABLE case_documents (
  id                TEXT PRIMARY KEY,
  case_id           TEXT NOT NULL REFERENCES cases (id),
  document_role     TEXT NOT NULL,
  source_filename   TEXT NOT NULL,
  source_sha256     TEXT NOT NULL,
  content_blob      BLOB NOT NULL,
  extracted_text    TEXT,
  page_count        INTEGER,
  created_by        TEXT NOT NULL,
  created_at        TEXT NOT NULL,
  CHECK (document_role IN ('appeal', 'disposition'))
);

CREATE INDEX idx_case_documents_case ON case_documents (case_id);
