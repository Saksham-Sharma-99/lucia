import uuid

from lucia.scheduling.tasks import arm_scheduled_episodes, fire_episode, lease_reaper


def test_beat_tasks_run_in_their_own_loop_and_session() -> None:
    """Smoke test of the Celery wrappers; the logic is tested in test_scheduler.py."""
    assert arm_scheduled_episodes() == 0
    assert lease_reaper() == 0
    fire_episode(str(uuid.uuid4()), "0")
