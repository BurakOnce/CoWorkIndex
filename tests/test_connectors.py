"""Claude Code bağlayıcısı: transcript ayrıştırma (saf), heuristik sinyal
çıkarımı (saf) ve /connectors uç noktaları (gerçek SQL Server)."""

import json
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from connectors.claude_code.transcript import parse_transcript
from src.analysis.heuristics import heuristic_signals, text_stats
from src.main import app
from src.routers.connectors import project_short_name


def _line(**kwargs) -> str:
    return json.dumps(kwargs, ensure_ascii=False)


def _write_transcript(tmp_path: Path, sid: str = "sess-1234") -> Path:
    lines = [
        _line(type="queue-operation", operation="enqueue", sessionId=sid),
        _line(
            type="user", uuid="u1", sessionId=sid, timestamp="2026-09-20T10:00:00.000Z",
            cwd="C:\\proj", gitBranch="main", origin={"kind": "human"},
            message={"role": "user", "content": "README dosyasını İngilizceye çevirir misin lütfen?"},
        ),
        # Claude Code aynı API cevabını blok başına ayrı satıra yazar; usage tekrar eder
        _line(
            type="assistant", uuid="a1", sessionId=sid, timestamp="2026-09-20T10:00:05.000Z",
            requestId="req_1", effort="high",
            message={
                "role": "assistant", "model": "claude-opus-5",
                "content": [{"type": "text", "text": "Tabii, çeviriyorum."}],
                "usage": {"input_tokens": 1000, "output_tokens": 300, "cache_creation_input_tokens": 50, "cache_read_input_tokens": 2000},
            },
        ),
        _line(
            type="assistant", uuid="a1b", sessionId=sid, timestamp="2026-09-20T10:00:05.500Z",
            requestId="req_1",
            message={
                "role": "assistant", "model": "claude-opus-5",
                "content": [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "C:\\proj\\README.md"}}],
                "usage": {"input_tokens": 1000, "output_tokens": 300, "cache_creation_input_tokens": 50, "cache_read_input_tokens": 2000},
            },
        ),
        _line(
            type="user", uuid="u1r", sessionId=sid, timestamp="2026-09-20T10:00:06.000Z",
            message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
        ),
        _line(
            type="assistant", uuid="a2", sessionId=sid, timestamp="2026-09-20T10:00:09.000Z",
            requestId="req_2",
            message={"role": "assistant", "model": "claude-opus-5",
                     "content": [{"type": "text", "text": "Çeviri tamamlandı."}],
                     "usage": {"input_tokens": 200, "output_tokens": 50}},
        ),
        _line(
            type="user", uuid="u2", sessionId=sid, timestamp="2026-09-20T10:05:00.000Z",
            cwd="C:\\proj", origin={"kind": "human"},
            message={"role": "user", "content": "Hayır bu yanlış oldu, kurulum kısmını sil ve mülakatla ilgili hiçbir şey olmasın."},
        ),
        _line(
            type="assistant", uuid="a3", sessionId=sid, timestamp="2026-09-20T10:05:04.000Z",
            message={"role": "assistant", "model": "claude-opus-5",
                     "content": [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "cat secrets.txt"}}],
                     "usage": {"input_tokens": 100, "output_tokens": 20}},
        ),
        _line(
            type="user", uuid="u2r", sessionId=sid, timestamp="2026-09-20T10:05:05.000Z",
            message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t2", "is_error": True,
                                                   "content": "Permission for this action was denied by the user"}]},
        ),
        _line(
            type="user", uuid="u3", sessionId=sid, timestamp="2026-09-20T10:06:00.000Z",
            origin={"kind": "human"},
            message={"role": "user", "content": "<command-name>/model</command-name><command-message>model</command-message>"},
        ),
    ]
    path = tmp_path / f"{sid}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_parse_transcript_groups_exchanges(tmp_path: Path):
    path = _write_transcript(tmp_path)
    exchanges = parse_transcript(path, hook_prompt="teşekkürler, süper oldu")

    assert [e.turn_index for e in exchanges] == [1, 2]  # slash-komut satırı prompt sayılmaz
    first, second = exchanges
    assert first.external_id == "sess-1234:u1"
    assert first.prompt_text.startswith("README dosyasını")
    assert first.response_text == "Tabii, çeviriyorum.\nÇeviri tamamlandı."
    assert [t.name for t in first.tool_calls] == ["Edit"]
    assert first.tool_calls[0].target.endswith("README.md")
    # req_1 iki satırda tekrar etti ama bir kez sayılmalı (1000+200 / 300+50)
    assert first.usage == {
        "input_tokens": 1200, "output_tokens": 350,
        "cache_creation_input_tokens": 50, "cache_read_input_tokens": 2000,
    }
    assert first.api_request_count == 2
    assert first.to_payload()["usage"]["api_requests"] == 2
    assert first.feedback_text.startswith("Hayır bu yanlış")
    assert first.model == "claude-opus-5"
    assert first.effort == "high"
    assert first.ended_at == "2026-09-20T10:00:09.000Z"

    assert second.tool_calls[0].denied is True and second.tool_calls[0].is_error is True
    assert second.feedback_text == "teşekkürler, süper oldu"


def test_text_stats_turkish_politeness_and_directives():
    polite = text_stats("README dosyasını İngilizceye çevirir misin lütfen?")
    assert polite.politeness_marker_count >= 2
    assert polite.directive_language_ratio == 0.0

    bossy = text_stats("Kurulum kısmını sil. Mülakat cümlelerini kaldır. Hemen yap!")
    assert bossy.directive_language_ratio >= 0.6
    assert bossy.exclamation_density > 0
    assert bossy.sentence_count == 3


def test_heuristic_signals_feedback_drives_action():
    edit_calls = [{"name": "Edit", "target": "README.md", "is_error": False, "denied": False}]
    accepted = heuristic_signals("çevir", "tamam", "süper, teşekkürler", edit_calls, interrupted=False)
    assert accepted["action_type"] == "accepted"
    assert accepted["outcome_status"] == "production"
    assert accepted["task_category"] == "writing"

    corrected = heuristic_signals("çevir", "tamam", "hayır yanlış oldu, kurulum kısmını sil ve baştan yaz", edit_calls, interrupted=False)
    assert corrected["action_type"] == "edited"
    assert corrected["had_disagreement"] is True
    assert corrected["persuasion_direction"] == "user_persuaded_ai"

    denied_calls = [{"name": "Bash", "target": "cat secrets.txt", "is_error": True, "denied": True}]
    rejected = heuristic_signals("dosyayı oku", "", None, denied_calls, interrupted=False)
    assert rejected["action_type"] == "rejected"
    assert rejected["outcome_status"] == "abandoned"

    checked = heuristic_signals("testleri çalıştırıp kontrol et", "", None, [], interrupted=False)
    assert checked["critical_check_flag"] is True


def test_project_short_name_uses_project_root_not_deepest_folder():
    # Bir projenin İÇİNDEKİ alt klasörde çalışırken (rapor sayfası, notebook,
    # görsel klasörü) her turu ayrı bir "proje" gibi göstermemeli -- gerçek
    # veriyle karşılaşılan bug.
    assert project_short_name("C:\\Projects\\Python\\Mihenk") == "Mihenk"
    assert project_short_name("C:\\Projects\\Python\\Mihenk\\fabric\\notebooks") == "Mihenk"
    assert (
        project_short_name(
            "C:\\Projects\\Python\\Mihenk\\powerbi\\mihenk_1.Report\\definition\\pages\\6f7a8b9c\\visuals\\p1rimary00stackedbar6"
        )
        == "Mihenk"
    )
    # Dil klasörü hiç yoksa (bilinmeyen bir düzen), son segmente düşer.
    assert project_short_name("C:\\Users\\burak\\OneDrive\\Masaüstü\\fabric ss's") == "fabric ss's"
    assert project_short_name(None) is None


@pytest_asyncio.fixture(loop_scope="session")
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio(loop_scope="session")
async def test_connector_ingest_upsert_and_feed(client: AsyncClient, tmp_path: Path):
    # Benzersiz oturum/çalışan: test temiz olmayan bir DB'ye karşı da tekrar koşabilsin
    run_id = uuid.uuid4().hex[:8]
    path = _write_transcript(tmp_path, sid=f"sess-{run_id}")
    exchanges = parse_transcript(path)
    body = {
        "source": "claude_code",
        "employee_full_name": f"Test Connector {run_id}",
        "tool_name": "Claude",
        "exchanges": [e.to_payload() for e in exchanges],
    }
    resp = await client.post("/connectors/exchanges", json=body)
    assert resp.status_code == 201, resp.text
    first = resp.json()
    assert first["received"] == 2 and first["created"] == 2 and first["updated"] == 0

    # Aynı etkileşimler tekrar gelirse yeni satır değil güncelleme olmalı
    resp = await client.post("/connectors/exchanges", json=body)
    second = resp.json()
    assert second["created"] == 0 and second["updated"] == 2

    feed = (await client.get("/connectors/interactions", params={"employee_id": first["employee_id"]})).json()
    assert len(feed) == 2
    newest = feed[0]
    assert newest["source"] == "claude_code"
    assert newest["dialogue_turn_count"] == 2
    assert newest["model"] == "claude-opus-5"
    assert newest["action_type"] == "rejected"  # araç reddi
    assert newest["employee_full_name"] == f"Test Connector {run_id}"
    if first["capture_content"]:
        assert newest["prompt_text"].startswith("Hayır bu yanlış")
        assert newest["signals"]["classifier"] in ("heuristic", "claude", "heuristic (claude unavailable)")

    status = (await client.get("/connectors/status")).json()
    assert any(s["source"] == "claude_code" and s["event_count"] >= 2 for s in status["sources"])

    score = (await client.get(f"/scores/employees/{first['employee_id']}")).json()
    assert 0 <= score["composite_score"] <= 100

    # Proje filtresi: event'ler "C:\\proj" klasöründen geldi -> proje adı "proj"
    projects = (await client.get("/connectors/projects")).json()
    assert any(p["project"] == "proj" and p["event_count"] >= 2 for p in projects)
    assert newest["project"] == "proj"

    filtered = (
        await client.get("/connectors/interactions", params={"project": "proj", "employee_id": first["employee_id"]})
    ).json()
    assert len(filtered) == 2
    assert (await client.get("/connectors/interactions", params={"project": "yok"})).json() == []

    project_scores = (await client.get("/scores/employees", params={"project": "proj", "window_days": 365})).json()
    assert first["employee_id"] in [s["employee_id"] for s in project_scores]
    assert (await client.get("/scores/employees", params={"project": "yok"})).json() == []

    cost = (await client.get(f"/costs/employees/{first['employee_id']}", params={"project": "proj"})).json()
    assert cost["event_count"] == 2
    assert (await client.get("/costs/company", params={"project": "yok"})).json()["event_count"] == 0
