"""Canonicalizer — nightly entity-tag dedup over the episodic Qdrant collection.

Greedy clustering by cosine similarity. For each cluster, picks the
shortest member as the canonical tag and replaces all occurrences in
existing point payloads in place.
"""
import numpy as np

from app.core.config import settings
from app.services.memory.embedder import embedder
from app.services.memory.facade import memory_facade


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _cluster_tags(
    vectors: dict[str, np.ndarray], threshold: float,
) -> dict[str, list[str]]:
    """Greedy single-pass clustering. Returns {canonical_tag: [members...]}."""
    tags = sorted(vectors.keys(), key=lambda t: (len(t), t))
    clusters: dict[str, list[str]] = {}
    for tag in tags:
        v = vectors[tag]
        matched = None
        for canonical in clusters:
            if _cosine(v, vectors[canonical]) >= threshold:
                matched = canonical
                break
        if matched is None:
            clusters[tag] = [tag]
        else:
            clusters[matched].append(tag)
    return clusters


async def run_canonicalization() -> dict:
    if not settings.CANONICALIZER_ENABLED:
        return {"status": "disabled"}
    client = memory_facade.episodic._client
    if client is None:
        return {"status": "no_client"}

    # 1. Scroll all points (single-user scale — fits in memory).
    points: list = []
    offset = None
    while True:
        page, offset = await client.scroll(
            collection_name=settings.QDRANT_COLLECTION,
            with_payload=True, with_vectors=False, limit=512, offset=offset,
        )
        points.extend(page)
        if offset is None:
            break

    # 2. Collect unique tags + embed them.
    unique_tags = sorted({
        t for p in points for t in p.payload.get("entity_tags", [])
    })
    if not unique_tags:
        return {"status": "ok", "points": 0, "clusters": 0, "tags": 0}
    vecs = await embedder.encode_many(unique_tags)
    vectors = {t: np.array(v) for t, v in zip(unique_tags, vecs)}

    # 3. Cluster greedily.
    clusters = _cluster_tags(
        vectors, threshold=settings.CANONICALIZER_SIMILARITY_THRESHOLD,
    )
    tag_to_canonical = {
        member: canonical
        for canonical, members in clusters.items()
        for member in members
    }

    # 4. Rewrite every point — ensures tags are canonical (sorted, deduped,
    #    remapped) and idempotent; skips points with no entity_tags.
    updated = 0
    for p in points:
        old_tags: list = p.payload.get("entity_tags", [])
        if not old_tags:
            continue
        new_tags = sorted({tag_to_canonical.get(t, t) for t in old_tags})
        await client.set_payload(
            collection_name=settings.QDRANT_COLLECTION,
            payload={"entity_tags": new_tags},
            points=[p.id],
        )
        updated += 1

    return {
        "status": "ok",
        "points": len(points),
        "tags": len(unique_tags),
        "clusters": len(clusters),
        "updated": updated,
    }
