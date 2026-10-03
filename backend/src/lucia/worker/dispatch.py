"""Enqueue Celery tasks by name, after the caller has committed. Tests capture `send_task`."""

from datetime import datetime

from lucia.worker.celery_app import celery_app


def send(
    task: str, *args: object, eta: datetime | None = None, countdown: float | None = None
) -> None:
    celery_app.send_task(task, args=[str(a) for a in args], eta=eta, countdown=countdown)
