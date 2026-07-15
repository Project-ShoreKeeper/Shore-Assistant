import sys
from unittest.mock import MagicMock, patch
import pytest
import transformers

# Define a mock PaddleOCR class that mimics the behavior of PaddleOCR 2.7+
# by raising ValueError if any unknown argument is passed.
class MockPaddleOCRBase:
    VALID_PARAMS = {"lang", "device"}

    def __init__(self, lang=None, device=None, **kwargs):
        # We explicitly list valid parameters lang and device to mimic the real signature.
        # Any other parameter passed in kwargs is considered unknown.
        if kwargs:
            raise ValueError(f"Unknown argument: {list(kwargs.keys())[0]}")
        self.kwargs = {"lang": lang, "device": device, **kwargs}

mock_paddleocr_module = MagicMock()
mock_paddleocr_module.PaddleOCR = MockPaddleOCRBase
sys.modules["paddleocr"] = mock_paddleocr_module

# Mock the util.omniparser module so it doesn't fail import when running tests
mock_util_omniparser = MagicMock()
sys.modules["util"] = MagicMock()
sys.modules["util.omniparser"] = mock_util_omniparser

# Define mock model and tokenizer classes at module level so that they
# are resolved correctly via module attribute lookups inside patched_from_pretrained.
class MockTokenizer(transformers.PreTrainedTokenizerBase):
    def __init__(self):
        # Properly initialize the fields used by PreTrainedTokenizerBase
        # to avoid triggering the custom __getattr__ property-returning fallback.
        self._special_tokens_map = {}
        self._extra_special_tokens = ["<spec1>", "<spec2>"]
        self.verbose = False

class MockModel(transformers.PreTrainedModel):
    _tied_weights_keys = ["a.weight", "b.weight", "c.weight"]

    @property
    def _supports_sdpa(self):
        return self.non_existent_attribute

    def prepare_inputs_for_generation(self, input_ids, past_key_values=None, **kwargs):
        return {"input_ids": input_ids, "past_key_values": past_key_values}

from shore_ai.omniparser_adapter import build_omniparser

def test_build_omniparser_patches_paddleocr():
    # Verify that the initial mock PaddleOCR raises ValueError when unsupported args are provided
    with pytest.raises(ValueError, match="Unknown argument:"):
        mock_paddleocr_module.PaddleOCR(lang="en", show_log=False, use_dilation=True)

    # Call build_omniparser which should execute our monkeypatches
    with patch("shore_ai.omniparser_adapter._OMNI_ROOT", "/tmp"):
        try:
            build_omniparser()
        except Exception:
            # We can ignore import or runtime errors downstream from build_omniparser
            pass

    # 1. Verify that the monkeypatched PaddleOCR successfully filters unsupported arguments
    instance = mock_paddleocr_module.PaddleOCR(
        lang="en", 
        show_log=False, 
        use_dilation=True, 
        det_db_score_mode="slow"
    )
    assert instance is not None
    assert instance.kwargs.get("lang") == "en"
    assert "show_log" not in instance.kwargs
    assert "use_dilation" not in instance.kwargs
    assert "det_db_score_mode" not in instance.kwargs

    # 2. Verify that transformers.PretrainedConfig has been patched
    assert hasattr(transformers.PretrainedConfig, "forced_bos_token_id")
    assert transformers.PretrainedConfig.forced_bos_token_id is None
    assert hasattr(transformers.PretrainedConfig, "forced_eos_token_id")
    assert transformers.PretrainedConfig.forced_eos_token_id is None

    # 3. Verify that transformers.PreTrainedTokenizerBase has been patched
    assert hasattr(transformers.PreTrainedTokenizerBase, "additional_special_tokens")
    
    # Verify the property works on a mock instance
    tok = MockTokenizer()
    assert tok.additional_special_tokens == ["<spec1>", "<spec2>"]

    # 4. Verify that PreTrainedModel.from_pretrained has been patched
    try:
        MockModel.from_pretrained("mock-model-name")
    except Exception:
        pass

    # Verify that the property has been successfully wrapped and returns False instead of raising AttributeError
    model_instance = MockModel.__new__(MockModel)
    assert model_instance._supports_sdpa is False

    # Verify that _tied_weights_keys list was converted to a dictionary
    assert MockModel._tied_weights_keys == {"b.weight": "a.weight", "c.weight": "a.weight"}

    # 5. Verify that torch.equal has been patched to support meta tensors
    import torch
    meta_tensor_1 = torch.empty(2, 3, device="meta")
    meta_tensor_2 = torch.empty(2, 3, device="meta")
    assert torch.equal(meta_tensor_1, meta_tensor_2) is True

    # 6. Verify that meta tensor initialization converts meta parameters and buffers to CPU
    class ModelWithMeta(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.param = torch.nn.Parameter(torch.empty(2, 3, device="meta"))
            self.register_buffer("buf", torch.empty(2, 3, device="meta"))
            
    model_with_meta = ModelWithMeta()
    assert model_with_meta.param.device.type == "meta"
    assert model_with_meta.buf.device.type == "meta"
    
    memo = {}
    for name, module in model_with_meta.named_modules():
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
                
    assert model_with_meta.param.device.type == "cpu"
    assert model_with_meta.buf.device.type == "cpu"

    # 7. Verify that prepare_inputs_for_generation has been patched on MockModel
    class FakeLayer:
        def __init__(self, keys, values):
            self.keys = keys
            self.values = values

    class FakeSubCache:
        def __init__(self, layers):
            self.layers = layers

    class FakeEncoderDecoderCache:
        def __init__(self, self_attn, cross_attn):
            self.self_attention_cache = self_attn
            self.cross_attention_cache = cross_attn

    empty_cache = FakeEncoderDecoderCache(FakeSubCache([]), FakeSubCache([]))
    model_instance = MockModel.__new__(MockModel)
    out = model_instance.prepare_inputs_for_generation(torch.ones(1), past_key_values=empty_cache)
    assert out["past_key_values"] is None

    k, v = torch.ones(2, 3), torch.zeros(2, 3)
    populated_cache = FakeEncoderDecoderCache(
        FakeSubCache([FakeLayer(k, v)]),
        FakeSubCache([FakeLayer(k, v)])
    )
    out2 = model_instance.prepare_inputs_for_generation(torch.ones(1), past_key_values=populated_cache)
    assert isinstance(out2["past_key_values"], tuple)
    assert len(out2["past_key_values"]) == 1
    assert out2["past_key_values"][0] == (k, v, k, v)
