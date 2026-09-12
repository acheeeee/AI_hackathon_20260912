-- A1 地基：案件、案件快照、稽核鏈、冪等紀錄。
-- 事實／草稿版本在 A2、提案與合併在 A3 才加表，不預先建立用不到的結構。

CREATE TABLE cases (
  id               TEXT PRIMARY KEY,
  owner_id         TEXT NOT NULL,
  case_revision    INTEGER NOT NULL,
  workflow_state   TEXT NOT NULL,
  active_heads_json TEXT NOT NULL,
  title            TEXT,
  official_case_no TEXT,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL
);

CREATE INDEX idx_cases_owner ON cases (owner_id);

-- 每次正式變更一筆；parent_revision 讓版本鏈可回溯。
CREATE TABLE case_snapshots (
  case_id         TEXT NOT NULL REFERENCES cases (id),
  revision        INTEGER NOT NULL,
  heads_json      TEXT NOT NULL,
  parent_revision INTEGER,
  mutation_id     TEXT NOT NULL,
  actor_id        TEXT NOT NULL,
  created_at      TEXT NOT NULL,
  PRIMARY KEY (case_id, revision)
);

-- append-only；prev_hash 串成每案一條 hash chain。
CREATE TABLE audit_entries (
  case_id           TEXT NOT NULL REFERENCES cases (id),
  sequence          INTEGER NOT NULL,
  mutation_id       TEXT,
  actor_id          TEXT NOT NULL,
  action            TEXT NOT NULL,
  before_refs_json  TEXT,
  after_refs_json   TEXT,
  reason            TEXT,
  evidence_refs_json TEXT,
  prev_hash         TEXT,
  entry_hash        TEXT NOT NULL,
  created_at        TEXT NOT NULL,
  PRIMARY KEY (case_id, sequence)
);

-- key 由 actor、案件範圍與端點共同限定，不能跨案重用舊的成功結果。
CREATE TABLE idempotency_records (
  actor_id      TEXT NOT NULL,
  case_scope    TEXT NOT NULL,
  endpoint      TEXT NOT NULL,
  key           TEXT NOT NULL,
  request_hash  TEXT NOT NULL,
  status_code   INTEGER NOT NULL,
  response_json TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  PRIMARY KEY (actor_id, case_scope, endpoint, key)
);
