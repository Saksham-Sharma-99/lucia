import uuid

from lucia.llm.client import LLMError
from lucia.orchestrator.pipeline import handle_message
from lucia.worker.celery_app import celery_app
from lucia.worker.runner import run_async

RETRY_AFTER_S = 30


@celery_app.task(name="orchestrator.handle_message", bind=True, max_retries=1)
def handle_message_task(self, message_id: str) -> None:
    try:
        run_async(lambda s: handle_message(s, uuid.UUID(message_id)))
    except LLMError as e:
        if e.retryable:
            raise self.retry(countdown=RETRY_AFTER_S) from e
