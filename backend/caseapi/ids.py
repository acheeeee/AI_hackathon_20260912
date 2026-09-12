"""不透明 ID。對外一律當成字串，不從 ID 反推任何語意。"""

import uuid

ID_SUFFIX_LENGTH = 12


def new_id(prefix: str) -> str:
    return f'{prefix}_{uuid.uuid4().hex[:ID_SUFFIX_LENGTH]}'
