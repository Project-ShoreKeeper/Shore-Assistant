"""Adapter over the vendored microsoft/OmniParser stack.

Produces the `parser(image_bytes) -> (elements, som_jpeg)` callable the
ScreenParseHandler expects. Imports OmniParser lazily so importing this module
is cheap; the models load only when build_omniparser() is called.

OmniParser is cloned into /opt/OmniParser in the Docker image (see Dockerfile)
and added to PYTHONPATH. Weights live under /opt/OmniParser/weights.
"""
from __future__ import annotations

import base64
import io
import logging
import os

log = logging.getLogger(__name__)

_OMNI_ROOT = os.environ.get("OMNIPARSER_ROOT", "/opt/OmniParser")


def build_omniparser(device: str = "cuda", box_threshold: float = 0.05):
    """Construct the OmniParser callable. Heavy — call inside an executor.

    NOTE: the exact OmniParser `parse()` return shape and parsed-item keys
    (`bbox`, `content`, `interactivity`, `type`) must be verified against the
    pinned commit at deploy time. If the pinned commit (Dockerfile
    OMNIPARSER_REF) differs and its API changed, adjust the mapping in `parse()`
    below only — the handler contract stays fixed.
    """
    import sys
    if _OMNI_ROOT not in sys.path:
        sys.path.insert(0, _OMNI_ROOT)

    from util.omniparser import Omniparser  # type: ignore

    config = {
        "som_model_path": os.path.join(_OMNI_ROOT, "weights/icon_detect/model.pt"),
        "caption_model_name": "florence2",
        "caption_model_path": os.path.join(_OMNI_ROOT, "weights/icon_caption_florence"),
        "BOX_TRESHOLD": box_threshold,
        "device": device,
    }
    omni = Omniparser(config)

    def parse(image_bytes: bytes):
        b64 = base64.b64encode(image_bytes).decode("ascii")
        # Omniparser.parse returns (annotated_image_base64, parsed_content_list)
        som_b64, parsed = omni.parse(b64)
        elements = []
        for item in parsed:
            bbox = item.get("bbox", [0.0, 0.0, 0.0, 0.0])
            elements.append({
                "type": item.get("type", "icon"),
                "content": item.get("content", "") or "",
                "interactable": bool(item.get("interactivity", item.get("interactable", False))),
                "bbox": [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])],
            })
        som_jpeg = _to_jpeg(som_b64)
        return elements, som_jpeg

    return parse


def _to_jpeg(som_b64: str) -> bytes:
    """OmniParser returns a base64 PNG/whatever; re-encode to JPEG bytes."""
    from PIL import Image
    raw = base64.b64decode(som_b64)
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()
