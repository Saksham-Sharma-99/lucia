"""Plan items live in `run_tasks.plan` (JSONB). The list is replaced, never mutated in place,
so SQLAlchemy sees every change."""

from typing import Any

from lucia.db.models import RunTask


def item(task: RunTask, item_id: str) -> dict[str, Any]:
    return next(i for i in task.plan if i["id"] == item_id)


def set_item(task: RunTask, item_id: str, **changes: Any) -> dict[str, Any]:
    task.plan = [{**i, **changes} if i["id"] == item_id else i for i in task.plan]
    return item(task, item_id)
