"""
Scheduler service for proactive agent tasks.
Uses APScheduler for timing and JSON files for persistence across restarts.
"""

import json
import uuid
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable, Awaitable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings


class SchedulerService:

    def __init__(self):
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._tasks: dict[str, dict] = {}
        self._on_fire: Optional[Callable[[dict], Awaitable[None]]] = None
        self._tasks_file = Path(settings.SCHEDULER_TASKS_FILE)

    def set_fire_callback(self, callback: Callable[[dict], Awaitable[None]]):
        """Set the async callback invoked when a task fires."""
        self._on_fire = callback

    def start(self):
        """Initialize APScheduler, load persisted tasks, reschedule them."""
        self._scheduler = AsyncIOScheduler()
        self._scheduler.start()
        self._load_tasks()
        self._reschedule_all()
        print(f"[Scheduler] Started with {len(self._tasks)} persisted tasks")

    def shutdown(self):
        """Stop the scheduler."""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            print("[Scheduler] Shut down")

    # ── Task CRUD ──

    def add_reminder(self, message: str, delay_seconds: int) -> dict:
        """One-shot reminder that fires after delay_seconds."""
        task_id = f"rem_{uuid.uuid4().hex[:8]}"
        trigger_at = datetime.now() + timedelta(seconds=delay_seconds)

        task = {
            "task_id": task_id,
            "type": "reminder",
            "message": message,
            "created_at": datetime.now().isoformat(),
            "trigger_at": trigger_at.isoformat(),
            "recurrence": None,
            "status": "pending",
        }

        self._tasks[task_id] = task
        self._save_tasks()

        self._scheduler.add_job(
            self._fire_task,
            DateTrigger(run_date=trigger_at),
            id=task_id,
            args=[task_id],
            replace_existing=True,
        )

        print(f"[Scheduler] Reminder '{task_id}' set for {trigger_at}")
        return task

    def add_recurring_task(
        self,
        message: str,
        interval_seconds: Optional[int] = None,
        cron: Optional[str] = None,
    ) -> dict:
        """Recurring task with interval or cron expression."""
        task_id = f"sched_{uuid.uuid4().hex[:8]}"

        task = {
            "task_id": task_id,
            "type": "scheduled",
            "message": message,
            "created_at": datetime.now().isoformat(),
            "trigger_at": None,
            "recurrence": None,
            "status": "pending",
        }

        if interval_seconds:
            task["recurrence"] = {"type": "interval", "seconds": interval_seconds}
            trigger = IntervalTrigger(seconds=interval_seconds)
        elif cron:
            task["recurrence"] = {"type": "cron", "expression": cron}
            # Parse cron: "minute hour day month day_of_week"
            parts = cron.strip().split()
            cron_kwargs = {}
            fields = ["minute", "hour", "day", "month", "day_of_week"]
            for i, part in enumerate(parts):
                if i < len(fields):
                    cron_kwargs[fields[i]] = part
            trigger = CronTrigger(**cron_kwargs)
        else:
            return {"error": "Provide either interval_seconds or cron"}

        self._tasks[task_id] = task
        self._save_tasks()

        self._scheduler.add_job(
            self._fire_task,
            trigger,
            id=task_id,
            args=[task_id],
            replace_existing=True,
        )

        print(f"[Scheduler] Recurring task '{task_id}' created")
        return task

    def cancel_task(self, task_id: str) -> bool:
        """Cancel and remove a scheduled task."""
        if task_id not in self._tasks:
            return False

        self._tasks[task_id]["status"] = "cancelled"
        try:
            self._scheduler.remove_job(task_id)
        except Exception:
            pass

        self._save_tasks()
        print(f"[Scheduler] Task '{task_id}' cancelled")
        return True

    def list_tasks(self) -> list[dict]:
        """Return all pending/active tasks."""
        return [t for t in self._tasks.values() if t["status"] == "pending"]

    # ── Internal ──

    async def _fire_task(self, task_id: str):
        """Called by APScheduler when a task triggers."""
        task = self._tasks.get(task_id)
        if not task:
            return

        print(f"[Scheduler] Firing task '{task_id}': {task['message']}")

        # Remove one-shot reminders after firing
        if task.get("recurrence") is None:
            del self._tasks[task_id]
            self._save_tasks()

        if self._on_fire:
            await self._on_fire(task)

    def _load_tasks(self):
        """Load tasks from disk."""
        if not self._tasks_file.exists():
            return
        try:
            data = json.loads(self._tasks_file.read_text(encoding="utf-8"))
            self._tasks = {t["task_id"]: t for t in data}
        except (json.JSONDecodeError, Exception) as e:
            print(f"[Scheduler] Error loading tasks: {e}")

    def _save_tasks(self):
        """Persist tasks to disk."""
        self._tasks_file.parent.mkdir(parents=True, exist_ok=True)
        self._tasks_file.write_text(
            json.dumps(list(self._tasks.values()), indent=2, default=str),
            encoding="utf-8",
        )

    def _reschedule_all(self):
        """Re-register all pending tasks with APScheduler after restart."""
        now = datetime.now()
        fired_immediately = 0

        for task in list(self._tasks.values()):
            if task["status"] != "pending":
                continue

            if task.get("recurrence") is None and task.get("trigger_at"):
                # One-shot reminder
                trigger_dt = datetime.fromisoformat(task["trigger_at"])
                if trigger_dt <= now:
                    # Missed — fire immediately
                    asyncio.get_event_loop().create_task(
                        self._fire_task(task["task_id"])
                    )
                    fired_immediately += 1
                else:
                    self._scheduler.add_job(
                        self._fire_task,
                        DateTrigger(run_date=trigger_dt),
                        id=task["task_id"],
                        args=[task["task_id"]],
                        replace_existing=True,
                    )

            elif task.get("recurrence"):
                # Recurring task
                rec = task["recurrence"]
                if rec["type"] == "interval":
                    trigger = IntervalTrigger(seconds=rec["seconds"])
                elif rec["type"] == "cron":
                    parts = rec["expression"].strip().split()
                    cron_kwargs = {}
                    fields = ["minute", "hour", "day", "month", "day_of_week"]
                    for i, part in enumerate(parts):
                        if i < len(fields):
                            cron_kwargs[fields[i]] = part
                    trigger = CronTrigger(**cron_kwargs)
                else:
                    continue

                self._scheduler.add_job(
                    self._fire_task,
                    trigger,
                    id=task["task_id"],
                    args=[task["task_id"]],
                    replace_existing=True,
                )

        if fired_immediately:
            print(f"[Scheduler] Fired {fired_immediately} missed tasks immediately")


scheduler_service = SchedulerService()
