"""Migration 執行器。已套用的版本記在 schema_migrations，重跑不會重複套用。"""

import sqlite3
from pathlib import Path

from caseapi.clock import now_iso

MIGRATIONS_DIR = Path(__file__).resolve().parent / 'migrations'

_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
)
"""


def apply_migrations(conn: sqlite3.Connection) -> list[str]:
    """套用尚未執行的 migration，回傳本次新套用的版本。"""
    conn.execute(_VERSION_TABLE)
    applied = {row['version'] for row in conn.execute('SELECT version FROM schema_migrations')}

    newly_applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob('*.sql')):
        version = path.stem
        if version in applied:
            continue
        conn.executescript(path.read_text(encoding='utf-8'))
        conn.execute(
            'INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)',
            (version, now_iso()),
        )
        newly_applied.append(version)
    return newly_applied
