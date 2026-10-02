import uuid

from lucia.conversations.summarize import summarize, title
from lucia.worker.celery_app import celery_app
from lucia.worker.runner import run_async


@celery_app.task(name="conversations.title")
def title_task(conversation_id: str) -> None:
    run_async(lambda s: title(s, uuid.UUID(conversation_id)))


@celery_app.task(name="conversations.summarize")
def summarize_task(conversation_id: str) -> None:
    run_async(lambda s: summarize(s, uuid.UUID(conversation_id)))
