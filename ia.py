from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

try:
    import redis
except ImportError:  # optional dependency
    redis = None

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
except ImportError:  # optional dependency
    TfidfVectorizer = None
    cosine_similarity = None


@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    score: float


class LocalKnowledgeAssistant:
    """Optional local-first retrieval helper for the portfolio project.

    Knowledge is loaded from a public-safe Markdown file. Retrieval stays local,
    Redis is optional, and Ollama is used only when explicitly enabled.
    """

    def __init__(
        self,
        knowledge_path: str | Path | None = None,
        model: str | None = None,
        ollama_url: str | None = None,
    ) -> None:
        base_dir = Path(__file__).resolve().parent
        self.knowledge_path = Path(
            knowledge_path
            or os.getenv(
                "KNOWLEDGE_BASE_PATH",
                base_dir / "docs" / "knowledge_base.example.md",
            )
        )
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")
        self.ollama_url = ollama_url or os.getenv(
            "OLLAMA_CHAT_URL",
            "http://127.0.0.1:11434/api/chat",
        )
        self.chunks = self._load_chunks()
        self.vectorizer = None
        self.matrix = None
        if self.chunks and TfidfVectorizer is not None:
            self.vectorizer = TfidfVectorizer(stop_words=None, max_features=4096)
            self.matrix = self.vectorizer.fit_transform(self.chunks)
        self.redis_client = self._build_redis_client()

    def _load_chunks(self) -> list[str]:
        if not self.knowledge_path.exists():
            return []
        content = self.knowledge_path.read_text(encoding="utf-8")
        blocks = [
            block.strip()
            for block in re.split(r"\n{2,}", content)
            if block.strip()
        ]
        return [
            block
            for block in blocks
            if not block.startswith("#") or len(block) > 40
        ]

    def _build_redis_client(self):
        if redis is None or os.getenv("REDIS_ENABLED", "false").lower() != "true":
            return None
        try:
            client = redis.Redis(
                host=os.getenv("REDIS_HOST", "127.0.0.1"),
                port=int(os.getenv("REDIS_PORT", "6379")),
                db=int(os.getenv("REDIS_DB", "0")),
                password=os.getenv("REDIS_PASSWORD") or None,
                socket_timeout=1,
                decode_responses=True,
            )
            client.ping()
            return client
        except Exception:
            return None

    def retrieve(self, question: str, top_k: int = 3) -> list[RetrievedChunk]:
        query = question.strip()
        if not query or not self.chunks:
            return []
        top_k = max(1, min(top_k, 8))

        if (
            self.vectorizer is not None
            and self.matrix is not None
            and cosine_similarity is not None
        ):
            query_vector = self.vectorizer.transform([query])
            scores = cosine_similarity(query_vector, self.matrix).flatten()
            indices = scores.argsort()[-top_k:][::-1]
            return [
                RetrievedChunk(self.chunks[index], float(scores[index]))
                for index in indices
                if scores[index] > 0
            ]

        terms = {
            term
            for term in re.findall(r"[a-zA-ZÀ-ÿ0-9_]+", query.lower())
            if len(term) > 2
        }
        ranked: list[RetrievedChunk] = []
        for chunk in self.chunks:
            words = set(re.findall(r"[a-zA-ZÀ-ÿ0-9_]+", chunk.lower()))
            score = len(terms & words) / max(len(terms), 1)
            if score:
                ranked.append(RetrievedChunk(chunk, score))
        return sorted(ranked, key=lambda item: item.score, reverse=True)[:top_k]

    def answer(self, question: str) -> dict[str, Any]:
        question = question.strip()[:2000]
        if not question:
            return {
                "answer": "Pergunta vazia.",
                "source": "validation",
                "chunks": [],
            }

        cache_key = "helpdesk:rag:" + hashlib.sha256(
            question.lower().encode()
        ).hexdigest()
        if self.redis_client is not None:
            cached = self.redis_client.get(cache_key)
            if cached:
                return json.loads(cached)

        chunks = self.retrieve(question)
        context = "\n\n".join(item.text for item in chunks)
        result = self._ask_ollama(question, context)
        if result is None:
            result = {
                "answer": (
                    chunks[0].text
                    if chunks
                    else "Não encontrei contexto suficiente na base local."
                ),
                "source": "local-retrieval",
                "chunks": [item.text for item in chunks],
            }
        if self.redis_client is not None:
            self.redis_client.setex(
                cache_key,
                900,
                json.dumps(result, ensure_ascii=False),
            )
        return result

    def _ask_ollama(self, question: str, context: str) -> dict[str, Any] | None:
        if os.getenv("OLLAMA_ENABLED", "false").lower() != "true":
            return None
        prompt = (
            "Responda somente com base no contexto fornecido. "
            "Quando o contexto não for suficiente, declare a limitação.\n\n"
            f"CONTEXTO:\n{context or '[sem contexto]'}\n\n"
            f"PERGUNTA:\n{question}"
        )
        try:
            response = requests.post(
                self.ollama_url,
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            answer = payload.get("message", {}).get("content", "").strip()
            if not answer:
                return None
            return {
                "answer": answer,
                "source": "ollama-local",
                "chunks": [item.text for item in self.retrieve(question)],
            }
        except requests.RequestException:
            return None


MinimalAIWithRAG = LocalKnowledgeAssistant
