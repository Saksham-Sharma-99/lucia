from httpx import AsyncClient

from lucia.worker.celery_app import celery_app


async def test_health_reports_postgres_and_redis(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "postgres": "ok", "redis": "ok"}


def test_ping_task_runs_eagerly() -> None:
    assert celery_app.tasks["lucia.ping"].apply().get() == "pong"
