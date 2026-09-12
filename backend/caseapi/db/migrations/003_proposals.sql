-- A3：修改提案、合併預覽、逐組採用紀錄與來源引用。
-- 提案未採用前不碰任何正式內容；合併預覽是不可變的，解衝突會產生新的一筆。

CREATE TABLE evidence_records (
  id                TEXT PRIMARY KEY,
  case_id           TEXT NOT NULL REFERENCES cases (id),
  run_id            TEXT,
  source_ref_json   TEXT NOT NULL,
  quote             TEXT,
  quote_hash        TEXT,
  verification_json TEXT NOT NULL,
  created_at        TEXT NOT NULL
);

CREATE INDEX idx_evidence_case ON evidence_records (case_id);

CREATE TABLE proposals (
  id                  TEXT PRIMARY KEY,
  case_id             TEXT NOT NULL REFERENCES cases (id),
  origin              TEXT NOT NULL,
  run_id              TEXT,
  reverts_mutation_id TEXT,
  mode                TEXT NOT NULL,
  base_case_revision  INTEGER NOT NULL,
  target_json         TEXT NOT NULL,
  dependencies_json   TEXT NOT NULL,
  candidate_json      TEXT NOT NULL,
  dependency_hash     TEXT NOT NULL,
  state               TEXT NOT NULL,
  created_by          TEXT NOT NULL,
  created_at          TEXT NOT NULL
);

CREATE INDEX idx_proposals_case ON proposals (case_id);

CREATE TABLE merge_previews (
  id                      TEXT PRIMARY KEY,
  proposal_id             TEXT NOT NULL REFERENCES proposals (id),
  case_id                 TEXT NOT NULL REFERENCES cases (id),
  parent_preview_id       TEXT REFERENCES merge_previews (id),
  current_case_revision   INTEGER NOT NULL,
  selected_groups_json    TEXT NOT NULL,
  resolved_candidate_json TEXT NOT NULL,
  preview_hash            TEXT NOT NULL,
  conflict_json           TEXT NOT NULL,
  created_at              TEXT NOT NULL
);

CREATE INDEX idx_merge_previews_proposal ON merge_previews (proposal_id);

-- 同一組不能套用兩次：主鍵就是保證。
CREATE TABLE proposal_applications (
  proposal_id        TEXT NOT NULL REFERENCES proposals (id),
  group_id           TEXT NOT NULL,
  mutation_id        TEXT NOT NULL,
  resulting_revision INTEGER NOT NULL,
  created_at         TEXT NOT NULL,
  PRIMARY KEY (proposal_id, group_id)
);
