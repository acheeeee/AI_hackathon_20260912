"""
供應商抽象層。
目前實作 Gemini（embedding: gemini-embedding-001, LLM: gemini-2.5-flash）。
設計目標：
- key 來源：環境變數 GEMINI_API_KEY / GOOGLE_API_KEY，或專案根目錄 .env
- 無 key 時 available=False，上層據此降級（純 BM25 + 模板）
- 比賽當天換官方 API：只改本檔
"""
from __future__ import annotations
import os
from typing import Optional


EMBED_MODEL = os.environ.get("GEMINI_EMBED_MODEL", "models/gemini-embedding-2")
LLM_MODEL = os.environ.get("GEMINI_LLM_MODEL", "gemini-3.6-flash")


def _load_dotenv() -> None:
    """極簡 .env 載入（避免額外依賴）。只設定尚未存在的變數。"""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    for candidate in (
        os.path.join(os.path.dirname(__file__), "..", ".env"),
        os.path.join(root, ".env"),
    ):
        if os.path.isfile(candidate):
            with open(candidate, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    os.environ.setdefault(k, v)


def get_api_key() -> Optional[str]:
    _load_dotenv()
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


class GeminiProvider:
    """封裝 Gemini embedding 與生成。無 key 時 available=False。"""

    def __init__(self):
        self.api_key = get_api_key()
        self._genai = None
        if self.api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self._genai = genai
            except Exception as e:  # SDK 未安裝或設定失敗
                print(f"[providers] Gemini 初始化失敗，降級為無 API 模式: {e}")
                self._genai = None

    @property
    def available(self) -> bool:
        return self._genai is not None

    # ---------- Embedding ----------
    def embed(self, texts: list[str], task_type: str = "retrieval_document",
              batch_size: int = 100, sleep_between: float = 1.0,
              max_retries: int = 6) -> list[list[float]]:
        """批次回傳每段文字的向量，含 429 自動重試與節流。
        task_type: retrieval_document / retrieval_query。"""
        if not self.available:
            raise RuntimeError("Gemini 不可用（未設定 API key）")
        import time
        out: list[list[float]] = []
        clean = [t if t else " " for t in texts]
        n_batches = (len(clean) + batch_size - 1) // batch_size
        for bi, i in enumerate(range(0, len(clean), batch_size)):
            chunk = clean[i:i + batch_size]
            attempt = 0
            while True:
                try:
                    r = self._genai.embed_content(
                        model=EMBED_MODEL, content=chunk, task_type=task_type,
                    )
                    emb = r["embedding"]
                    if emb and isinstance(emb[0], (int, float)):
                        out.append(list(emb))
                    else:
                        out.extend([list(v) for v in emb])
                    break
                except Exception as e:
                    msg = str(e)
                    is_quota = "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower()
                    attempt += 1
                    if not is_quota or attempt > max_retries:
                        raise
                    # 從錯誤訊息解析 retry_delay，否則指數退避
                    import re as _re
                    m = _re.search(r"retry in ([\d.]+)s", msg) or _re.search(r"seconds: (\d+)", msg)
                    wait = float(m.group(1)) + 2 if m else min(60, 5 * attempt)
                    print(f"[embed] 額度限制，等待 {wait:.0f}s 後重試 (batch {bi+1}/{n_batches}, 第{attempt}次)")
                    time.sleep(wait)
            # 批次間節流，避免觸及每分鐘上限
            if bi < n_batches - 1 and sleep_between > 0:
                time.sleep(sleep_between)
        return out

    def embed_one(self, text: str, task_type: str = "retrieval_query") -> list[float]:
        return self.embed([text], task_type=task_type, batch_size=1,
                          sleep_between=0, max_retries=0)[0]

    # ---------- 生成 ----------
    def generate(self, prompt: str, temperature: float = 0.2, max_tokens: int = 4096) -> str:
        if not self.available:
            raise RuntimeError("Gemini 不可用（未設定 API key）")
        model = self._genai.GenerativeModel(LLM_MODEL)
        resp = model.generate_content(
            prompt,
            generation_config={"temperature": temperature, "max_output_tokens": max_tokens},
        )
        return resp.text


# 單例
_provider: Optional[GeminiProvider] = None


def get_provider() -> GeminiProvider:
    global _provider
    if _provider is None:
        _provider = GeminiProvider()
    return _provider
