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
_BGE_QUERY_PREFIX = "query: "
_BGE_PASSAGE_PREFIX = "passage: "
_BGE_VECTOR_DIM = 384


def _get_embedder():
    global _EMBEDDER
    if _EMBEDDER is not None:
        return _EMBEDDER
    try:
        from sentence_transformers import SentenceTransformer

        _EMBEDDER = SentenceTransformer(config.retrieval_embedding_model)
        return _EMBEDDER
    except Exception as exc:
        logger.warning("Semantic embedder unavailable: %s", exc)
        return None


def _get_reranker():
    global _RERANKER
    if _RERANKER is not None:
        return _RERANKER
    try:
        from sentence_transformers import CrossEncoder

        _RERANKER = CrossEncoder(config.retrieval_rerank_model)
        return _RERANKER
    except Exception as exc:
        logger.warning("Cross-encoder reranker unavailable: %s", exc)
        return None


def _encode_passages(texts: Sequence[str]) -> List[List[float]]:
    model = _get_embedder()
    if model is None or not texts:
        return []
    prefixed = [f"{_BGE_PASSAGE_PREFIX}{text}" for text in texts]
    vectors = model.encode(prefixed, normalize_embeddings=True, show_progress_bar=False)
    return [vector.tolist() for vector in vectors]


def _encode_query(text: str) -> Optional[List[float]]:
    model = _get_embedder()
    if model is None or not text:
        return None
    vector = model.encode(
        f"{_BGE_QUERY_PREFIX}{text}",
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vector.tolist()


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
        return self._available and self._client is not None

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

            self._client = QdrantClient(host=self.host, port=self.port, timeout=10.0)
            if not self._client.collection_exists(self.collection_name):
                self._client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=qmodels.VectorParams(
                        size=_BGE_VECTOR_DIM,
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
        return {
            "session_id": self.session_id,
            "collection_name": self.collection_name,
            "host": self.host,
            "port": self.port,
            "status": self._status,
            "available": self.is_available(),
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
