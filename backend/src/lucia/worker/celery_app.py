from celery import Celery

from lucia.core.config import get_settings

settings = get_settings()

celery_app = Celery("lucia", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Must exceed the 1h ETA arming horizon (HLD §10) so armed tasks are not redelivered early.
    broker_transport_options={"visibility_timeout": 7200},
    result_expires=3600,
    timezone="UTC",
    beat_schedule={},
)


@celery_app.task(name="lucia.ping")
def ping() -> str:
    return "pong"
