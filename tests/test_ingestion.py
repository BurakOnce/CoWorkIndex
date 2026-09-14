"""Veri yükleme (demo veri üretimi + Excel içe aktarma) uçtan uca testleri.

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


async def test_seed_demo_data_uses_fixed_roster_and_is_idempotent(client: AsyncClient):
    first = await client.post("/ingestion/seed-demo-data", params={"months": 1})
    assert first.status_code == 200
    body = first.json()
    assert body["employees_total"] == FIXED_EMPLOYEE_COUNT
    assert body["events_added"] > 0
    assert body["quality_status"] in {"passed", "warning", "failed"}

    employees_resp = await client.get("/employees")
    assert employees_resp.status_code == 200
    assert len(employees_resp.json()) == FIXED_EMPLOYEE_COUNT

    # İkinci koşu yeni çalışan oluşturmamalı, sadece daha fazla event eklemeli.
    second = await client.post("/ingestion/seed-demo-data", params={"months": 1})
    assert second.status_code == 200
    assert second.json()["employees_total"] == FIXED_EMPLOYEE_COUNT

    employees_resp_again = await client.get("/employees")
    assert len(employees_resp_again.json()) == FIXED_EMPLOYEE_COUNT


async def test_seed_demo_data_rejects_invalid_months(client: AsyncClient):
    resp = await client.post("/ingestion/seed-demo-data", params={"months": 0})
    assert resp.status_code == 422


async def test_download_template_lists_existing_roster(client: AsyncClient):
    # Şablonun "Çalışanlar (referans)" sayfası üretilebilmesi için önce
    # kadronun var olduğundan emin ol.
    await client.post("/ingestion/seed-demo-data", params={"months": 1})

    resp = await client.get("/ingestion/template")
    assert resp.status_code == 200
    assert "spreadsheetml" in resp.headers["content-type"]
    assert len(resp.content) > 0


async def test_import_excel_only_adds_events_to_existing_employees(client: AsyncClient):
    await client.post("/ingestion/seed-demo-data", params={"months": 1})

    template_resp = await client.get("/ingestion/template")
    assert template_resp.status_code == 200

    employees_before = (await client.get("/employees")).json()

    import_resp = await client.post(
        "/ingestion/import-excel",
        files={
            "file": (
                "sablon.xlsx",
                template_resp.content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert import_resp.status_code == 200
    body = import_resp.json()
    assert body["events_accepted"] == 2
    assert body["events_rejected"] == 0
    assert body["errors"] == []

    employees_after = (await client.get("/employees")).json()
    assert len(employees_after) == len(employees_before) == FIXED_EMPLOYEE_COUNT


async def test_import_excel_rejects_unknown_employee(client: AsyncClient):
    await client.post("/ingestion/seed-demo-data", params={"months": 1})

    import io

    import pandas as pd

    buffer = io.BytesIO()
    events_df = pd.DataFrame(
        [
            {
                "employee_full_name": "Var Olmayan Kişi",
                "tool_name": "ChatGPT",
                "occurred_at": "2026-08-15 09:30:00",
                "action_type": "accepted",
                "dialogue_turn_count": 1,
                "had_disagreement": False,
                "persuasion_direction": "none",
                "directive_language_ratio": 0.2,
                "politeness_marker_count": 1,
                "avg_sentence_length": 10.0,
                "exclamation_density": 0.0,
                "outcome_status": "production",
                "critical_check_flag": False,
                "task_category": "code",
                "input_tokens": 100,
                "output_tokens": 200,
            }
        ]
    )
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        events_df.to_excel(writer, sheet_name="events", index=False)

    resp = await client.post(
        "/ingestion/import-excel",
        files={
            "file": (
                "sablon.xlsx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["events_accepted"] == 0
    assert body["events_rejected"] == 1
    assert len(body["errors"]) == 1


async def test_import_excel_rejects_non_xlsx(client: AsyncClient):
    resp = await client.post(
        "/ingestion/import-excel",
        files={"file": ("veri.csv", b"a,b,c", "text/csv")},
    )
    assert resp.status_code == 422
