import uuid

from lucia.scheduling import scheduler
from lucia.worker.celery_app import celery_app
from lucia.worker.dispatch import send
from lucia.worker.runner import run_async


@celery_app.task(name="scheduling.arm_scheduled_episodes")
def arm_scheduled_episodes() -> int:
    armed = run_async(scheduler.arm_due)
    for episode_id, guard, due_at in armed:
        send("scheduling.fire_episode", episode_id, guard, eta=due_at)
    return len(armed)


@celery_app.task(name="scheduling.fire_episode")
def fire_episode(episode_id: str, guard_version: str) -> None:
    run_id = run_async(lambda s: scheduler.fire(s, uuid.UUID(episode_id), int(guard_version)))
    if run_id:
        send("harness.advance_run", run_id)


@celery_app.task(name="harness.lease_reaper")
def lease_reaper() -> int:
    run_ids = run_async(scheduler.reap)
    for run_id in run_ids:
        send("harness.advance_run", run_id)
    return len(run_ids)
