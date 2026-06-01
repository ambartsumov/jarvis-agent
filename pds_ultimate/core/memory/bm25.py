"""BM25 keyword search — agentmemory-style retrieval without embeddings API."""

from __future__ import annotations

import math
import re
from collections import Counter


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9_]+", text.lower())


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._docs: list[tuple[str, dict]] = []  # (doc_id, fields)
        self._avgdl = 0.0
        self._df: Counter[str] = Counter()
        self._N = 0

    def add(self, doc_id: str, content: str, **fields: str) -> None:
        text = " ".join([content, *[str(v) for v in fields.values()]])
        tokens = _tokenize(text)
        tf = Counter(tokens)
        self._docs.append((doc_id, {"content": content, "tokens": tokens, "tf": tf, **fields}))
        self._N = len(self._docs)
        self._df = Counter()
        lengths = []
        for _, d in self._docs:
            lengths.append(len(d["tokens"]))
            for t in set(d["tokens"]):
                self._df[t] += 1
        self._avgdl = sum(lengths) / max(len(lengths), 1)

    def remove(self, doc_id: str) -> bool:
        before = len(self._docs)
        self._docs = [(d, f) for d, f in self._docs if d != doc_id]
        if len(self._docs) == before:
            return False
        self._N = len(self._docs)
        self._df = Counter()
        lengths = []
        for _, d in self._docs:
            lengths.append(len(d["tokens"]))
            for t in set(d["tokens"]):
                self._df[t] += 1
        self._avgdl = sum(lengths) / max(len(lengths), 1)
        return True

    def rebuild(self, items: list[tuple[str, str, dict]]) -> None:
        self._docs.clear()
        for doc_id, content, fields in items:
            self.add(doc_id, content, **fields)

    def search(self, query: str, limit: int = 8) -> list[tuple[str, float]]:
        q_tokens = _tokenize(query)
        if not q_tokens or not self._docs:
            return []

        scores: list[tuple[str, float]] = []
        for doc_id, d in self._docs:
            score = 0.0
            dl = len(d["tokens"])
            for term in q_tokens:
                if term not in d["tf"]:
                    continue
                df = self._df.get(term, 0)
                idf = math.log(1 + (self._N - df + 0.5) / (df + 0.5))
                tf = d["tf"][term]
                denom = tf + self.k1 * (1 - self.b + self.b * dl / self._avgdl)
                score += idf * (tf * (self.k1 + 1)) / denom
            if score > 0:
                scores.append((doc_id, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:limit]
