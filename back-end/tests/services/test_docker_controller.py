"""Tests for DockerController — subprocess is mocked."""
import pytest

from app.services.controllers.docker import DockerController, _parse_compose_ps


def test_parse_compose_ps_jsonl():
    raw = '{"Service":"postgres","State":"running"}\n{"Service":"qdrant","State":"exited"}'
    rows = _parse_compose_ps(raw)
    assert len(rows) == 2
    assert rows[0]["Service"] == "postgres"
    assert rows[1]["State"] == "exited"


def test_parse_compose_ps_json_array():
    raw = '[{"Service":"postgres","State":"running"}]'
    rows = _parse_compose_ps(raw)
    assert rows[0]["Service"] == "postgres"


def test_parse_compose_ps_empty():
    assert _parse_compose_ps("") == []
    assert _parse_compose_ps("   \n  ") == []


def test_parse_compose_ps_ignores_garbage_lines():
    raw = 'not json\n{"Service":"redis","State":"running"}\nalso not json'
    rows = _parse_compose_ps(raw)
    assert len(rows) == 1
    assert rows[0]["Service"] == "redis"


@pytest.mark.asyncio
async def test_is_running_true_when_compose_ps_reports_running(monkeypatch):
    ctrl = DockerController(
        "redis", display_name="Redis",
        compose_file="docker-compose.yml", compose_service="redis",
    )

    async def fake_run(*args):
        return 0, '{"Service":"redis","State":"running"}', ""

    monkeypatch.setattr(ctrl, "_run_compose", fake_run)
    assert await ctrl.is_running() is True


@pytest.mark.asyncio
async def test_is_running_false_when_state_exited(monkeypatch):
    ctrl = DockerController(
        "redis", display_name="Redis",
        compose_file="docker-compose.yml", compose_service="redis",
    )

    async def fake_run(*args):
        return 0, '{"Service":"redis","State":"exited"}', ""

    monkeypatch.setattr(ctrl, "_run_compose", fake_run)
    assert await ctrl.is_running() is False


@pytest.mark.asyncio
async def test_is_running_false_on_nonzero_exit(monkeypatch):
    ctrl = DockerController(
        "redis", display_name="Redis",
        compose_file="docker-compose.yml", compose_service="redis",
    )

    async def fake_run(*args):
        return 1, "", "Cannot connect to docker daemon"

    monkeypatch.setattr(ctrl, "_run_compose", fake_run)
    assert await ctrl.is_running() is False


@pytest.mark.asyncio
async def test_start_uses_up_when_use_up_on_start(monkeypatch):
    ctrl = DockerController(
        "n8n", display_name="n8n",
        compose_file="docker-compose.n8n.yml", compose_service="n8n",
        use_up_on_start=True,
    )
    seen_args: list[tuple] = []

    async def fake_run(*args):
        seen_args.append(args)
        return 0, "", ""

    monkeypatch.setattr(ctrl, "_run_compose", fake_run)
    await ctrl.start()
    assert seen_args == [("up", "-d", "n8n")]
    assert ctrl.last_action == "start"
    assert ctrl.last_error is None


@pytest.mark.asyncio
async def test_start_uses_start_when_not_use_up_on_start(monkeypatch):
    ctrl = DockerController(
        "redis", display_name="Redis",
        compose_file="docker-compose.yml", compose_service="redis",
    )
    seen_args: list[tuple] = []

    async def fake_run(*args):
        seen_args.append(args)
        return 0, "", ""

    monkeypatch.setattr(ctrl, "_run_compose", fake_run)
    await ctrl.start()
    assert seen_args == [("start", "redis")]


@pytest.mark.asyncio
async def test_start_raises_and_records_error_on_nonzero(monkeypatch):
    ctrl = DockerController(
        "redis", display_name="Redis",
        compose_file="docker-compose.yml", compose_service="redis",
    )

    async def fake_run(*args):
        return 1, "", "no such service"

    monkeypatch.setattr(ctrl, "_run_compose", fake_run)
    with pytest.raises(RuntimeError, match="no such service"):
        await ctrl.start()
    assert ctrl.last_error == "no such service"


@pytest.mark.asyncio
async def test_stop_invokes_compose_stop(monkeypatch):
    ctrl = DockerController(
        "redis", display_name="Redis",
        compose_file="docker-compose.yml", compose_service="redis",
    )
    seen_args: list[tuple] = []

    async def fake_run(*args):
        seen_args.append(args)
        return 0, "", ""

    monkeypatch.setattr(ctrl, "_run_compose", fake_run)
    await ctrl.stop()
    assert seen_args == [("stop", "redis")]
    assert ctrl.last_action == "stop"
