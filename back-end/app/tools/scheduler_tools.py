"""Scheduler tools for the AI agent — reminders and recurring tasks."""

from langchain_core.tools import tool
from app.services.scheduler_service import scheduler_service


@tool
def set_reminder(message: str, delay_minutes: int) -> str:
    """Set a ONE-TIME reminder that fires once after a delay, then stops. Use this for "remind me in X minutes" requests. For RECURRING reminders ("every X minutes"), use set_scheduled_task instead.

    Args:
        message: The reminder message to deliver.
        delay_minutes: How many minutes from now to trigger the reminder.
    """
    if delay_minutes <= 0:
        return "Error: delay_minutes must be positive."
    task = scheduler_service.add_reminder(message, delay_seconds=delay_minutes * 60)
    return f"Reminder set (ID: {task['task_id']}). Will fire at {task['trigger_at']}."


@tool
def set_scheduled_task(message: str, interval_minutes: int = 0, cron: str = "") -> str:
    """Set a RECURRING task that repeats on a schedule until cancelled. Use this for "every X minutes" or "every day at Y" requests. For one-time reminders, use set_reminder instead.

    Args:
        message: Description of what to check or notify about.
        interval_minutes: Run every N minutes. Use this OR cron, not both.
        cron: Cron expression for scheduling (e.g. "0 9 * * *" for daily at 9am). Use this OR interval_minutes.
    """
    if interval_minutes > 0:
        task = scheduler_service.add_recurring_task(
            message, interval_seconds=interval_minutes * 60
        )
    elif cron:
        task = scheduler_service.add_recurring_task(message, cron=cron)
    else:
        return "Error: provide either interval_minutes or cron."

    if "error" in task:
        return task["error"]
    return f"Scheduled task created (ID: {task['task_id']})."


@tool
def cancel_task(task_id: str) -> str:
    """Cancel a scheduled reminder or recurring task.

    Args:
        task_id: The ID of the task to cancel (e.g. "rem_a1b2c3" or "sched_d4e5f6").
    """
    if scheduler_service.cancel_task(task_id):
        return f"Task {task_id} cancelled."
    return f"Task {task_id} not found."


@tool
def list_tasks() -> str:
    """List all active scheduled tasks and reminders."""
    tasks = scheduler_service.list_tasks()
    if not tasks:
        return "No active tasks."
    lines = []
    for t in tasks:
        if t.get("trigger_at"):
            trigger = t["trigger_at"]
        elif t.get("recurrence"):
            rec = t["recurrence"]
            if rec["type"] == "interval":
                mins = rec["seconds"] // 60
                trigger = f"every {mins} min"
            else:
                trigger = f"cron: {rec['expression']}"
        else:
            trigger = "unknown"
        lines.append(f"- {t['task_id']} ({t['type']}): {t['message']} [fires: {trigger}]")
    return "\n".join(lines)
