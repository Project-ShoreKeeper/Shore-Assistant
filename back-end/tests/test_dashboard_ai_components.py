from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


def test_dashboard_ai_components_present(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.AUTH_ENABLED", False)
    fake_health = {
        "ready": True,
        "version": "0.1.0",
        "components": [
            {"name": "stt", "loaded": True, "detail": "base"},
            {"name": "tts", "loaded": False, "detail": "af_heart"},
            {"name": "embed", "loaded": True, "detail": "all-MiniLM-L6-v2"},
        ],
    }
    with patch(
        "app.api.endpoints.dashboard.health_client.get",
        new=AsyncMock(return_value=fake_health),
    ):
        client = TestClient(app)
        r = client.get("/api/dashboard")

    assert r.status_code == 200
    body = r.json()
    assert "ai_components" in body
    names = {c["name"] for c in body["ai_components"]}
    assert names == {"stt", "tts", "embed"}
    stt_row = next(c for c in body["ai_components"] if c["name"] == "stt")
    assert stt_row["loaded"] is True
    assert stt_row["detail"] == "base"
