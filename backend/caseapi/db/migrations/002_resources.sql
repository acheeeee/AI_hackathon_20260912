-- A2：不可變資源版本與註記。
-- 內容一律新增版本，不原地修改；freshness 屬於「目前指標」而非版本內容，
-- 所以存在 cases.active_heads_json，不存在這張表。

CREATE TABLE resource_versions (
  id                TEXT PRIMARY KEY,
  case_id           TEXT NOT NULL REFERENCES cases (id),
  resource_id       TEXT NOT NULL,
  resource_kind     TEXT NOT NULL,
  parent_id         TEXT REFERENCES resource_versions (id),
  content_json      TEXT NOT NULL,
  content_hash      TEXT NOT NULL,
  origin            TEXT NOT NULL,
  dependencies_json TEXT NOT NULL,
  created_by        TEXT NOT NULL,
  created_at        TEXT NOT NULL
);

CREATE INDEX idx_resource_versions_case_resource
  ON resource_versions (case_id, resource_id);

-- 註記本身的狀態在這張表；每次編修的內容存成 resource_versions 的一個版本。
CREATE TABLE annotations (
  id                  TEXT PRIMARY KEY,
  case_id             TEXT NOT NULL REFERENCES cases (id),
  target_json         TEXT NOT NULL,
  status              TEXT NOT NULL,
  current_revision_id TEXT NOT NULL REFERENCES resource_versions (id),
  created_by          TEXT NOT NULL,
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL
);

CREATE INDEX idx_annotations_case ON annotations (case_id);
