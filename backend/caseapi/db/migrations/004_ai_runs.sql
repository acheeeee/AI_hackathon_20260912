-- B1：AI run、持久事件與可恢復工作。
-- run/context 建立後不可換基底；事件按 run 內 sequence append-only。

CREATE TABLE ai_runs (
  id                    TEXT PRIMARY KEY,
  case_id               TEXT NOT NULL REFERENCES cases (id),
  kind                  TEXT NOT NULL CHECK (kind IN ('chat', 'regenerate', 'analysis')),
  state                 TEXT NOT NULL CHECK (
    state IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'needs_input')
  ),
  base_case_revision    INTEGER NOT NULL,
  context_manifest_json TEXT NOT NULL,
  prompt_version        TEXT NOT NULL,
  provider_config_json  TEXT NOT NULL,
  proposal_ids_json     TEXT NOT NULL,
  last_event_sequence   INTEGER NOT NULL DEFAULT 0 CHECK (last_event_sequence >= 0),
  error_json            TEXT,
  lease_until           TEXT,
  created_by            TEXT NOT NULL,
  created_at            TEXT NOT NULL,
  updated_at            TEXT NOT NULL
);

CREATE INDEX idx_ai_runs_case ON ai_runs (case_id, created_at);
CREATE INDEX idx_ai_runs_state_lease ON ai_runs (state, lease_until);

CREATE TABLE jobs (
  id              TEXT PRIMARY KEY,
  case_id         TEXT NOT NULL REFERENCES cases (id),
  run_id          TEXT NOT NULL REFERENCES ai_runs (id),
  kind            TEXT NOT NULL,
  input_refs_json TEXT NOT NULL,
  state           TEXT NOT NULL CHECK (
    state IN ('queued', 'running', 'completed', 'failed', 'cancelled')
  ),
  attempt         INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
  lease_until     TEXT,
  error_json      TEXT,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);

CREATE INDEX idx_jobs_run ON jobs (run_id);
CREATE INDEX idx_jobs_state_lease ON jobs (state, lease_until);

CREATE TABLE run_events (
  run_id      TEXT NOT NULL REFERENCES ai_runs (id),
  sequence    INTEGER NOT NULL CHECK (sequence > 0),
  event_type  TEXT NOT NULL CHECK (event_type IN (
    'run.started',
    'tool.started',
    'tool.completed',
    'tool.failed',
    'source.opened',
    'answer.delta',
    'proposal.ready',
    'run.completed',
    'run.failed',
    'run.cancelled',
    'run.needs_input'
  )),
  tool_call_id TEXT,
  payload_json TEXT NOT NULL,
  created_at   TEXT NOT NULL,
  PRIMARY KEY (run_id, sequence)
);

CREATE INDEX idx_run_events_type ON run_events (run_id, event_type);
