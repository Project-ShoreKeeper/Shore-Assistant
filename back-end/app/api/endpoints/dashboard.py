"""Dashboard endpoint — aggregate status of services, databases, hardware, workers.

One GET call returns everything needed to render the /dashboard page. Each
probe is wrapped in try/except so a single backend failure cannot blank the
whole UI.
"""
import asyncio
import shutil
import subprocess
import time
from typing import Any, Optional

import httpx
import psutil
from fastapi import APIRouter, Depends

from app.api.deps import current_user
from app.core.config import settings
from app.services.memory import memory_facade, worker_service
from app.services.scheduler_service import scheduler_service
from app.services.service_manager import service_manager
from app.services.ai_client.health import health_client
from app.services.terminal_service import terminal_service

# Any logged-in user can read the dashboard.
router = APIRouter(
    prefix="/api", tags=["dashboard"],
    dependencies=[Depends(current_user)],
)


# ── Helpers ────────────────────────────────────────────────────────────

async def _http_probe(url: str, timeout: float = 2.0) -> tuple[str, Optional[float]]:
    """Returns (status, latency_ms). status ∈ {'up','down'}."""
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url)
            if r.status_code < 500:
                return "up", round((time.perf_counter() - t0) * 1000, 1)
            return "down", None
    except Exception:
        return "down", None


async def _measure(coro) -> tuple[bool, Optional[float]]:
    """Run an async health() and measure latency."""
    t0 = time.perf_counter()
    try:
        ok = await coro
        return bool(ok), round((time.perf_counter() - t0) * 1000, 1)
    except Exception:
        return False, None


def _nvidia_smi_gpu() -> list[dict]:
    """Query GPUs via `nvidia-smi`. Returns [] if not available."""
    if shutil.which("nvidia-smi") is None:
        return []
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode != 0:
            return []
        gpus = []
        for line in out.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 5:
                continue
            try:
                gpus.append({
                    "name": parts[0],
                    "util_pct": float(parts[1]),
                    "vram_used_mb": float(parts[2]),
                    "vram_total_mb": float(parts[3]),
                    "temp_c": float(parts[4]),
                })
            except ValueError:
                continue
        return gpus
    except (subprocess.TimeoutExpired, OSError):
        return []


def _parse_glances_uptime(v) -> Optional[int]:
    """Glances may report uptime as int seconds or as a string like
    '5 days, 4:23:17' / '4:23:17'. Return seconds or None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    if not isinstance(v, str):
        return None
    s = v.strip()
    total = 0
    if "day" in s:
        try:
            days_part, rest = s.split(",", 1)
            total += int(days_part.split()[0]) * 86400
            s = rest.strip()
        except (ValueError, IndexError):
            return None
    parts = s.split(":")
    try:
        if len(parts) == 3:
            total += int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            total += int(parts[0]) * 60 + int(parts[1])
        else:
            return None
    except ValueError:
        return None
    return total


async def _remote_hardware_snapshot() -> Optional[dict]:
    """Probe a Glances server via its JSON REST API. Returns None if
    REMOTE_SERVER_ENABLED is off; returns a `{name, status, hardware}`
    dict otherwise — `hardware` is None when the probe failed."""
    if not settings.REMOTE_SERVER_ENABLED or not settings.REMOTE_SERVER_GLANCES_URL:
        return None

    base = settings.REMOTE_SERVER_GLANCES_URL.rstrip("/")
    name = settings.REMOTE_SERVER_NAME
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{base}/api/4/all")
            r.raise_for_status()
            data = r.json()
    except Exception:
        return {"name": name, "status": "down", "hardware": None}

    cpu = data.get("cpu") or {}
    mem = data.get("mem") or {}
    fs_list = data.get("fs") or []
    root_fs = next((f for f in fs_list if f.get("mnt_point") == "/"), None)
    if root_fs is None and fs_list:
        # Pick the filesystem with the largest size as a sensible default.
        root_fs = max(fs_list, key=lambda f: f.get("size") or 0)
    uptime_seconds = _parse_glances_uptime(data.get("uptime"))

    gpus = []
    for g in data.get("gpu") or []:
        try:
            vram_total = float(g.get("mem_total") or g.get("memory_total") or 0)
            mem_pct = g.get("mem")
            if isinstance(mem_pct, (int, float)) and vram_total:
                vram_used = vram_total * float(mem_pct) / 100.0
            else:
                vram_used = float(g.get("memory_used") or 0)
            gpus.append({
                "name": str(g.get("name") or "GPU"),
                "util_pct": float(g.get("proc") or g.get("utilization") or 0),
                "vram_used_mb": round(vram_used, 1),
                "vram_total_mb": round(vram_total, 1),
                "temp_c": float(g.get("temperature") or 0),
            })
        except (TypeError, ValueError):
            continue

    def _opt_float(x) -> Optional[float]:
        try:
            return float(x) if x is not None else None
        except (TypeError, ValueError):
            return None

    ram_total = _opt_float(mem.get("total"))
    ram_used = _opt_float(mem.get("used"))

    hardware = {
        "cpu_pct": _opt_float(cpu.get("total")),
        "ram_pct": _opt_float(mem.get("percent")),
        "ram_used_gb": round(ram_used / (1024 ** 3), 2) if ram_used else None,
        "ram_total_gb": round(ram_total / (1024 ** 3), 2) if ram_total else None,
        "disk_pct": _opt_float(root_fs.get("percent")) if root_fs else None,
        "disk_free_gb": round(float(root_fs.get("free") or 0) / (1024 ** 3), 2) if root_fs else None,
        "uptime_seconds": uptime_seconds,
        "gpu": gpus,
    }
    return {"name": name, "status": "up", "hardware": hardware}


def _hardware_snapshot() -> dict:
    """Local hardware via psutil + nvidia-smi. All probes independent."""
    try:
        cpu_pct = psutil.cpu_percent(interval=None)
    except Exception:
        cpu_pct = None
    try:
        vm = psutil.virtual_memory()
        ram_pct = vm.percent
        ram_used_gb = round(vm.used / (1024 ** 3), 2)
        ram_total_gb = round(vm.total / (1024 ** 3), 2)
    except Exception:
        ram_pct = ram_used_gb = ram_total_gb = None
    try:
        du = psutil.disk_usage("/")
        disk_pct = du.percent
        disk_free_gb = round(du.free / (1024 ** 3), 2)
    except Exception:
        disk_pct = disk_free_gb = None
    try:
        uptime_seconds = round(time.time() - psutil.boot_time())
    except Exception:
        uptime_seconds = None
    return {
        "cpu_pct": cpu_pct,
        "ram_pct": ram_pct,
        "ram_used_gb": ram_used_gb,
        "ram_total_gb": ram_total_gb,
        "disk_pct": disk_pct,
        "disk_free_gb": disk_free_gb,
        "uptime_seconds": uptime_seconds,
        "gpu": _nvidia_smi_gpu(),
    }


async def _services_snapshot(ai_health: dict) -> list[dict]:
    out: list[dict] = []

    # FastAPI itself — we answered, so we're up.
    out.append({"name": "FastAPI", "status": "up", "latency_ms": 0.0})

    # llama-server
    llama_status, llama_latency = await _http_probe(
        f"{settings.LLAMA_BASE_URL}/v1/models", timeout=2.0,
    )
    out.append({
        "name": "llama-server",
        "status": llama_status,
        "latency_ms": llama_latency,
        "model": settings.LLAMA_MODEL or None,
    })

    def _ai_component_status(name: str) -> str:
        component = next(
            (c for c in ai_health.get("components", []) if c.get("name") == name),
            None,
        )
        return "loaded" if component and component.get("loaded") else "down"

    # shore-ai container row. `correlates_with: shore-ai` in services.yaml
    # attaches the Start/Stop button here. Status reflects the supervisor's
    # view of the container, derived from whether Health.Get responded.
    shore_ai_status = "up" if ai_health.get("components") else "down"
    out.append({
        "name": "shore-ai",
        "status": shore_ai_status,
    })

    # Whisper STT (remote shore-ai-service component)
    out.append({
        "name": "Whisper STT",
        "status": _ai_component_status("stt"),
    })

    # Kokoro TTS (remote shore-ai-service component)
    out.append({
        "name": "Kokoro TTS",
        "status": _ai_component_status("tts"),
    })

    # n8n (only if enabled)
    if settings.N8N_ENABLED:
        n8n_status, n8n_latency = await _http_probe(
            f"{settings.N8N_BASE_URL}/healthz", timeout=2.0,
        )
        workflows_count = 0
        try:
            from app.services.n8n_service import n8n_service
            workflows_count = len(getattr(n8n_service, "_registered_tools", []))
        except Exception:
            pass
        out.append({
            "name": "n8n",
            "status": n8n_status,
            "latency_ms": n8n_latency,
            "workflows_count": workflows_count,
        })

    # FileBrowser
    if settings.FILEBROWSER_URL:
        fb_status, fb_latency = await _http_probe(settings.FILEBROWSER_URL, timeout=2.0)
        out.append({
            "name": "FileBrowser",
            "status": fb_status,
            "latency_ms": fb_latency,
        })

    # shore-pty-service
    try:
        backend = getattr(terminal_service, "backend", None)
        client = getattr(backend, "client", None) if backend else None
        pty_up = bool(client and client.is_connected)
    except Exception:
        pty_up = False
    out.append({
        "name": "shore-pty-service",
        "status": "up" if pty_up else "down",
        "sessions_count": len(getattr(terminal_service, "sessions", {}) or {}),
    })

    return out


async def _databases_snapshot() -> list[dict]:
    out: list[dict] = []

    # Redis
    redis_ok, redis_latency = (False, None)
    short_term_turns = None
    if memory_facade.short_term is not None:
        redis_ok, redis_latency = await _measure(memory_facade.short_term.health())
        if redis_ok:
            try:
                msgs = await memory_facade.short_term.recent()
                short_term_turns = len(msgs)
            except Exception:
                pass
    out.append({
        "name": "Redis",
        "status": "up" if redis_ok else "down",
        "latency_ms": redis_latency,
        "short_term_turns": short_term_turns,
    })

    # Postgres
    pg_ok, pg_latency = await _measure(memory_facade.profile.health())
    profile_size_bytes = None
    if pg_ok:
        try:
            import json
            data = await memory_facade.profile.read()
            profile_size_bytes = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        except Exception:
            pass
    out.append({
        "name": "Postgres",
        "status": "up" if pg_ok else "down",
        "latency_ms": pg_latency,
        "profile_size_bytes": profile_size_bytes,
    })

    # Qdrant
    qd_ok, qd_latency = await _measure(memory_facade.episodic.health())
    episodic_count = None
    if qd_ok:
        try:
            episodic_count = await memory_facade.episodic.count()
        except Exception:
            pass
    out.append({
        "name": "Qdrant",
        "status": "up" if qd_ok else "down",
        "latency_ms": qd_latency,
        "episodic_count": episodic_count,
    })

    return out


async def _workers_snapshot() -> dict:
    # LOCOMO worker
    locomo: dict[str, Any] = {
        "enabled": settings.WORKER_ENABLED,
        "last_extracted_ts": None,
        "locked": False,
        "unprocessed_count": None,
    }
    if settings.WORKER_ENABLED:
        try:
            # Worker is per-user (only admin's turns extract). When
            # AUTH_ENABLED=False the admin is the synthetic "legacy"
            # user. With auth on, the dashboard shows the most-recently-
            # tracked admin (set by worker on each admin turn); if no
            # admin has chatted yet, this falls back to "legacy" and
            # reports 0 — acceptable until first admin login.
            admin_uid = worker_service._pending_user_id or "legacy"
            last_ts = await worker_service.get_last_extracted_ts(admin_uid)
            locomo["last_extracted_ts"] = last_ts
            locomo["locked"] = bool(worker_service._lock.locked())
        except Exception:
            pass

    # Scheduler
    scheduler: dict[str, Any] = {
        "active_tasks": 0,
        "next_fire_at": None,
        "next_fire_label": None,
    }
    try:
        tasks = scheduler_service.list_tasks()
        scheduler["active_tasks"] = len(tasks)
        # Find earliest next_run_at among tasks (if present)
        upcoming = [
            t for t in tasks
            if isinstance(t.get("next_run_at"), (int, float)) and t["next_run_at"] > 0
        ]
        if upcoming:
            nxt = min(upcoming, key=lambda t: t["next_run_at"])
            scheduler["next_fire_at"] = nxt["next_run_at"]
            scheduler["next_fire_label"] = nxt.get("message") or nxt.get("task_id")
    except Exception:
        pass

    # Canonicalizer — known to run via scheduler_service.add_system_job(); exact
    # last-run tracking is not persisted today, so report config only.
    canonicalizer = {
        "enabled": settings.CANONICALIZER_ENABLED,
        "cron": settings.CANONICALIZER_CRON,
        "similarity_threshold": settings.CANONICALIZER_SIMILARITY_THRESHOLD,
    }

    return {"locomo": locomo, "scheduler": scheduler, "canonicalizer": canonicalizer}


# ── Service-control overlay ────────────────────────────────────────────

async def _control_lookup() -> tuple[dict, dict]:
    """Build two lookups: by correlates_with (for services/databases) and by
    display_name (for workers). Returns (by_correlate, by_display)."""
    by_correlate: dict[str, dict] = {}
    by_display: dict[str, dict] = {}
    try:
        for st in await service_manager.list_state():
            control = {
                "name": st.name,
                "kind": st.kind,
                "running": st.running,
                "transitioning": st.transitioning,
                "last_error": st.last_error,
            }
            if st.correlates_with:
                by_correlate[st.correlates_with] = control
            if st.display_name:
                by_display[st.display_name] = control
    except Exception:
        pass
    return by_correlate, by_display


# ── Endpoint ───────────────────────────────────────────────────────────

async def _ai_health_snapshot() -> dict:
    try:
        return await health_client.get()
    except Exception:
        return {"ready": False, "version": "", "components": []}


@router.get("/dashboard")
async def dashboard() -> dict:
    # One Health.Get round-trip per request; reused by services + ai_components.
    ai_health = await _ai_health_snapshot()

    databases, workers, remote, (ctrl_by_corr, ctrl_by_display) = \
        await asyncio.gather(
            _databases_snapshot(),
            _workers_snapshot(),
            _remote_hardware_snapshot(),
            _control_lookup(),
        )
    services = await _services_snapshot(ai_health)
    hardware = _hardware_snapshot()

    # Attach `control` field to each row whose name matches the registry.
    for s in services:
        s["control"] = ctrl_by_corr.get(s["name"])
    for d in databases:
        d["control"] = ctrl_by_corr.get(d["name"])

    # Workers section uses display_name as the join key (LOCOMO worker,
    # Canonicalizer). Scheduler is not controllable.
    workers["locomo"]["control"] = ctrl_by_display.get("LOCOMO worker")
    workers["canonicalizer"]["control"] = ctrl_by_display.get("Canonicalizer")

    ai_components = ai_health.get("components", []) or [
        {"name": "stt", "loaded": False, "detail": ""},
        {"name": "tts", "loaded": False, "detail": ""},
        {"name": "embed", "loaded": False, "detail": ""},
    ]

    return {
        "generated_at": time.time(),
        "services": services,
        "databases": databases,
        "hardware": hardware,
        "remote_hardware": remote,
        "workers": workers,
        "ai_components": ai_components,
    }
