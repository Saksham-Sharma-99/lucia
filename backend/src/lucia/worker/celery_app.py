from typing import Any

from celery import Celery

from lucia.core.config import get_settings

settings = get_settings()

# Task name → queue (RUNTIME_SPEC §15). Exact names win over prefixes.
_QUEUES = {
    "harness.advance_run": "episodes",
    "harness.compact_journal": "maintenance",
    "connectors.slack_ack": "interactive",
    "orchestrator.": "interactive",
    "harness.": "sched",
    "scheduling.": "sched",
    "connectors.": "sched",
    "notifications.": "notify",
    "conversations.": "maintenance",
}


def route(name: str, *_: Any, **__: Any) -> dict[str, str]:
    queue = _QUEUES.get(name) or next(
        (q for prefix, q in _QUEUES.items() if prefix.endswith(".") and name.startswith(prefix)),
        "celery",
    )
    return {"queue": queue}


BEAT: dict[str, dict[str, Any]] = {
    "arm-scheduled-episodes": {
        "task": "scheduling.arm_scheduled_episodes",
        "schedule": settings.beat_arm_interval_s,
    },
    "lease-reaper": {"task": "harness.lease_reaper", "schedule": settings.beat_reaper_interval_s},
    "kill-switch-sweep": {"task": "harness.kill_switch_sweep", "schedule": 60.0},
    "end-condition-sweep": {"task": "harness.end_condition_sweep", "schedule": 3600.0},
    "poll-stale-vapi-calls": {"task": "connectors.poll_stale_vapi_calls", "schedule": 60.0},
    "sla-sweep": {"task": "notifications.sla_sweep", "schedule": 60.0},
    "deliver-pending": {"task": "notifications.deliver_pending", "schedule": 10.0},
}

celery_app = Celery(
    "lucia",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "lucia.harness.tasks",
        "lucia.scheduling.tasks",
        "lucia.orchestrator.tasks",
        "lucia.notifications.tasks",
        "lucia.conversations.tasks",
        "lucia.connectors.tasks",
    ],
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Must exceed the 1h ETA arming horizon (HLD §10) so armed tasks are not redelivered early.
    broker_transport_options={"visibility_timeout": 7200},
    result_expires=3600,
    timezone="UTC",
    task_routes=(route,),
    beat_schedule=BEAT,
)


@celery_app.task(name="lucia.ping")
def ping() -> str:
    return "pong"
