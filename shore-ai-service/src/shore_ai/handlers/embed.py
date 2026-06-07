"""Embedding gRPC handler wrapping sentence-transformers."""
from __future__ import annotations

import asyncio

from sentence_transformers import SentenceTransformer

from shore_ai._pb import embed_pb2, embed_pb2_grpc


class EmbedHandler(embed_pb2_grpc.EmbedServicer):
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        self.dim = self.model.get_sentence_embedding_dimension()

    def loaded(self) -> bool:
        return self.model is not None

    async def Encode(self, request, context):
        texts = list(request.texts)

        def _encode():
            vecs = self.model.encode(texts, normalize_embeddings=True)
            return vecs.tolist()

        vectors = await asyncio.get_event_loop().run_in_executor(None, _encode)
        return embed_pb2.EncodeResponse(
            vectors=[embed_pb2.Vector(values=v) for v in vectors],
            dim=self.dim,
            model=self.model_name,
        )
