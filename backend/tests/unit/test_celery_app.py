import pytest

from lucia.worker.celery_app import BEAT, route


@pytest.mark.parametrize(
    ("task", "queue"),
    [
        ("orchestrator.handle_message", "interactive"),
        ("harness.advance_run", "episodes"),
        ("harness.lease_reaper", "sched"),
        ("scheduling.fire_episode", "sched"),
        ("connectors.poll_stale_vapi_calls", "sched"),
        ("notifications.deliver", "notify"),
        ("conversations.summarize", "maintenance"),
        ("harness.compact_journal", "maintenance"),
        ("lucia.ping", "celery"),
    ],
)
def test_tasks_route_to_their_queue(task: str, queue: str) -> None:
    assert route(task) == {"queue": queue}


def test_beat_runs_the_scheduler_and_the_reaper() -> None:
    tasks = {entry["task"] for entry in BEAT.values()}
    assert {"scheduling.arm_scheduled_episodes", "harness.lease_reaper"} <= tasks
