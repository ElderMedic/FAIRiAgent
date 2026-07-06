"""Semantic chunk index backed by Qdrant."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Sequence

from ..config import config
from .chunking import SourceChunk
from .qdrant_client import ensure_qdrant_available

logger = logging.getLogger(__name__)

_EMBEDDER = None
_RERANKER = None


class EmbeddingClient:
    def __init__(self, backend: str, model_name: str, base_url: str = "", api_key: str = ""):
        self.backend = backend
        self.model_name = model_name
        self.base_url = base_url
        self.api_key = api_key
        self.local_model = None

    def initialize(self):
        if self.backend == "auto":
            if self.base_url:
                try:
                    import urllib.request
                    url = f"{self.base_url.rstrip('/')}/api/tags"
                    req = urllib.request.Request(url, method="GET")
                    with urllib.request.urlopen(req, timeout=2.0) as response:
                        if response.status == 200:
                            self.backend = "ollama"
                            logger.info("Using Ollama backend for embedding at %s", self.base_url)
                            return
                except Exception as e:
                    logger.warning("Ollama backend check failed at %s: %s. Falling back.", self.base_url, e)
            
            if self.api_key:
                self.backend = "jina_api"
                logger.info("Using Jina API backend for embedding")
            else:
                self.backend = "local"
                logger.info("Using local SentenceTransformer backend for embedding")

        if self.backend == "local":
            try:
                from sentence_transformers import SentenceTransformer
                self.local_model = SentenceTransformer(self.model_name, trust_remote_code=True)
            except Exception as exc:
                logger.error("Failed to load local SentenceTransformer %s: %s", self.model_name, exc)
                raise exc

    def encode(self, texts: Sequence[str], is_query: bool = False) -> List[List[float]]:
        if not texts:
            return []

        prefix = ""
        if self.backend == "local":
            if "bge-" in self.model_name.lower():
                prefix = "passage: " if not is_query else "query: "

        prefixed_texts = [f"{prefix}{text}" for text in texts]

        if self.backend == "ollama":
            return self._encode_ollama(prefixed_texts)
        elif self.backend == "jina_api":
            return self._encode_jina(prefixed_texts)
        else:
            if self.local_model is None:
                raise RuntimeError("Local embedding model not initialized")
            import numpy as np
            vectors = self.local_model.encode(prefixed_texts, normalize_embeddings=True, show_progress_bar=False)
            if isinstance(vectors, np.ndarray):
                return vectors.tolist()
            return [v.tolist() if hasattr(v, "tolist") else list(v) for v in vectors]

    def _encode_ollama(self, texts: Sequence[str]) -> List[List[float]]:
        import json
        import time
        import urllib.request
        
        base_url = self.base_url or "http://localhost:11434"
        url = f"{base_url.rstrip('/')}/api/embed"
        
        embeddings = []
        batch_size = 32
        max_retries = 3
        for i in range(0, len(texts), batch_size):
            batch = list(texts[i:i+batch_size])
            data = {
                "model": self.model_name,
                "input": batch
            }
            last_exc: Optional[Exception] = None
            for attempt in range(max_retries):
                try:
                    req = urllib.request.Request(
                        url,
                        data=json.dumps(data).encode("utf-8"),
                        headers={"Content-Type": "application/json"}
                    )
                    with urllib.request.urlopen(req, timeout=30.0) as response:
                        res_data = json.loads(response.read().decode("utf-8"))
                        batch_embs = res_data.get("embeddings", [])
                        embeddings.extend(batch_embs)
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    if attempt < max_retries - 1:
                        wait = 2.0 * (attempt + 1)
                        logger.warning(
                            "Ollama embedding attempt %d/%d failed: %s — retrying in %.1fs",
                            attempt + 1, max_retries, exc, wait,
                        )
                        time.sleep(wait)
            if last_exc is not None:
                logger.error("Ollama embedding API call failed after %d attempts: %s", max_retries, last_exc)
                raise last_exc
        return embeddings

    def _encode_jina(self, texts: Sequence[str]) -> List[List[float]]:
        import json
        import urllib.request
        
        url = "https://api.jina.ai/v1/embeddings"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        embeddings = []
        batch_size = 32
        for i in range(0, len(texts), batch_size):
            batch = list(texts[i:i+batch_size])
            data = {
                "model": "jina-embeddings-v3",
                "task": "retrieval.passage",
                "dimensions": 1024,
                "input": batch
            }
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(data).encode("utf-8"),
                    headers=headers
                )
                with urllib.request.urlopen(req, timeout=15.0) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                    batch_embs = [item.get("embedding") for item in res_data.get("data", [])]
                    embeddings.extend(batch_embs)
            except Exception as exc:
                logger.error("Jina embedding API call failed: %s", exc)
                raise exc
        return embeddings


class RerankerClient:
    def __init__(self, backend: str, model_name: str, api_key: str = ""):
        self.backend = backend
        self.model_name = model_name
        self.api_key = api_key
        self.local_model = None

    def initialize(self):
        if self.backend == "auto":
            if self.api_key:
                self.backend = "jina_api"
                logger.info("Using Jina API backend for reranker")
            else:
                self.backend = "local"
                logger.info("Using local CrossEncoder backend for reranker")

        if self.backend == "local":
            try:
                from sentence_transformers import CrossEncoder
                self.local_model = CrossEncoder(self.model_name, trust_remote_code=True)
            except Exception as exc:
                logger.error("Failed to load local CrossEncoder %s: %s", self.model_name, exc)
                raise exc

    def predict(self, pairs: List[tuple[str, str]], show_progress_bar: bool = False) -> List[float]:
        if not pairs:
            return []

        if self.backend == "jina_api":
            return self._rerank_jina(pairs)
        else:
            if self.local_model is None:
                raise RuntimeError("Local reranker model not initialized")
            scores = self.local_model.predict(pairs, show_progress_bar=show_progress_bar)
            return [float(s) for s in scores]

    def _rerank_jina(self, pairs: List[tuple[str, str]]) -> List[float]:
        import json
        import urllib.request
        
        if not pairs:
            return []
        query = pairs[0][0]
        documents = [p[1] for p in pairs]
        
        url = "https://api.jina.ai/v1/rerank"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        data = {
            "model": "jina-reranker-v2-base-multilingual",
            "query": query,
            "documents": documents,
            "top_n": len(documents)
        }
        
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode("utf-8"),
                headers=headers
            )
            with urllib.request.urlopen(req, timeout=15.0) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                results = res_data.get("results", [])
                scores_map = {item["index"]: float(item["relevance_score"]) for item in results}
                return [scores_map.get(i, 0.0) for i in range(len(documents))]
        except Exception as exc:
            logger.error("Jina rerank API call failed: %s", exc)
            raise exc


def _get_embedder():
    global _EMBEDDER
    if _EMBEDDER is not None:
        return _EMBEDDER
    try:
        client = EmbeddingClient(
            backend=config.retrieval_embedding_backend,
            model_name=config.retrieval_embedding_model,
            base_url=config.retrieval_embedding_base_url,
            api_key=config.jina_api_key,
        )
        client.initialize()
        _EMBEDDER = client
        return _EMBEDDER
    except Exception as exc:
        logger.warning("Semantic embedder unavailable: %s", exc)
        _EMBEDDER = None
        return None


def _resolve_embedding_vector_size() -> Optional[int]:
    """Return the embedder's actual vector width, falling back to config."""
    configured = int(config.retrieval_embedding_dims or 0) or None
    client = _get_embedder()
    if client is None:
        return configured
    try:
        vectors = client.encode(["dimension_probe"], is_query=True)
        if vectors and vectors[0]:
            actual = len(vectors[0])
            if configured and configured != actual:
                logger.warning(
                    "FAIRIFIER_RETRIEVAL_EMBEDDING_DIMS=%s but embedder returns %s; using actual width",
                    configured,
                    actual,
                )
            return actual
    except Exception as exc:
        logger.warning("Embedding dimension probe failed: %s", exc)
    return configured


def _collection_vector_size(client: Any, collection_name: str) -> Optional[int]:
    try:
        info = client.get_collection(collection_name)
        vectors = info.config.params.vectors
        if hasattr(vectors, "size"):
            return int(vectors.size)
        if isinstance(vectors, dict):
            for params in vectors.values():
                if hasattr(params, "size"):
                    return int(params.size)
    except Exception as exc:
        logger.debug("Could not read vector size for %s: %s", collection_name, exc)
    return None


def _get_reranker():
    global _RERANKER
    if _RERANKER is not None:
        return _RERANKER
    try:
        client = RerankerClient(
            backend=config.retrieval_rerank_backend,
            model_name=config.retrieval_rerank_model,
            api_key=config.jina_api_key,
        )
        client.initialize()
        _RERANKER = client
        return _RERANKER
    except Exception as exc:
        logger.warning("Cross-encoder reranker unavailable: %s", exc)
        _RERANKER = None
        return None


def _encode_passages(texts: Sequence[str]) -> List[List[float]]:
    client = _get_embedder()
    if client is None or not texts:
        return []
    try:
        return client.encode(texts, is_query=False)
    except Exception as exc:
        logger.warning("Passage embedding failed; falling back to lexical retrieval: %s", exc)
        return []


def _encode_query(text: str) -> Optional[List[float]]:
    client = _get_embedder()
    if client is None or not text:
        return None
    try:
        res = client.encode([text], is_query=True)
        return res[0] if res else None
    except Exception as exc:
        logger.warning("Query embedding failed; falling back to lexical retrieval: %s", exc)
        return None


class SemanticIndex:
    """Per-run Qdrant collection for chunk and evidence payloads."""

    def __init__(
        self,
        session_id: str,
        *,
        host: Optional[str] = None,
        port: Optional[int] = None,
    ):
        self.session_id = session_id
        prefix = (config.retrieval_qdrant_collection_prefix or "run").strip() or "run"
        safe_session = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in session_id)
        self.collection_name = f"{prefix}_{safe_session}"
        self.host = host or config.mem0_qdrant_host
        self.port = int(port or config.mem0_qdrant_port)
        self._client = None
        self._available = False
        self._status = "uninitialized"

    def is_available(self) -> bool:
        return self._available and self._client is not None and self._status == "ready"

    def embedder_ready(self) -> bool:
        return _get_embedder() is not None

    def status(self) -> str:
        return self._status

    def connect(self) -> bool:
        if not config.semantic_index_enabled:
            self._status = "disabled"
            return False
        if self._available and self._client is not None:
            return True
        ready = ensure_qdrant_available(
            self.host,
            self.port,
            auto_start=config.mem0_auto_start_qdrant,
            container_name=config.mem0_qdrant_container_name,
            healthcheck_timeout_seconds=config.mem0_healthcheck_timeout_seconds,
        )
        if not ready:
            self._status = "qdrant_unreachable"
            return False
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models as qmodels

            vector_size = _resolve_embedding_vector_size()
            if not vector_size:
                self._status = "embedder_unavailable"
                return False

            self._client = QdrantClient(host=self.host, port=self.port, timeout=10.0)
            if self._client.collection_exists(self.collection_name):
                existing_size = _collection_vector_size(self._client, self.collection_name)
                if existing_size and existing_size != vector_size:
                    logger.warning(
                        "Recreating Qdrant collection %s (dim %s -> %s)",
                        self.collection_name,
                        existing_size,
                        vector_size,
                    )
                    self._client.delete_collection(self.collection_name)
            if not self._client.collection_exists(self.collection_name):
                self._client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=qmodels.VectorParams(
                        size=vector_size,
                        distance=qmodels.Distance.COSINE,
                    ),
                )
            self._available = True
            self._status = "ready"
            return True
        except Exception as exc:
            logger.warning("Semantic index connection failed: %s", exc)
            self._status = f"error:{exc}"
            self._available = False
            self._client = None
            return False

    def index_chunks(self, chunks: Sequence[SourceChunk]) -> int:
        if not self.connect() or not chunks:
            return 0
        texts = [chunk.text for chunk in chunks]
        vectors = _encode_passages(texts)
        if not vectors:
            self._status = "embedder_unavailable"
            self._available = False
            return 0

        from qdrant_client.http import models as qmodels

        points = []
        for chunk, vector in zip(chunks, vectors):
            points.append(
                qmodels.PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.chunk_id)),
                    vector=vector,
                    payload={
                        "kind": "chunk",
                        "chunk_id": chunk.chunk_id,
                        "source_id": chunk.source_id,
                        "char_start": chunk.char_start,
                        "char_end": chunk.char_end,
                        "section_id": chunk.section_id,
                        "section_title": chunk.section_title,
                        "section_type": chunk.section_type,
                        "text": chunk.text[:4000],
                    },
                )
            )
        self._client.upsert(collection_name=self.collection_name, points=points, wait=True)
        return len(points)

    def search(self, query: str, *, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        if not self.connect():
            return []
        vector = _encode_query(query)
        if vector is None:
            return []
        hit_limit = limit or config.retrieval_semantic_max_hits
        hits = self._client.search(
            collection_name=self.collection_name,
            query_vector=vector,
            limit=hit_limit,
            query_filter=None,
        )
        results: List[Dict[str, Any]] = []
        for hit in hits:
            payload = hit.payload or {}
            if payload.get("kind") not in (None, "chunk", "evidence"):
                continue
            results.append(
                {
                    "source_id": payload.get("source_id"),
                    "start": int(payload.get("char_start") or 0),
                    "end": int(payload.get("char_end") or 0),
                    "excerpt": str(payload.get("text") or "")[:2000],
                    "score": float(hit.score or 0.0),
                    "retrieval_channel": "semantic",
                    "chunk_id": payload.get("chunk_id"),
                    "section_id": payload.get("section_id"),
                }
            )
        return results

    def upsert_evidence(self, records: Sequence[Dict[str, Any]]) -> int:
        if not self.connect() or not records:
            return 0
        texts = [str(record.get("text") or record.get("evidence_text") or "") for record in records]
        vectors = _encode_passages(texts)
        if not vectors:
            return 0
        from qdrant_client.http import models as qmodels

        points = []
        for record, vector in zip(records, vectors):
            evidence_id = str(record.get("evidence_id") or record.get("packet_id") or uuid.uuid4())
            points.append(
                qmodels.PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, evidence_id)),
                    vector=vector,
                    payload={
                        "kind": "evidence",
                        **record,
                    },
                )
            )
        self._client.upsert(collection_name=self.collection_name, points=points, wait=True)
        return len(points)

    def serialize(self) -> Dict[str, Any]:
        ready = self.is_available() and self.embedder_ready()
        return {
            "session_id": self.session_id,
            "collection_name": self.collection_name,
            "host": self.host,
            "port": self.port,
            "status": self._status,
            "available": ready,
            "embedder_ready": self.embedder_ready(),
        }


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[Dict[str, Any]]],
    *,
    k: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Fuse multiple ranked hit lists with RRF."""
    rrf_k = int(k or config.retrieval_rrf_k)
    scores: Dict[str, float] = {}
    payloads: Dict[str, Dict[str, Any]] = {}

    def _key(item: Dict[str, Any]) -> str:
        return (
            f"{item.get('source_id')}:{item.get('start')}:{item.get('end')}:"
            f"{item.get('table', '')}:{item.get('row_index', '')}"
        )

    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            key = _key(item)
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)
            payloads.setdefault(key, item)

    fused = []
    for key, score in sorted(scores.items(), key=lambda pair: pair[1], reverse=True):
        item = dict(payloads[key])
        item["rrf_score"] = score
        fused.append(item)
    return fused


def rerank_hits(
    query: str,
    hits: Sequence[Dict[str, Any]],
    *,
    top_k: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Rerank fused hits with a cross-encoder; fall back on timeout/unavailable."""
    if not hits:
        return []
    reranker = _get_reranker()
    if reranker is None:
        for item in hits:
            item["rerank_status"] = "skipped"
        return list(hits[: top_k or config.retrieval_final_snippets])

    import concurrent.futures

    pairs = [(query, str(hit.get("excerpt") or hit.get("text") or "")) for hit in hits]
    timeout = float(config.retrieval_rerank_timeout_seconds)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                reranker.predict,
                pairs,
                show_progress_bar=False,
            )
            scores = future.result(timeout=timeout)
    except Exception as exc:
        logger.warning("Reranker timed out or failed (%s); keeping RRF order.", exc)
        for item in hits:
            item["rerank_status"] = "skipped"
        return list(hits[: top_k or config.retrieval_final_snippets])

    ranked = sorted(zip(hits, scores), key=lambda pair: float(pair[1]), reverse=True)
    output: List[Dict[str, Any]] = []
    for hit, score in ranked:
        enriched = dict(hit)
        enriched["rerank_score"] = float(score)
        enriched["rerank_status"] = "applied"
        output.append(enriched)
    return output[: top_k or config.retrieval_final_snippets]
