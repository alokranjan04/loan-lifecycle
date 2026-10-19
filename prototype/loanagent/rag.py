"""RAG layer: embeddings + Qdrant vector store.

Adds semantic (vector) retrieval on top of the existing BM25 PolicyKnowledgeBase.
The public API is identical to PolicyKnowledgeBase so the rest of the codebase
needs no changes.

Authentication (first key found is used):
  OPENROUTER_API_KEY  → OpenRouter embeddings (openai/text-embedding-3-small, 1536-dim)
  VOYAGE_API_KEY      → Voyage AI native embeddings (voyage-3, 1024-dim)
  ANTHROPIC_API_KEY   → Voyage AI via Anthropic auth

Qdrant:
  Expects Qdrant running at QDRANT_URL (default http://localhost:6333).
  For Qdrant Cloud set QDRANT_API_KEY — passed as the `api-key` header.
  Uses only the REST API — no SDK required.

Fallback:
  If Qdrant is unreachable, the key is missing, or any embedding call fails,
  the class silently falls back to BM25-only search. The pipeline never fails
  because of the vector layer.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .knowledge import Clause, PolicyKnowledgeBase

# ── Constants ────────────────────────────────────────────────────────────────
VOYAGE_EMBED_URL    = "https://api.voyageai.com/v1/embeddings"
OPENROUTER_EMBED_URL = "https://openrouter.ai/api/v1/embeddings"
QDRANT_DEFAULT_URL  = "http://localhost:6333"
DEFAULT_EMBED_MODEL_VOYAGE = "voyage-3"           # 1024-dim
DEFAULT_EMBED_MODEL_OR     = "openai/text-embedding-3-small"  # 1536-dim

# Hybrid scoring: alpha * BM25_norm + (1-alpha) * vector_cosine
ALPHA_BM25 = 0.4


# ── Embedding client ─────────────────────────────────────────────────────────

def _auth_key() -> tuple[str, str] | None:
    """Return (api_key, provider) for the first available embedding provider."""
    k = os.environ.get("OPENROUTER_API_KEY")
    if k:
        return k, "openrouter"
    k = os.environ.get("VOYAGE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if k:
        return k, "voyage"
    return None


def _default_embed_model(provider: str) -> str:
    return DEFAULT_EMBED_MODEL_OR if provider == "openrouter" else DEFAULT_EMBED_MODEL_VOYAGE


def _embed(texts: list[str], model: str, batch_size: int = 32) -> list[list[float]]:
    """Embed texts via OpenRouter or Voyage AI. Returns one float vector per text."""
    import time
    auth = _auth_key()
    if not auth:
        raise RuntimeError("Set OPENROUTER_API_KEY, VOYAGE_API_KEY, or ANTHROPIC_API_KEY.")
    key, provider = auth

    if provider == "openrouter":
        url = OPENROUTER_EMBED_URL
        extra_headers = {
            "HTTP-Referer": "https://loan-lifecycle-demo",
            "X-Title": "Loan Lifecycle Agent",
        }
        def parse_response(data):
            return sorted(data["data"], key=lambda x: x["index"])
    else:
        url = VOYAGE_EMBED_URL
        extra_headers = {}
        def parse_response(data):
            return sorted(data["data"], key=lambda x: x["index"])

    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i: i + batch_size]
        for attempt in range(3):
            try:
                payload = {"model": model, "input": batch}
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode(),
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                             **extra_headers},
                )
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = json.loads(resp.read())
                items = parse_response(data)
                all_embeddings.extend(item["embedding"] for item in items)
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 2:
                    time.sleep(5 * (attempt + 1))
                else:
                    raise
        if i + batch_size < len(texts):
            time.sleep(0.5)
    return all_embeddings


# ── Qdrant REST client ───────────────────────────────────────────────────────

class _Qdrant:
    """Thin REST wrapper for Qdrant. No SDK needed — all standard-library HTTP."""

    def __init__(self, url: str, api_key: str = ""):
        self.url = url.rstrip("/")
        self._api_key = api_key

    def _headers(self, with_content_type: bool = False) -> dict:
        h: dict = {}
        if with_content_type:
            h["Content-Type"] = "application/json"
        if self._api_key:
            h["api-key"] = self._api_key
        return h

    def _req(self, method: str, path: str, body: dict | None = None, timeout: int = 10) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{self.url}{path}",
            data=data,
            headers=self._headers(with_content_type=data is not None),
            method=method,
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    def alive(self) -> bool:
        try:
            req = urllib.request.Request(
                f"{self.url}/healthz",
                headers=self._headers(),
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def collection_exists(self, name: str) -> bool:
        try:
            self._req("GET", f"/collections/{name}")
            return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            raise

    def create_collection(self, name: str, dim: int) -> None:
        self._req("PUT", f"/collections/{name}",
                  {"vectors": {"size": dim, "distance": "Cosine"}})

    def upsert(self, name: str, points: list[dict]) -> None:
        """points: [{"id": int, "vector": [...], "payload": {...}}]"""
        self._req("PUT", f"/collections/{name}/points",
                  {"points": points}, timeout=30)

    def search(self, name: str, vector: list[float], k: int) -> list[dict]:
        """Returns Qdrant result list: [{"id", "score", "payload"}]"""
        result = self._req("POST", f"/collections/{name}/points/search",
                           {"vector": vector, "limit": k, "with_payload": True})
        return result.get("result", [])


# ── Hybrid knowledge base ────────────────────────────────────────────────────

class HybridPolicyKB(PolicyKnowledgeBase):
    """PolicyKnowledgeBase extended with Voyage AI + Qdrant hybrid retrieval.

    Identical public interface to PolicyKnowledgeBase. Drop-in replacement.
    Falls back to BM25 silently if Qdrant or the embedding key is unavailable.

    The Qdrant collection name is derived from the policy file's SHA-256 hash,
    so each policy version gets its own collection and re-indexing is automatic.
    """

    def __init__(
        self,
        path: Path,
        version: str = "v3.2",
        params: dict | None = None,
        effective_from: str = "",
        qdrant_url: str = QDRANT_DEFAULT_URL,
        qdrant_api_key: str = "",
        embed_model: str | None = None,
        extra_paths: list | None = None,
    ):
        auth = _auth_key()
        provider = auth[1] if auth else "voyage"
        self._model = embed_model or os.environ.get("LOAN_AGENT_EMBED_MODEL", _default_embed_model(provider))
        self._qdrant = _Qdrant(qdrant_url, api_key=qdrant_api_key)
        self._vector_ready = False
        self._index_error: str = ""
        super().__init__(path, version, params, effective_from, extra_paths=extra_paths)
        # sha256 is computed by super().__init__(), so collection name is set after
        self._collection = f"policy_{self.sha256[:16]}"
        self._try_init()

    # ── Initialisation ───────────────────────────────────────────────────────

    def _try_init(self) -> None:
        """Best-effort: index clauses. Silently degrades to BM25 on any failure."""
        try:
            if not _auth_key():
                self._index_error = "No OPENROUTER_API_KEY / VOYAGE_API_KEY / ANTHROPIC_API_KEY — using BM25"
                return
            if not self._qdrant.alive():
                self._index_error = f"Qdrant not reachable at {self._qdrant.url} — using BM25"
                return
            if not self._qdrant.collection_exists(self._collection):
                self._build_vector_index()
            self._vector_ready = True
        except Exception as exc:
            self._index_error = f"RAG init failed ({exc}) — using BM25"

    def _build_vector_index(self) -> None:
        """Embed all policy clauses and upsert into Qdrant."""
        clauses = list(self.clauses.values())
        texts = [f"{c.id}: {c.title}. {c.text}" for c in clauses]
        vectors = _embed(texts, self._model)

        dim = len(vectors[0])
        if not self._qdrant.collection_exists(self._collection):
            self._qdrant.create_collection(self._collection, dim)

        points = [
            {
                "id": i,
                "vector": vec,
                "payload": {
                    "clause_id": c.id,
                    "title": c.title,
                    "text": c.text,
                    "source": c.source,
                    "line": c.line,
                    "policy_version": self.version,
                },
            }
            for i, (c, vec) in enumerate(zip(clauses, vectors))
        ]
        self._qdrant.upsert(self._collection, points)

    # ── Search ───────────────────────────────────────────────────────────────

    def search(self, query: str, k: int = 3) -> list[tuple[Clause, float]]:
        """Hybrid BM25 + vector search.

        Scores are normalised to [0, 1] then combined:
            hybrid = ALPHA_BM25 * bm25_norm + (1 - ALPHA_BM25) * cosine_sim

        Falls back to BM25 if the vector layer is unavailable.
        """
        # Always run BM25 — it is the safety net and needs no network
        bm25 = super().search(query, k=max(k * 2, 10))

        if not self._vector_ready:
            return bm25[:k]

        try:
            q_vec = _embed([query], self._model)[0]
            hits = self._qdrant.search(self._collection, q_vec, k=max(k * 2, 10))
        except Exception:
            return bm25[:k]

        # Normalise BM25 scores to [0, 1]
        bm25_max = max((s for _, s in bm25), default=1.0) or 1.0
        bm25_map = {c.id: s / bm25_max for c, s in bm25}

        # Qdrant cosine scores are already in [0, 1] for normalised vectors
        vec_map = {
            hit["payload"]["clause_id"]: float(hit["score"])
            for hit in hits
            if "clause_id" in hit.get("payload", {})
        }

        # Combine all candidates from both retrievers
        all_ids = set(bm25_map) | set(vec_map)
        combined: list[tuple[Clause, float]] = []
        for cid in all_ids:
            clause = self.clauses.get(cid)
            if clause is None:
                continue
            b = bm25_map.get(cid, 0.0)
            v = vec_map.get(cid, 0.0)
            combined.append((clause, ALPHA_BM25 * b + (1.0 - ALPHA_BM25) * v))

        combined.sort(key=lambda x: -x[1])
        return combined[:k]

    # ── Status ───────────────────────────────────────────────────────────────

    def rag_status(self) -> dict:
        """Return a status dict for the /api/rag/status endpoint."""
        return {
            "vector_ready": self._vector_ready,
            "embed_model": self._model,
            "collection": self._collection,
            "qdrant_url": self._qdrant.url,
            "clause_count": len(self.clauses),
            "policy_version": self.version,
            "alpha_bm25": ALPHA_BM25,
            "alpha_vector": round(1.0 - ALPHA_BM25, 2),
            "error": self._index_error or None,
        }

    # ── Factory (same signature as PolicyKnowledgeBase.for_date) ────────────

    @classmethod
    def for_date(                                       # type: ignore[override]
        cls,
        policy_dir: Path,
        as_of: str,
        version: str | None = None,
        qdrant_url: str = QDRANT_DEFAULT_URL,
        qdrant_api_key: str = "",
        embed_model: str | None = None,
    ) -> "HybridPolicyKB":
        from datetime import date
        reg = json.loads((policy_dir / "registry.json").read_text())["versions"]
        if version:
            v = next(x for x in reg if x["version"] == version)
        else:
            live = [x for x in reg if date.fromisoformat(x["effective_from"]) <= date.fromisoformat(as_of)]
            v = max(live, key=lambda x: x["effective_from"])
        extra = sorted((policy_dir / "docs").glob("*.md")) if (policy_dir / "docs").is_dir() else []
        return cls(
            policy_dir / v["file"],
            v["version"],
            v.get("params"),
            v["effective_from"],
            qdrant_url=qdrant_url,
            qdrant_api_key=qdrant_api_key,
            embed_model=embed_model,
            extra_paths=extra,
        )


# ── Public factory ───────────────────────────────────────────────────────────

def get_knowledge_base(
    policy_dir: Path,
    as_of: str,
    version: str | None = None,
    qdrant_url: str | None = None,
    embed_model: str | None = None,
) -> "PolicyKnowledgeBase":
    """Factory used by orchestrator.py.

    Returns HybridPolicyKB when VOYAGE_API_KEY or ANTHROPIC_API_KEY is set,
    otherwise returns the plain BM25 PolicyKnowledgeBase.
    Both have the identical interface; the caller does not need to care.

    Reads QDRANT_URL and QDRANT_API_KEY from the environment.
    QDRANT_API_KEY is required for Qdrant Cloud; ignored for local Qdrant.
    """
    url = qdrant_url or os.environ.get("QDRANT_URL", QDRANT_DEFAULT_URL)
    api_key = os.environ.get("QDRANT_API_KEY", "")
    if _auth_key():
        return HybridPolicyKB.for_date(policy_dir, as_of, version,
                                       qdrant_url=url, qdrant_api_key=api_key,
                                       embed_model=embed_model)
    return PolicyKnowledgeBase.for_date(policy_dir, as_of, version)
