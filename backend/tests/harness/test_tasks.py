import uuid

from lucia.harness.tasks import advance_run_task, end_condition_sweep, kill_switch_sweep


def test_task_runs_in_its_own_loop_and_session() -> None:
    assert advance_run_task(str(uuid.uuid4())) == "not_claimed"


def test_sweeps_run_in_their_own_loop_and_session() -> None:
    assert kill_switch_sweep() >= 0
    assert end_condition_sweep() >= 0


def test_delivery_sla_and_poll_sweeps_run_in_their_own_loop() -> None:
    from lucia.connectors.tasks import poll_stale_vapi_calls
    from lucia.notifications.tasks import deliver_pending_task, sla_sweep

    assert deliver_pending_task() == 0
    assert sla_sweep() == 0
    assert poll_stale_vapi_calls() == 0
