"""Tests for ServiceManager — YAML load, concurrency, conflict handling."""
import asyncio
from pathlib import Path

import pytest
import yaml

from app.services.controllers.base import Controller, ServiceKind
from app.services.service_manager import (
    ServiceConflict,
    ServiceManager,
    ServiceNotFound,
)


class _FakeCtrl(Controller):
    def __init__(self, name="fake", *, display_name="fake", running=False, slow=False):
        super().__init__(name, display_name=display_name)
        self._running = running
        self._slow = slow

    @property
    def kind(self) -> ServiceKind:
        return "internal"

    async def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._slow:
            await asyncio.sleep(0.2)
        self._running = True

    async def stop(self) -> None:
        if self._slow:
            await asyncio.sleep(0.2)
        self._running = False


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_load_missing_file_is_noop(tmp_path):
    mgr = ServiceManager(registry_path=tmp_path / "nope.yaml")
    mgr.load()
    assert mgr.names() == []


def test_load_parse_error_yields_empty_registry(tmp_path):
    p = tmp_path / "broken.yaml"
    p.write_text("not: : yaml ::", encoding="utf-8")
    mgr = ServiceManager(registry_path=p)
    mgr.load()
    assert mgr.names() == []


def test_load_top_level_not_mapping_yields_empty(tmp_path):
    p = tmp_path / "list.yaml"
    p.write_text("services:\n  - a\n  - b\n", encoding="utf-8")
    mgr = ServiceManager(registry_path=p)
    mgr.load()
    assert mgr.names() == []


def test_load_valid_internal_entries(tmp_path):
    p = tmp_path / "services.yaml"
    _write_yaml(p, {
        "services": {
            "locomo-worker": {
                "kind": "internal", "display_name": "LOCOMO worker",
                "target": "locomo_worker",
            },
            "canonicalizer": {
                "kind": "internal", "display_name": "Canonicalizer",
                "target": "canonicalizer",
            },
        },
    })
    mgr = ServiceManager(registry_path=p)
    mgr.load()
    assert set(mgr.names()) == {"locomo-worker", "canonicalizer"}


def test_load_skips_bad_entries_keeps_good(tmp_path):
    p = tmp_path / "services.yaml"
    _write_yaml(p, {
        "services": {
            "good": {
                "kind": "internal", "display_name": "Good",
                "target": "locomo_worker",
            },
            "bad-kind": {"kind": "wat"},
            "missing-fields": {"kind": "internal"},
        },
    })
    mgr = ServiceManager(registry_path=p)
    mgr.load()
    assert mgr.names() == ["good"]


@pytest.mark.asyncio
async def test_start_unknown_name_raises_not_found(tmp_path):
    mgr = ServiceManager(registry_path=tmp_path / "x.yaml")
    mgr.load()
    with pytest.raises(ServiceNotFound):
        await mgr.start("nope")


def _seed_manager_with(ctrl: _FakeCtrl) -> ServiceManager:
    mgr = ServiceManager(registry_path=Path("/tmp/never"))
    mgr._controllers[ctrl.name] = ctrl
    mgr._locks[ctrl.name] = asyncio.Lock()
    return mgr


@pytest.mark.asyncio
async def test_start_conflict_when_already_running():
    ctrl = _FakeCtrl(running=True)
    mgr = _seed_manager_with(ctrl)
    with pytest.raises(ServiceConflict):
        await mgr.start("fake")


@pytest.mark.asyncio
async def test_stop_conflict_when_already_stopped():
    ctrl = _FakeCtrl(running=False)
    mgr = _seed_manager_with(ctrl)
    with pytest.raises(ServiceConflict):
        await mgr.stop("fake")


@pytest.mark.asyncio
async def test_concurrent_start_second_caller_gets_conflict():
    ctrl = _FakeCtrl(slow=True)
    mgr = _seed_manager_with(ctrl)
    task = asyncio.create_task(mgr.start("fake"))
    await asyncio.sleep(0.01)  # let task add itself to transitioning
    with pytest.raises(ServiceConflict):
        await mgr.start("fake")
    await task
    assert ctrl._running is True


@pytest.mark.asyncio
async def test_schedule_start_returns_immediately_and_runs_in_background():
    ctrl = _FakeCtrl(slow=True)
    mgr = _seed_manager_with(ctrl)
    task = mgr.schedule_start("fake")
    # Should return immediately, not block on the slow controller.
    assert not task.done()
    await task
    assert ctrl._running is True


@pytest.mark.asyncio
async def test_schedule_start_unknown_raises_synchronously(tmp_path):
    mgr = ServiceManager(registry_path=tmp_path / "x.yaml")
    mgr.load()
    with pytest.raises(ServiceNotFound):
        mgr.schedule_start("nope")


@pytest.mark.asyncio
async def test_schedule_start_conflict_when_transitioning():
    ctrl = _FakeCtrl(slow=True)
    mgr = _seed_manager_with(ctrl)
    task = mgr.schedule_start("fake")
    with pytest.raises(ServiceConflict):
        mgr.schedule_start("fake")
    await task


@pytest.mark.asyncio
async def test_list_state_includes_transitioning_flag():
    ctrl = _FakeCtrl(slow=True)
    mgr = _seed_manager_with(ctrl)
    task = asyncio.create_task(mgr.start("fake"))
    await asyncio.sleep(0.01)
    states = await mgr.list_state()
    assert len(states) == 1
    assert states[0].transitioning is True
    await task
    states = await mgr.list_state()
    assert states[0].transitioning is False
    assert states[0].running is True


@pytest.mark.asyncio
async def test_has_and_get_state():
    ctrl = _FakeCtrl(running=True)
    mgr = _seed_manager_with(ctrl)
    assert mgr.has("fake") is True
    st = await mgr.get_state("fake")
    assert st.name == "fake"
    assert st.running is True
    with pytest.raises(ServiceNotFound):
        await mgr.get_state("absent")
