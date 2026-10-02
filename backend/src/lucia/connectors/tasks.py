import uuid

from lucia.connectors.slack_ingest import acknowledge
from lucia.harness.tools.vapi_tool import poll_stale
from lucia.worker.celery_app import celery_app
from lucia.worker.runner import run_async


@celery_app.task(name="connectors.poll_stale_vapi_calls")
def poll_stale_vapi_calls() -> int:
    return run_async(poll_stale)


@celery_app.task(name="connectors.slack_ack")
def slack_ack(message_id: str) -> None:
    run_async(lambda session: acknowledge(session, uuid.UUID(message_id)))
