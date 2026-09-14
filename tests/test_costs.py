"""Maliyet & verimlilik (token/USD) uçtan uca testleri.

Diğer API testleri gibi gerçek bir SQL Server bağlantısı gerektirir.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.demo_data import FIXED_EMPLOYEE_COUNT
from src.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _ensure_demo_data(client: AsyncClient) -> None:
    resp = await client.post("/ingestion/seed-demo-data", params={"months": 1})
    assert resp.status_code == 200


async def test_company_cost_summary(client: AsyncClient):
    await _ensure_demo_data(client)

    resp = await client.get("/costs/company")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"] == "company"
    assert body["event_count"] > 0
    assert body["total_tokens"] == body["total_input_tokens"] + body["total_output_tokens"]
    assert body["total_cost_usd"] > 0
    assert 0.0 <= body["efficient_token_ratio"] <= 1.0
    assert len(body["by_tool"]) > 0
    for tool_row in body["by_tool"]:
        assert tool_row["cost_usd"] >= 0


async def test_company_cost_windowed(client: AsyncClient):
    await _ensure_demo_data(client)

    resp = await client.get("/costs/company", params={"window_days": 7})
    assert resp.status_code == 200
    body = resp.json()
    assert body["period_start"] is not None
    assert body["period_end"] is not None


async def test_list_employee_costs(client: AsyncClient):
    await _ensure_demo_data(client)

    resp = await client.get("/costs/employees")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == FIXED_EMPLOYEE_COUNT
    for row in body:
        assert row["scope"] == "employee"
        assert row["scope_name"]
        assert row["total_cost_usd"] >= 0


async def test_employee_cost_not_found(client: AsyncClient):
    resp = await client.get("/costs/employees/999999")
    assert resp.status_code == 404


async def test_team_cost_not_found(client: AsyncClient):
    resp = await client.get("/costs/teams/999999")
    assert resp.status_code == 404


async def test_team_cost_summary(client: AsyncClient):
    await _ensure_demo_data(client)

    teams_resp = await client.get("/teams")
    teams = teams_resp.json()
    assert teams

    resp = await client.get(f"/costs/teams/{teams[0]['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"] == "team"
    assert body["scope_name"] == teams[0]["name"]
