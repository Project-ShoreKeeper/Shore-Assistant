from app.services.ai_client.channel import BearerMetadataPlugin


def test_bearer_metadata_plugin_emits_header():
    plugin = BearerMetadataPlugin(token="abc")
    captured: list = []

    def _callback(metadata, error):
        captured.append((metadata, error))

    plugin(context=None, callback=_callback)
    assert len(captured) == 1
    metadata, error = captured[0]
    assert error is None
    assert ("authorization", "Bearer abc") in metadata
