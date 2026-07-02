from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.api.endpoints.dashboard import _parse_remote_ssh_snapshot


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


def test_parse_remote_ssh_snapshot_windows_nvidia_smi():
    hardware = _parse_remote_ssh_snapshot(
        "\n".join([
            "CPU_PCT=12.5",
            "RAM_TOTAL_KB=16702668",
            "RAM_FREE_KB=8123456",
            "DISK_FREE_BYTES=536870912000",
            "DISK_TOTAL_BYTES=1073741824000",
            "UPTIME_SECONDS=3600",
            "GPU_CSV_BEGIN",
            "NVIDIA GeForce RTX 5060 Ti, 7, 2210, 16311, 47",
        ])
    )

    assert hardware["cpu_pct"] == 12.5
    assert hardware["ram_total_gb"] == 15.93
    assert hardware["disk_free_gb"] == 500.0
    assert hardware["disk_pct"] == 50.0
    assert hardware["uptime_seconds"] == 3600
    assert hardware["gpu"] == [{
        "name": "NVIDIA GeForce RTX 5060 Ti",
        "util_pct": 7.0,
        "vram_used_mb": 2210.0,
        "vram_total_mb": 16311.0,
        "temp_c": 47.0,
    }]
