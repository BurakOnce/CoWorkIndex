"""VS Code / GitHub Copilot Chat oturum kaydı ayrıştırıcı.

**Format**: VS Code, Copilot Chat konuşmalarını
`<VS Code kullanıcı verisi>/workspaceStorage/<hash>/chatSessions/*.jsonl`
altında tutar. Bu **resmi/desteklenen bir API değil** -- VS Code'un iç
depolama biçimidir ve sürüm güncellemeleriyle değişebilir. Dosya, adının
önerdiği gibi gerçekten satır bazlı bir **patch log**'dur (JSONL), tek bir
JSON nesnesi değil:

- İlk satır (`"kind": 0`) oturumun boş/başlangıç anlık görüntüsüdür (`v`
  tüm oturum nesnesidir).
- Sonraki her satır (`"kind": 1` ya da `2`) bir yol-patch'idir:
  `{"k": [<anahtar/indeks yolu>], "v": <yeni değer>}` -- örn.
  `{"k": ["requests", 0, "response"], "v": [...]}` demek
  "kök nesnenin requests[0].response alanını bu değere ayarla" demektir.

Son durumu elde etmek için tüm satırlar sırayla **replay** edilir
(`_replay_patch_log`). Bu, gerçek bir Copilot Chat konuşmasıyla doğrulandı
(bkz. `tests/test_copilot_connector.py`); yine de VS Code güncellemeleriyle
değişebileceği için ayrıştırma kasıtlı olarak **savunmacı** kalır: her metin
alanını birden çok olası şekilde dener, tanıyamadığı bir turu sessizce atlar.

Bilinen sınırlama: "auto" model yönlendirmesinde (`modelId` "auto" ile
bitiyorsa) hangi modelin isteği gerçekte işlediği yerel veride yok; bu
durumda oturumda o an seçili olan model ailesi (`selectedModel.metadata.
family`) gösterge olarak kullanılır -- bu, isteğin GERÇEKTEN o modelle
işlendiğinin garantisi değildir.
"""

from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def _default_vscode_user_dir() -> Path:
    override = os.environ.get("VSCODE_USER_DIR")
    if override:
        return Path(override)
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
        return base / "Code" / "User"
    if system == "Darwin":
        return Path.home() / "Library/Application Support/Code/User"
    return Path.home() / ".config/Code/User"


@dataclass
class ToolCall:
    name: str
    target: str | None = None
    is_error: bool = False
    denied: bool = False


@dataclass
class Exchange:
    """Claude Code bağlayıcısındaki `Exchange` ile aynı alan kümesi --
    `/connectors/exchanges`'in beklediği ortak sözleşme. Bilinçli olarak
    ayrı bir sınıf: iki bağlayıcının transcript biçimleri tamamen farklı,
    yalnızca çıktı şekli ortak."""

    session_id: str
    external_id: str
    turn_index: int
    started_at: str
    ended_at: str | None
    model: str | None
    effort: str | None
    prompt_text: str
    response_text: str
    feedback_text: str | None
    tool_calls: list[ToolCall]
    usage: dict[str, int]
    interrupted: bool
    project: str | None
    git_branch: str | None
    transcript_path: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("extra", None)
        return d


def _iso(ms: float | int | None) -> str | None:
    if not ms:
        return None
    try:
        dt = datetime.fromtimestamp(float(ms) / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _extract_text(value: Any, _depth: int = 0) -> str:
    """Birden çok olası VS Code chat model şeklini dener: düz string,
    {text: ...}, {value: ...}, {parts: [...]}, ya da parça listesi."""
    if _depth > 6 or value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        chunks = [t for t in (_extract_text(v, _depth + 1) for v in value) if t]
        return "\n".join(chunks)
    if isinstance(value, dict):
        for key in ("text", "value", "message", "content", "parts"):
            if key in value:
                t = _extract_text(value[key], _depth + 1)
                if t:
                    return t
    return ""


def _extract_referenced_files(node: Any, out: list[str], _depth: int = 0) -> None:
    if _depth > 8 or node is None:
        return
    if isinstance(node, dict):
        for key in ("uri", "path", "filePath", "resource"):
            v = node.get(key)
            if isinstance(v, str) and ("/" in v or "\\" in v):
                out.append(v)
            elif isinstance(v, dict):
                p = v.get("path") or v.get("fsPath")
                if isinstance(p, str) and p:
                    out.append(p)
        for v in node.values():
            _extract_referenced_files(v, out, _depth + 1)
    elif isinstance(node, list):
        for v in node:
            _extract_referenced_files(v, out, _depth + 1)


def _model_and_effort(request: dict, session_root: dict) -> tuple[str | None, str | None]:
    """Gerçek veriyle doğrulanmış alanlar: `request.modelId` (örn.
    "copilot/auto" -- bir routing takma adı, gerçek model değil) ve
    `session.inputState.modelConfiguration.tier` (low/balance/... eşdeğeri).
    `modelId` "auto" ile bitiyorsa, o an seçili model ailesini gösterge
    olarak kullanırız (bkz. modül docstring'i)."""
    raw_model_id = request.get("modelId")
    model: str | None = None
    if isinstance(raw_model_id, str) and raw_model_id and not raw_model_id.rstrip("/").lower().endswith("auto"):
        model = raw_model_id

    input_state = session_root.get("inputState") or {}
    selected = input_state.get("selectedModel") or {}
    metadata = selected.get("metadata") or {}
    if not model:
        model = metadata.get("family") or metadata.get("name") or selected.get("identifier") or raw_model_id

    effort = (selected.get("modelConfiguration") or {}).get("tier")
    return model, effort


def _replay_patch_log(lines: list[str]) -> dict:
    """`chatSessions/*.jsonl`'daki satır bazlı patch log'unu son duruma
    dönüştürür -- bkz. modül docstring'i."""
    root: dict = {}
    for raw_line in lines:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        path = entry.get("k")
        value = entry.get("v")
        if not path:
            # "kind": 0 -- tam oturum anlık görüntüsü.
            if isinstance(value, dict):
                root = value
            continue

        # ÖZEL DURUM (gerçek veriyle doğrulandı): path tam olarak ["requests"]
        # olduğunda bu bir tam değiştirme değil, bir **ekleme**(append)'dir --
        # her yeni tur, `v` içinde SADECE o yeni isteği taşıyan bir liste
        # olarak gelir; önceki istekleri olduğu gibi bırakıp sona eklemek
        # gerekir. Bunu normal "yolu değiştir" olarak uygularsak (aşağıdaki
        # genel durum gibi), önceki tur sessizce kaybolur.
        if path == ["requests"] and isinstance(value, list):
            existing = root.get("requests")
            if not isinstance(existing, list):
                existing = []
                root["requests"] = existing
            existing.extend(value)
            continue

        node: Any = root
        for key in path[:-1]:
            if isinstance(key, int):
                while len(node) <= key:
                    node.append({})
                node = node[key]
            else:
                if not isinstance(node.get(key), (dict, list)):
                    node[key] = {}
                node = node[key]
        last = path[-1]
        if isinstance(last, int):
            while len(node) <= last:
                node.append(None)
            node[last] = value
        else:
            node[last] = value
    return root


def parse_session_file(path: str | Path, project: str | None = None) -> list[Exchange]:
    path = Path(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    root = _replay_patch_log(lines)
    if not isinstance(root, dict):
        return []

    session_id = str(root.get("sessionId") or path.stem)
    requests = root.get("requests")
    if not isinstance(requests, list) or not requests:
        return []

    exchanges: list[Exchange] = []
    for i, request in enumerate(requests):
        if not isinstance(request, dict):
            continue
        prompt_text = _extract_text(request.get("message"))
        response_text = _extract_text(request.get("response"))
        interrupted = bool(request.get("isCanceled"))
        if not prompt_text and not response_text and not interrupted:
            # Ne isteği ne cevabı okunabildi -- muhtemelen henüz bitmemiş
            # ya da tanımadığımız bir şekil; atla (sessizce başarısız olma).
            continue

        files: list[str] = []
        _extract_referenced_files(request.get("response"), files)
        seen: set[str] = set()
        tool_calls = []
        for f in files:
            if f not in seen:
                seen.add(f)
                tool_calls.append(ToolCall(name="Edit", target=f[:160]))

        model, effort = _model_and_effort(request, root)
        usage: dict[str, int] = {}
        prompt_tokens = request.get("promptTokens")
        completion_tokens = request.get("completionTokens")
        if isinstance(prompt_tokens, (int, float)):
            usage["input_tokens"] = int(prompt_tokens)
        if isinstance(completion_tokens, (int, float)):
            usage["output_tokens"] = int(completion_tokens)
        started_at = _iso(request.get("timestamp")) or _iso(root.get("creationDate")) or ""
        elapsed = ((request.get("result") or {}).get("timings") or {}).get("totalElapsed")
        ended_at = None
        if started_at and isinstance(elapsed, (int, float)):
            try:
                base_ms = float(request.get("timestamp") or root.get("creationDate") or 0)
                ended_at = _iso(base_ms + elapsed)
            except (TypeError, ValueError):
                ended_at = None

        exchanges.append(
            Exchange(
                session_id=session_id,
                external_id=f"{session_id}:{request.get('requestId') or i}",
                turn_index=i + 1,
                started_at=started_at,
                ended_at=ended_at,
                model=model,
                effort=effort,
                prompt_text=prompt_text,
                response_text=response_text,
                feedback_text=None,
                tool_calls=tool_calls,
                usage=usage,
                interrupted=interrupted,
                project=project or root.get("cwd"),
                git_branch=None,
                transcript_path=str(path),
            )
        )

    for i, ex in enumerate(exchanges):
        if i + 1 < len(exchanges):
            ex.feedback_text = exchanges[i + 1].prompt_text
    return exchanges


def iter_workspace_folders(vscode_user_dir: str | Path) -> Iterator[tuple[Path, str | None]]:
    """(chatSessions klasörü, proje klasörü) çiftlerini döndürür."""
    storage = Path(vscode_user_dir) / "workspaceStorage"
    if not storage.exists():
        return
    for ws_dir in storage.iterdir():
        chat_dir = ws_dir / "chatSessions"
        if not chat_dir.is_dir():
            continue
        project = None
        ws_json = ws_dir / "workspace.json"
        if ws_json.exists():
            try:
                data = json.loads(ws_json.read_text(encoding="utf-8"))
                uri = data.get("folder") or data.get("workspace") or ""
                # file:///c%3A/Projects/Python/CoWorkIndex -> C:/Projects/Python/CoWorkIndex
                from urllib.parse import unquote, urlparse

                parsed = urlparse(uri)
                if parsed.scheme == "file":
                    project = unquote(parsed.path).lstrip("/")
            except (json.JSONDecodeError, OSError):
                project = None
        yield chat_dir, project


def find_sessions(vscode_user_dir: str | Path | None = None) -> list[tuple[Path, str | None]]:
    """Tüm workspaceStorage klasörlerindeki `chatSessions/*.jsonl` dosyalarını,
    ait oldukları proje klasörüyle eşleştirip döndürür."""
    root = vscode_user_dir or _default_vscode_user_dir()
    out: list[tuple[Path, str | None]] = []
    for chat_dir, project in iter_workspace_folders(root):
        for f in sorted(chat_dir.glob("*.jsonl")):
            out.append((f, project))
    return out
