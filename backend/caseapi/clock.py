"""時間來源。契約規定時間一律 UTC RFC 3339。"""

from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
