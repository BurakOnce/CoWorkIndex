"""API uçtan uca testleri.

Bu testler gerçek bir SQL Server bağlantısı gerektirir (docker-compose ile
ayağa kaldırılmış ve alembic migration'ları uygulanmış olmalı) -- OLTP/
API-first mimaride skorlama mantığı DB'ye bağlı olduğu için burada bilinçli
olarak mock kullanılmıyor.

Çalıştırmadan önce:
    docker compose up -d sqlserver
    python -m scripts.ensure_database
    alembic upgrade head
    pytest tests/test_api.py
"""

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_team_employee_tool(client: AsyncClient) -> tuple[int, int, int]:
    suffix = uuid.uuid4().hex[:8]
    team_resp = await client.post("/teams", json={"name": f"Test Takım {suffix}", "department": "Test"})
    assert team_resp.status_code == 201
    team_id = team_resp.json()["id"]

    tool_resp = await client.post("/tools", json={"name": f"Test Araç {suffix}"})
    assert tool_resp.status_code == 201
    tool_id = tool_resp.json()["id"]

    employee_resp = await client.post(
        "/employees",
        json={
            "full_name": f"Test Çalışan {suffix}",
            "team_id": team_id,
            "role": "Uzman",
            "hire_date": "2023-01-01",
        },
    )
    assert employee_resp.status_code == 201
    employee_id = employee_resp.json()["id"]

    return team_id, employee_id, tool_id


async def test_health(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_create_event_rejects_content_field(client: AsyncClient):
    _, employee_id, tool_id = await _create_team_employee_tool(client)

    payload = {
        "employee_id": employee_id,
        "tool_id": tool_id,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "session_id": str(uuid.uuid4()),
        "action_type": "accepted",
        "outcome_status": "production",
        "task_category": "code",
        "content": "bu alan asla kabul edilmemeli",
    }
    resp = await client.post("/events", json=payload)
    assert resp.status_code == 422


async def test_create_event_and_score_updates(client: AsyncClient):
    _, employee_id, tool_id = await _create_team_employee_tool(client)

    payload = {
        "employee_id": employee_id,
        "tool_id": tool_id,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "session_id": str(uuid.uuid4()),
        "action_type": "accepted",
        "dialogue_turn_count": 3,
        "had_disagreement": True,
        "persuasion_direction": "user_persuaded_ai",
        "directive_language_ratio": 0.2,
        "politeness_marker_count": 2,
        "avg_sentence_length": 12.5,
        "exclamation_density": 0.1,
        "outcome_status": "production",
        "critical_check_flag": True,
        "task_category": "code",
    }
    event_resp = await client.post("/events", json=payload)
    assert event_resp.status_code == 201

    score_resp = await client.get(f"/scores/employees/{employee_id}")
    assert score_resp.status_code == 200
    body = score_resp.json()
    assert body["employee_id"] == employee_id
    assert 0.0 <= body["composite_score"] <= 100.0
    assert body["archetype"] in {
        "kopyala_yapistirci",
        "diyalog_ortagi",
        "supheci",
        "emir_verici",
        "pasif_kullanici",
    }


async def test_directive_language_ratio_out_of_range_rejected(client: AsyncClient):
    _, employee_id, tool_id = await _create_team_employee_tool(client)

    payload = {
        "employee_id": employee_id,
        "tool_id": tool_id,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "session_id": str(uuid.uuid4()),
        "action_type": "accepted",
        "directive_language_ratio": 1.5,
        "outcome_status": "production",
        "task_category": "code",
    }
    resp = await client.post("/events", json=payload)
    assert resp.status_code == 422


async def test_quality_run_and_report(client: AsyncClient):
    run_resp = await client.post("/quality/run")
    assert run_resp.status_code == 201
    body = run_resp.json()
    assert "overall_status" in body
    assert len(body["checks"]) == 4

    report_resp = await client.get("/quality/report")
    assert report_resp.status_code == 200
