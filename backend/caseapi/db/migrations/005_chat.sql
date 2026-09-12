-- B3：案件內對話與不可變訊息。訊息只新增；AI 回覆必須連回產生它的 run。

CREATE TABLE chat_threads (
  id         TEXT PRIMARY KEY,
  case_id    TEXT NOT NULL REFERENCES cases (id),
  title      TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX idx_chat_threads_case ON chat_threads (case_id, created_at);

CREATE TABLE messages (
  id          TEXT PRIMARY KEY,
  case_id     TEXT NOT NULL REFERENCES cases (id),
  thread_id   TEXT NOT NULL REFERENCES chat_threads (id),
  role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content     TEXT NOT NULL,
  intent      TEXT CHECK (intent IN ('explain', 'verify')),
  target_json TEXT,
  run_id      TEXT REFERENCES ai_runs (id),
  created_at  TEXT NOT NULL
);

CREATE INDEX idx_messages_thread ON messages (thread_id, created_at);
CREATE INDEX idx_messages_run ON messages (run_id);
