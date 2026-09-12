"""FastAPI 依賴：連線、身分與冪等鍵。

身分只從伺服器設定取得。契約 §1 規定不得接受客戶端指定 actor；v1 是單人
demo，換成真正的登入時只要改這裡，服務層不用動。
"""

import sqlite3
from collections.abc import Iterator

from fastapi import Header, Request

from caseapi.config import Settings
from caseapi.db.connection import connect


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    """每個請求一條連線，避免多執行緒共用同一個 sqlite3 連線。"""
    conn = connect(get_settings(request).db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_actor_id(request: Request) -> str:
    return get_settings(request).actor_id


def get_idempotency_key(idempotency_key: str = Header(alias='Idempotency-Key')) -> str:
    return idempotency_key
