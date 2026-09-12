"""執行設定。v1 是單人 demo：actor 由伺服器端固定，不接受前端指定。"""

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / 'data' / 'caseapi.db'
DEFAULT_ACTOR_ID = 'actor_demo'
DEFAULT_EVIDENCE_RELEASE_DIR = (
    Path(__file__).resolve().parents[2] / 'data' / 'processed' / 'releases' / 'r3'
)
DEFAULT_EVIDENCE_RELEASE_ID = 'r3'


@dataclass(frozen=True)
class Settings:
    db_path: Path
    actor_id: str = DEFAULT_ACTOR_ID
    evidence_release_dir: Path = DEFAULT_EVIDENCE_RELEASE_DIR
    evidence_release_id: str = DEFAULT_EVIDENCE_RELEASE_ID


def load_settings() -> Settings:
    """從環境變數讀設定；未設定時使用本機 demo 預設值。"""
    return Settings(
        db_path=Path(os.environ.get('CASEAPI_DB_PATH', str(DEFAULT_DB_PATH))),
        actor_id=os.environ.get('CASEAPI_ACTOR_ID', DEFAULT_ACTOR_ID),
        evidence_release_dir=Path(
            os.environ.get(
                'CASEAPI_EVIDENCE_RELEASE_DIR', str(DEFAULT_EVIDENCE_RELEASE_DIR)
            )
        ),
        evidence_release_id=os.environ.get(
            'CASEAPI_EVIDENCE_RELEASE_ID', DEFAULT_EVIDENCE_RELEASE_ID
        ),
    )
