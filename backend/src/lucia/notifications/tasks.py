import uuid

from lucia.notifications.deliver import deliver_message, deliver_pending
from lucia.notifications.sla import sweep
from lucia.worker.celery_app import celery_app
from lucia.worker.runner import run_async


@celery_app.task(name="notifications.deliver_message")
def deliver_message_task(message_id: str) -> None:
    run_async(lambda s: deliver_message(s, uuid.UUID(message_id)))


@celery_app.task(name="notifications.deliver_pending")
def deliver_pending_task() -> int:
    return run_async(deliver_pending)


@celery_app.task(name="notifications.sla_sweep")
def sla_sweep() -> int:
    return run_async(sweep)
