"""SQLite 連線與交易。

設計 03 §8：每個連線都要確認 foreign_keys 有開；WAL 只讓讀寫並行，
不是多人同時寫入的保證，所以交易一律短。
"""

import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

BUSY_TIMEOUT_MS = 5000


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA journal_mode = WAL')
    conn.execute(f'PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}')
    if conn.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
        conn.close()
        raise RuntimeError('SQLite 沒有啟用 foreign_keys，拒絕在無外鍵保護下運作')
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """短交易。任何一步失敗就整筆 rollback，不允許只寫一半。"""
    conn.execute('BEGIN IMMEDIATE')
    try:
        yield conn
    except BaseException:
        conn.execute('ROLLBACK')
        raise
    conn.execute('COMMIT')
