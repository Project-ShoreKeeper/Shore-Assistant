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

    # Patch PaddleOCR to avoid "ValueError: Unknown argument" errors in newer paddleocr versions.
    try:
        import paddleocr
        import inspect
        original_paddle_ocr = paddleocr.PaddleOCR

        class PatchedPaddleOCR(original_paddle_ocr):  # type: ignore
            def __init__(self, *args, **kwargs):
                # 1. Get valid parameters from original __init__ signature
                try:
                    sig = inspect.signature(original_paddle_ocr.__init__)
                    allowed_keys = {
                        name for name, param in sig.parameters.items()
                        if param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
                    }
                except Exception:
                    allowed_keys = set()

                # 2. Add deprecated mappings
                try:
                    import paddleocr._pipelines.ocr as ocr_pipeline
                    deprecated_map = getattr(ocr_pipeline, "_DEPRECATED_PARAM_NAME_MAPPING", {})
                    allowed_keys.update(deprecated_map.keys())
                except Exception:
                    pass

                # 3. Add valid common args for execution engine
                common_args = {
                    "device", "engine", "engine_config", "enable_hpi", "use_tensorrt",
                    "precision", "enable_mkldnn", "mkldnn_cache_capacity", "cpu_threads", "enable_cinn"
                }
                allowed_keys.update(common_args)

                # Filter kwargs to only include valid parameters
                filtered_kwargs = {k: v for k, v in kwargs.items() if k in allowed_keys}
                discarded = kwargs.keys() - filtered_kwargs.keys()
                if discarded:
                    log.info("PaddleOCR monkeypatch: discarding unsupported arguments: %s", discarded)

                super().__init__(*args, **filtered_kwargs)

        paddleocr.PaddleOCR = PatchedPaddleOCR
    except Exception as e:
        log.warning("Failed to patch PaddleOCR: %s", e)

    # Patch transformers to avoid compatibility errors with transformers v5.
    try:
        import torch
        original_torch_equal = torch.equal
        def patched_torch_equal(self, other):
            try:
                if (hasattr(self, "device") and self.device.type == "meta") or (hasattr(other, "device") and other.device.type == "meta"):
                    return self is other or (self.shape == other.shape and self.dtype == other.dtype)
                return original_torch_equal(self, other)
            except Exception:
                return self is other
        torch.equal = patched_torch_equal

        import transformers
        # 1. Florence2LanguageConfig 'forced_bos_token_id' AttributeError
        transformers.PretrainedConfig.forced_bos_token_id = None
        transformers.PretrainedConfig.forced_eos_token_id = None

        # 2. RobertaTokenizer 'additional_special_tokens' AttributeError
        if not hasattr(transformers.PreTrainedTokenizerBase, "additional_special_tokens"):
            @property
            def _ast(self):
                return getattr(self, "extra_special_tokens", [])
            transformers.PreTrainedTokenizerBase.additional_special_tokens = _ast

        # 3. Florence2ForConditionalGeneration '_supports_sdpa' and '_tied_weights_keys' compatibility with transformers v5
        original_from_pretrained = transformers.PreTrainedModel.__dict__["from_pretrained"]

        @classmethod
        def patched_from_pretrained(cls, *args, **kwargs):
            def cache_to_legacy_tuple(cache):
                if cache is None:
                    return None
                if isinstance(cache, (tuple, list)):
                    return cache
                self_cache = getattr(cache, "self_attention_cache", None)
                cross_cache = getattr(cache, "cross_attention_cache", None)
                if self_cache is None or cross_cache is None:
                    return cache
                
                if len(self_cache.layers) == 0:
                    return None
                    
                legacy_tuple = []
                num_layers = len(self_cache.layers)
                for i in range(num_layers):
                    self_layer = self_cache.layers[i]
                    if self_layer.keys is None:
                        return None
                    cross_layer = cross_cache.layers[i] if i < len(cross_cache.layers) else None
                    layer_tuple = (
                        self_layer.keys,
                        self_layer.values,
                        cross_layer.keys if cross_layer is not None else None,
                        cross_layer.values if cross_layer is not None else None,
                    )
                    legacy_tuple.append(layer_tuple)
                return tuple(legacy_tuple)

            module_name = cls.__module__
            import sys
            mod = sys.modules.get(module_name)
            classes_to_patch = []
            if mod:
                for attr in dir(mod):
                    try:
                        c = getattr(mod, attr)
                        if isinstance(c, type) and issubclass(c, transformers.PreTrainedModel):
                            classes_to_patch.append(c)
                    except Exception:
                        pass
            else:
                classes_to_patch = [cls]

            for c in classes_to_patch:
                for base in c.__mro__:
                    if "_supports_sdpa" in base.__dict__:
                        val = base.__dict__["_supports_sdpa"]
                        if isinstance(val, property):
                            original_fget = val.fget
                            def make_safe_fget(fget):
                                def safe_fget(self):
                                    try:
                                        return fget(self)
                                    except AttributeError:
                                        return False
                                return safe_fget
                            setattr(base, "_supports_sdpa", property(make_safe_fget(original_fget)))

                    if "_tied_weights_keys" in base.__dict__:
                        val = base.__dict__["_tied_weights_keys"]
                        if isinstance(val, list):
                            if base.__name__ == "Florence2LanguageModel":
                                new_val = {"decoder.embed_tokens.weight": "encoder.embed_tokens.weight"}
                            elif base.__name__ == "Florence2LanguageForConditionalGeneration":
                                new_val = {
                                    "model.decoder.embed_tokens.weight": "model.encoder.embed_tokens.weight",
                                    "lm_head.weight": "model.encoder.embed_tokens.weight"
                                }
                            elif base.__name__ == "Florence2ForConditionalGeneration":
                                new_val = {
                                    "language_model.model.decoder.embed_tokens.weight": "language_model.model.encoder.embed_tokens.weight",
                                    "language_model.lm_head.weight": "language_model.model.encoder.embed_tokens.weight"
                                }
                            else:
                                if len(val) > 1:
                                    new_val = {k: val[0] for k in val[1:]}
                                else:
                                    new_val = {}
                            setattr(base, "_tied_weights_keys", new_val)

                    if "prepare_inputs_for_generation" in base.__dict__:
                        original_prep = base.__dict__["prepare_inputs_for_generation"]
                        if not getattr(original_prep, "_is_patched", False):
                            def make_patched_prepare_inputs(orig_prep, klass):
                                def patched_prepare_inputs(self, *args, **kwargs):
                                    if "past_key_values" in kwargs:
                                        kwargs["past_key_values"] = cache_to_legacy_tuple(kwargs["past_key_values"])
                                    elif len(args) > 1:
                                        args = list(args)
                                        args[1] = cache_to_legacy_tuple(args[1])
                                        args = tuple(args)
                                    return orig_prep.__get__(self, klass)(*args, **kwargs)
                                patched_prepare_inputs._is_patched = True
                                return patched_prepare_inputs
                            setattr(base, "prepare_inputs_for_generation", make_patched_prepare_inputs(original_prep, base))

            model = original_from_pretrained.__get__(None, cls)(*args, **kwargs)

            # Initialize any remaining meta parameters or buffers to avoid NotImplementedError on .to(device)
            memo = {}
            for name, module in model.named_modules():
                for param_name, param in list(module.named_parameters(recurse=False)):
                    if param.device.type == "meta":
                        param_id = id(param)
                        if param_id not in memo:
                            new_data = torch.empty(param.shape, dtype=param.dtype, device="cpu")
                            torch.nn.init.normal_(new_data, std=0.02)
                            memo[param_id] = torch.nn.Parameter(new_data, requires_grad=param.requires_grad)
                        module.register_parameter(param_name, memo[param_id])

                for buffer_name, buffer in list(module.named_buffers(recurse=False)):
                    if buffer.device.type == "meta":
                        buffer_id = id(buffer)
                        if buffer_id not in memo:
                            memo[buffer_id] = torch.zeros(buffer.shape, dtype=buffer.dtype, device="cpu")
                        module.register_buffer(buffer_name, memo[buffer_id])

            return model

        transformers.PreTrainedModel.from_pretrained = patched_from_pretrained
    except Exception as e:
        log.warning("Failed to patch transformers: %s", e)

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
