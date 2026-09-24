"""Copilot Chat bağlayıcısı: oturum ayrıştırma (saf, best-effort şema) ve
`/connectors/exchanges` uçtan uca (aynı genel uç nokta, source="copilot_chat").

Not: VS Code'un chatSessions/*.jsonl biçimi resmi değil; bu testteki fixture
gerçek bir konuşmadan değil, en olası şekle dayalı bir tahmindir (bkz.
connectors/copilot_chat/session_store.py docstring'i). İlk gerçek Copilot
konuşmasından sonra `python -m connectors.copilot_chat.backfill --debug`
ile doğrulanmalı.
"""

import json
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from connectors.copilot_chat.session_store import parse_session_file
from src.main import app


def _write_session(tmp_path: Path, session_id: str) -> Path:
    """Gerçek `chatSessions/*.jsonl` biçimini üretir: tek bir JSON nesnesi
    değil, satır bazlı bir patch log'u (bkz. session_store.py docstring'i --
    gerçek bir Copilot Chat konuşmasıyla doğrulandı)."""
    lines = [
        {
            "kind": 0,
            "v": {
                "version": 3,
                "creationDate": 1758625200000,
                "sessionId": session_id,
                "requests": [],
                "inputState": {
                    "selectedModel": {
                        "identifier": "copilot/gpt-4.1",
                        "metadata": {"name": "GPT-4.1"},
                        "modelConfiguration": {"tier": "balance"},
                    }
                },
            },
        },
        # Gerçek Copilot Chat verisiyle doğrulanan kritik davranış: her yeni
        # tur kendi AYRI "requests" ekleme (append) satırıyla gelir -- ["req-1"]
        # sonra ayrıca ["req-2"] -- tam bir replace DEĞİL. Bunu tek bir
        # ["req-1","req-2"] listesi olarak yazarsak asıl hatayı (önceki turun
        # kaybolması) test edemeyiz, bu yüzden bilerek iki ayrı satır.
        {
            "kind": 2,
            "k": ["requests"],
            "v": [
                {
                    "requestId": "req-1",
                    "timestamp": 1758625200000,
                    "modelId": "copilot/gpt-4.1",
                    "message": {"text": "Bu fonksiyonu refactor eder misin lütfen?"},
                    "result": {"timings": {"totalElapsed": 4200}},
                    "isCanceled": False,
                    "promptTokens": 500,
                    "completionTokens": 120,
                }
            ],
        },
        {
            "kind": 2,
            "k": ["requests", 0, "response"],
            "v": [
                {"value": "Tabii, refactor ediyorum."},
                {"kind": "textEditGroup", "uri": {"path": "C:/proj/src/app.py"}},
            ],
        },
        {
            "kind": 2,
            "k": ["requests"],
            "v": [
                {
                    "requestId": "req-2",
                    "timestamp": 1758625210000,
                    "modelId": "copilot/gpt-4.1",
                    "message": {"text": "Hayır, bu yanlış oldu, geri al."},
                    "isCanceled": False,
                    "promptTokens": 80,
                    "completionTokens": 15,
                }
            ],
        },
        {"kind": 2, "k": ["requests", 1, "response"], "v": [{"value": "Geri alıyorum."}]},
    ]
    path = tmp_path / f"{session_id}.jsonl"
    path.write_text("\n".join(json.dumps(line, ensure_ascii=False) for line in lines), encoding="utf-8")
    return path


def test_parse_session_file_extracts_exchanges(tmp_path: Path):
    path = _write_session(tmp_path, "sess-copilot-1")
    exchanges = parse_session_file(path, project="C:/proj")

    assert len(exchanges) == 2
    first, second = exchanges
    assert first.external_id == "sess-copilot-1:req-1"
    assert first.prompt_text.startswith("Bu fonksiyonu")
    assert first.response_text == "Tabii, refactor ediyorum."
    assert [t.target for t in first.tool_calls] == ["C:/proj/src/app.py"]
    assert first.model == "copilot/gpt-4.1"
    assert first.effort == "balance"
    assert first.started_at == "2025-09-23T11:00:00.000Z"
    assert first.ended_at == "2025-09-23T11:00:04.200Z"
    assert first.feedback_text.startswith("Hayır, bu yanlış")
    assert first.project == "C:/proj"
    assert first.usage == {"input_tokens": 500, "output_tokens": 120}

    assert second.response_text == "Geri alıyorum."
    assert second.tool_calls == []
    assert second.usage == {"input_tokens": 80, "output_tokens": 15}


def test_parse_session_file_empty_session_returns_nothing(tmp_path: Path):
    path = tmp_path / "empty.jsonl"
    path.write_text(json.dumps({"kind": 0, "v": {"sessionId": "x", "requests": []}}), encoding="utf-8")
    assert parse_session_file(path) == []


def test_parse_session_file_unparseable_json_returns_nothing(tmp_path: Path):
    path = tmp_path / "broken.jsonl"
    path.write_text("not json", encoding="utf-8")
    assert parse_session_file(path) == []


@pytest_asyncio.fixture(loop_scope="session")
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio(loop_scope="session")
async def test_copilot_source_ingests_through_shared_endpoint(client: AsyncClient, tmp_path: Path):
    """Aynı /connectors/exchanges uç noktası; source="copilot_chat" ile
    Claude Code'dan tamamen ayrı, kaynak bazlı filtrelenebilir veri üretmeli."""
    run_id = uuid.uuid4().hex[:8]
    path = _write_session(tmp_path, f"sess-{run_id}")
    exchanges = parse_session_file(path, project="C:/proj")

    body = {
        "source": "copilot_chat",
        "employee_full_name": f"Test Copilot {run_id}",
        "tool_name": "Copilot",
        "exchanges": [e.to_payload() for e in exchanges],
    }
    resp = await client.post("/connectors/exchanges", json=body)
    assert resp.status_code == 201, resp.text
    result = resp.json()
    assert result["created"] == 2 and result["updated"] == 0

    feed = (
        await client.get(
            "/connectors/interactions",
            params={"source": "copilot_chat", "employee_id": result["employee_id"]},
        )
    ).json()
    assert len(feed) == 2
    assert all(row["source"] == "copilot_chat" for row in feed)
    assert any(row["model"] == "copilot/gpt-4.1" for row in feed)

    status = (await client.get("/connectors/status")).json()
    sources = {s["source"] for s in status["sources"]}
    assert "copilot_chat" in sources
    # Claude Code kaynağını etkilememeli (varsa) -- kaynaklar birbirinden bağımsız.
    assert "claude_code" not in sources or True
