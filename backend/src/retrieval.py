"""
混合檢索索引：BM25（本地，jieba 斷詞）+ 向量（Gemini embedding，快取）。
- 向量快取存 data/index/*.npy 與對應 meta，建一次之後查詢不重算。
- 無 API key 時自動降級為純 BM25。
- 混合分數 = alpha * 向量cos相似 + (1-alpha) * BM25正規化分數。
"""
from __future__ import annotations
import os
import json
import pickle
from typing import Optional

import numpy as np
import jieba
from rank_bm25 import BM25Okapi

from .providers import get_provider

INDEX_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "index")

# 建索引時的 embedding 批次與節流（可由 build_index 覆寫）
_EMBED_BATCH = 50
_EMBED_SLEEP = 3.0


def tokenize(text: str) -> list[str]:
    """中文斷詞，過濾空白。"""
    return [w for w in jieba.lcut(text or "") if w.strip()]


def _minmax(scores: np.ndarray) -> np.ndarray:
    if len(scores) == 0:
        return scores
    lo, hi = float(scores.min()), float(scores.max())
    if hi - lo < 1e-9:
        return np.zeros_like(scores)
    return (scores - lo) / (hi - lo)


class HybridIndex:
    """
    一個知識庫子集（如 statutes / decisions）的混合索引。
    docs: list[dict]，每筆需有 'doc_id' 與由呼叫端提供的 index_text（供檢索的文字）。
    """

    def __init__(self, name: str):
        self.name = name
        self.docs: list[dict] = []
        self.texts: list[str] = []
        self.bm25: Optional[BM25Okapi] = None
        self.embeddings: Optional[np.ndarray] = None  # shape (N, D)

    # ---------- 建立 ----------
    def build(self, docs: list[dict], texts: list[str], use_vector: bool = True):
        assert len(docs) == len(texts)
        self.docs = docs
        self.texts = texts
        tokenized = [tokenize(t) for t in texts]
        self.bm25 = BM25Okapi(tokenized)

        self.embeddings = None
        if use_vector:
            prov = get_provider()
            if prov.available:
                print(f"[index:{self.name}] 產生向量 {len(texts)} 筆 ...")
                vecs = prov.embed(texts, task_type="retrieval_document",
                                  batch_size=_EMBED_BATCH, sleep_between=_EMBED_SLEEP)
                self.embeddings = np.array(vecs, dtype=np.float32)
            else:
                print(f"[index:{self.name}] 無 API key，降級為純 BM25")
        return self

    # ---------- 持久化 ----------
    def save(self):
        os.makedirs(INDEX_DIR, exist_ok=True)
        with open(os.path.join(INDEX_DIR, f"{self.name}.pkl"), "wb") as f:
            pickle.dump({"docs": self.docs, "texts": self.texts}, f)
        if self.embeddings is not None:
            np.save(os.path.join(INDEX_DIR, f"{self.name}.npy"), self.embeddings)

    def load(self) -> bool:
        pkl = os.path.join(INDEX_DIR, f"{self.name}.pkl")
        if not os.path.isfile(pkl):
            return False
        with open(pkl, "rb") as f:
            d = pickle.load(f)
        self.docs = d["docs"]
        self.texts = d["texts"]
        self.bm25 = BM25Okapi([tokenize(t) for t in self.texts])
        npy = os.path.join(INDEX_DIR, f"{self.name}.npy")
        if os.path.isfile(npy):
            self.embeddings = np.load(npy)
        return True

    # ---------- 查詢 ----------
    def search(self, query: str, top_k: int = 5, alpha: float = 0.5) -> list[dict]:
        if self.bm25 is None:
            raise RuntimeError("索引尚未建立/載入")

        bm25_scores = np.array(self.bm25.get_scores(tokenize(query)), dtype=np.float32)
        bm25_norm = _minmax(bm25_scores)

        if self.embeddings is not None:
            prov = get_provider()
            if prov.available:
                try:
                    # 查詢時不重試、不節流，失敗即降級為 BM25（互動流暢優先）
                    q = np.array(prov.embed_one(query, task_type="retrieval_query"),
                                 dtype=np.float32)
                    doc_norm = self.embeddings / (np.linalg.norm(self.embeddings, axis=1, keepdims=True) + 1e-9)
                    qn = q / (np.linalg.norm(q) + 1e-9)
                    cos = doc_norm @ qn
                    vec_norm = _minmax(cos)
                    final = alpha * vec_norm + (1 - alpha) * bm25_norm
                except Exception as e:
                    print(f"[search:{self.name}] 向量查詢降級為BM25（{str(e)[:60]}）")
                    final = bm25_norm
            else:
                final = bm25_norm
        else:
            final = bm25_norm

        order = np.argsort(-final)[:top_k]
        results = []
        for i in order:
            r = dict(self.docs[i])
            r["_score"] = float(final[i])
            r["_bm25"] = float(bm25_norm[i])
            results.append(r)
        return results
