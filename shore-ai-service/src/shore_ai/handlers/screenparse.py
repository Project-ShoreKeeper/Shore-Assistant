"""ScreenParse gRPC handler wrapping OmniParser v2.

The heavy OmniParser stack (YOLO icon detector + Florence-2 captioner + OCR)
is injected as a `parser` callable so this handler stays import-light and
unit-testable without models or a GPU. `server.py` builds the real callable
lazily in a background thread (STT load pattern).

parser contract:
    parse(image_bytes: bytes) -> tuple[list[dict], bytes]
    each element dict: {type, content, interactable, bbox=[x1,y1,x2,y2]}
    bbox floats are normalized 0..1; second tuple item is annotated JPEG bytes.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Optional

import grpc

from shore_ai._pb import screenparse_pb2, screenparse_pb2_grpc

log = logging.getLogger(__name__)

Parser = Callable[[bytes], "tuple[list[dict], bytes]"]


class ScreenParseHandler(screenparse_pb2_grpc.ScreenParseServicer):
    def __init__(self, parser: Optional[Parser] = None, device: str = "cuda"):
        self.parser = parser
        self.device = device

    def loaded(self) -> bool:
        return self.parser is not None

    async def Parse(self, request, context):
        if self.parser is None:
            if context is not None:
                await context.abort(
                    grpc.StatusCode.UNAVAILABLE, "screenparse model still loading",
                )
            raise RuntimeError("screenparse model still loading")

        image = request.image
        t0 = time.perf_counter()

        def _run():
            return self.parser(image)

        elements, som_jpeg = await asyncio.get_event_loop().run_in_executor(
            None, _run
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0

        proto_elems = []
        for i, el in enumerate(elements):
            bbox = el.get("bbox", [0.0, 0.0, 0.0, 0.0])
            proto_elems.append(
                screenparse_pb2.Element(
                    id=i,
                    type=str(el.get("type", "")),
                    content=str(el.get("content", "")),
                    interactable=bool(el.get("interactable", False)),
                    x1=float(bbox[0]), y1=float(bbox[1]),
                    x2=float(bbox[2]), y2=float(bbox[3]),
                )
            )
        from PIL import Image
        import io
        try:
            img = Image.open(io.BytesIO(image))
            w, h = img.size
        except Exception as e:
            log.warning("Failed to parse image size: %s", e)
            w, h = 0, 0

        return screenparse_pb2.ParseResponse(
            elements=proto_elems,
            som_image_jpeg=som_jpeg or b"",
            width=w,
            height=h,
            latency_ms=latency_ms,
        )
