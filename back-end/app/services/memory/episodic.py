"""Episodic memory — Qdrant async client over distilled facts + emotion."""
import hashlib
import time
import uuid
from typing import Optional

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qm
from qdrant_client.http.exceptions import UnexpectedResponse

from app.core.config import settings
from app.services.memory.embedder import embedder
from app.services.memory.types import EmotionVector, EpisodicFact, ScoredFact


_NAMESPACE_FACT = uuid.UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")


def _fact_point_id(fact: EpisodicFact) -> str:
    """Deterministic uuid5 based on turn timestamp, role, and fact text hash.
    Re-upserting the same fact yields the same id, so the worker (Phase 3)
    is idempotent across restarts.
    """
    fact_hash = hashlib.sha1(fact.fact.encode("utf-8")).hexdigest()[:16]
    name = f"{fact.source_turn_ts}:{fact.source_role}:{fact_hash}"
    return str(uuid.uuid5(_NAMESPACE_FACT, name))


class EpisodicMemory:
    def __init__(self):
        self._client: Optional[AsyncQdrantClient] = None

    async def startup(self) -> None:
        self._client = AsyncQdrantClient(url=settings.QDRANT_URL)
        await self._ensure_collection()

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def _ensure_collection(self) -> None:
        coll = settings.QDRANT_COLLECTION
        existing = {
            c.name
            for c in (await self._client.get_collections()).collections
        }
        if coll in existing:
            return
        await self._client.create_collection(
            collection_name=coll,
            vectors_config=qm.VectorParams(
                size=embedder.DIM,
                distance=qm.Distance.COSINE,
                on_disk=True,
            ),
        )
        await self._client.create_payload_index(
            collection_name=coll,
            field_name="entity_tags",
            field_schema=qm.PayloadSchemaType.KEYWORD,
        )
        await self._client.create_payload_index(
            collection_name=coll,
            field_name="created_at",
            field_schema=qm.PayloadSchemaType.FLOAT,
        )
        await self._client.create_payload_index(
            collection_name=coll,
            field_name="valence",
            field_schema=qm.PayloadSchemaType.FLOAT,
        )
        print(f"[Memory] Created Qdrant collection '{coll}'")

    async def upsert(self, fact: EpisodicFact) -> str:
        vec = await embedder.encode(fact.fact)
        point_id = _fact_point_id(fact)
        payload = {
            "fact": fact.fact,
            "entity_tags": fact.entity_tags,
            "emotion": fact.emotion.model_dump(),
            "valence": fact.emotion.valence,
            "source_turn_ts": fact.source_turn_ts,
            "source_role": fact.source_role,
            "created_at": time.time(),
            "confidence": fact.confidence,
            "embedding_model_version": settings.TOOL_RETRIEVER_MODEL,
        }
        await self._client.upsert(
            collection_name=settings.QDRANT_COLLECTION,
            points=[qm.PointStruct(id=point_id, vector=vec, payload=payload)],
        )
        return point_id

    async def search(
        self,
        query: str,
        entity_filter: list[str] | None = None,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> list[ScoredFact]:
        top_k = top_k or settings.MEMORY_EPISODIC_TOP_K
        min_score = (
            min_score if min_score is not None
            else settings.MEMORY_EPISODIC_MIN_SCORE
        )
        vec = await embedder.encode(query)
        qf: qm.Filter | None = None
        if entity_filter:
            qf = qm.Filter(
                must=[qm.FieldCondition(
                    key="entity_tags",
                    match=qm.MatchAny(any=entity_filter),
                )]
            )
        hits = await self._client.search(
            collection_name=settings.QDRANT_COLLECTION,
            query_vector=vec,
            query_filter=qf,
            limit=top_k,
            score_threshold=min_score,
        )
        results: list[ScoredFact] = []
        for h in hits:
            p = h.payload
            fact = EpisodicFact(
                fact=p["fact"],
                entity_tags=p["entity_tags"],
                emotion=EmotionVector(**p["emotion"]),
                source_turn_ts=p["source_turn_ts"],
                source_role=p["source_role"],
                confidence=p["confidence"],
            )
            results.append(ScoredFact(fact=fact, score=h.score))
        return results

    async def count(self) -> int:
        if self._client is None:
            return 0
        info = await self._client.count(
            collection_name=settings.QDRANT_COLLECTION, exact=True,
        )
        return info.count

    async def health(self) -> bool:
        if self._client is None:
            return False
        try:
            await self._client.get_collections()
            return True
        except (UnexpectedResponse, OSError):
            return False
