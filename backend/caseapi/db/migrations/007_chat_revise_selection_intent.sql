-- 7.3b：新增 revise_selection（選取局部修改）intent。
-- SQLite 不能直接改 CHECK constraint，用「建新表、搬資料、砍舊表、改名」
-- 的標準手法重建 messages，把允許的 intent 從 ('explain', 'verify')
-- 加上 'revise_selection'。

CREATE TABLE messages_new (
  id          TEXT PRIMARY KEY,
  case_id     TEXT NOT NULL REFERENCES cases (id),
  thread_id   TEXT NOT NULL REFERENCES chat_threads (id),
  role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content     TEXT NOT NULL,
  intent      TEXT CHECK (intent IN ('explain', 'verify', 'revise_selection')),
  target_json TEXT,
  run_id      TEXT REFERENCES ai_runs (id),
  created_at  TEXT NOT NULL
);

INSERT INTO messages_new
  SELECT id, case_id, thread_id, role, content, intent, target_json, run_id, created_at
  FROM messages;

DROP TABLE messages;
ALTER TABLE messages_new RENAME TO messages;

CREATE INDEX idx_messages_thread ON messages (thread_id, created_at);
CREATE INDEX idx_messages_run ON messages (run_id);
