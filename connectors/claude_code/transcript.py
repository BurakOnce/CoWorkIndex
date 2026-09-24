"""Claude Code konuşma kaydı (JSONL transcript) ayrıştırıcı.

Claude Code her oturumu `~/.claude/projects/<proje>/<session>.jsonl` altında
satır başına bir JSON nesnesi olarak tutar. Bu modül o dosyayı okuyup her
"kullanıcı promptu -> asistan cevabı (+ araç çağrıları)" çiftini bir
`Exchange` nesnesine çevirir. Yalnızca standart kütüphane kullanır; hem
hook (host tarafı) hem de toplu içe aktarma (backfill) bunu paylaşır.

Çıkarılan ham malzeme (metin, araç çağrıları, token kullanımı, zaman
damgaları) API'ye gönderilir; davranışsal sinyallere dönüştürme işi
sunucudaki `src/analysis` modülünde yapılır.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

INTERRUPT_MARKER = "[Request interrupted by user]"
_SYSTEM_TAG_RE = re.compile(
    r"<(system-reminder|ci-monitor-event|local-command-caveat|command-name|command-message|"
    r"command-args|local-command-stdout)>.*?</\1>",
    re.DOTALL,
)
_DENIAL_HINTS = (
    "permission for this action was denied",
    "user doesn't want to proceed",
    "user rejected",
    "user declined",
    "denied by",
    "was not approved",
    "user dismissed",
)
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


@dataclass
class ToolCall:
    name: str
    target: str | None = None
    is_error: bool = False
    denied: bool = False


@dataclass
class Exchange:
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
    assistant_message_count: int = 0
    api_request_count: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("extra", None)
        d["usage"] = {**self.usage, "api_requests": self.api_request_count}
        return d


def _clean_prompt(text: str) -> str:
    text = _SYSTEM_TAG_RE.sub("", text)
    return text.strip()


def _text_blocks(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(parts)
    return ""


def _tool_target(name: str, inp: Any) -> str | None:
    if not isinstance(inp, dict):
        return None
    for key in ("file_path", "path", "notebook_path", "url", "pattern", "command", "description", "prompt"):
        value = inp.get(key)
        if isinstance(value, str) and value.strip():
            value = value.strip().splitlines()[0]
            return value[:160]
    return None


def _result_denied(block: dict) -> bool:
    content = block.get("content")
    text = content if isinstance(content, str) else _text_blocks(content)
    lowered = text.lower()
    return any(hint in lowered for hint in _DENIAL_HINTS)


def iter_records(path: Path) -> Iterator[dict]:
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                yield obj


def _is_human_prompt(obj: dict, text: str) -> bool:
    if obj.get("isMeta") or obj.get("isSidechain"):
        return False
    origin = obj.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
        return False
    return bool(text)


def parse_transcript(path: str | Path, hook_prompt: str | None = None) -> list[Exchange]:
    """Bir transcript dosyasındaki tüm etkileşimleri döndürür.

    `hook_prompt`: UserPromptSubmit hook'undan gelen, henüz dosyaya
    yazılmamış yeni prompt -- son etkileşimin geri bildirimi olarak kullanılır.
    """
    path = Path(path)
    exchanges: list[Exchange] = []
    current: Exchange | None = None
    tool_by_id: dict[str, ToolCall] = {}
    seen_requests: set[str | None] = set()
    session_id = path.stem
    turn = 0

    def close_current() -> None:
        nonlocal current
        if current is not None:
            exchanges.append(current)
            current = None

    for obj in iter_records(path):
        rtype = obj.get("type")
        if rtype not in ("user", "assistant"):
            continue
        if obj.get("isSidechain"):
            continue
        message = obj.get("message") or {}
        content = message.get("content")
        timestamp = obj.get("timestamp")
        session_id = obj.get("sessionId") or session_id

        if rtype == "user":
            blocks = content if isinstance(content, list) else []
            tool_results = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"]
            if tool_results:
                for block in tool_results:
                    call = tool_by_id.get(str(block.get("tool_use_id")))
                    if call is None:
                        continue
                    if block.get("is_error"):
                        call.is_error = True
                    if _result_denied(block):
                        call.denied = True
                continue

            raw_text = _text_blocks(content)
            interrupted = INTERRUPT_MARKER in raw_text
            text = _clean_prompt(raw_text.replace(INTERRUPT_MARKER, ""))
            if interrupted and current is not None:
                current.interrupted = True
            if not _is_human_prompt(obj, text):
                continue

            close_current()
            turn += 1
            current = Exchange(
                session_id=session_id,
                external_id=f"{session_id}:{obj.get('uuid') or turn}",
                turn_index=turn,
                started_at=timestamp or "",
                ended_at=None,
                model=None,
                effort=None,
                prompt_text=text,
                response_text="",
                feedback_text=None,
                tool_calls=[],
                usage={
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
                interrupted=False,
                project=obj.get("cwd"),
                git_branch=obj.get("gitBranch"),
                transcript_path=str(path),
            )
            tool_by_id = {}
            continue

        # assistant
        if current is None:
            continue
        current.assistant_message_count += 1
        current.ended_at = timestamp or current.ended_at
        current.model = message.get("model") or current.model
        # "effort" (low/medium/high) Claude Code'un kendi düşünme bütçesi
        # ayarıdır; obj üzerinde (message içinde değil) durur.
        current.effort = obj.get("effort") or current.effort
        text = _text_blocks(content)
        if text.strip():
            current.response_text = (current.response_text + "\n" + text).strip()
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    call = ToolCall(name=str(block.get("name")), target=_tool_target(str(block.get("name")), block.get("input")))
                    current.tool_calls.append(call)
                    tool_by_id[str(block.get("id"))] = call
        # Claude Code tek bir API cevabını içerik bloğu başına ayrı satıra
        # yazar (metin + tool_use...) ve her satıra aynı usage'ı koyar; aynı
        # isteği yalnızca bir kez say.
        usage = message.get("usage")
        request_key = obj.get("requestId") or message.get("id")
        if isinstance(usage, dict) and request_key not in seen_requests:
            seen_requests.add(request_key)
            current.api_request_count += 1
            for key in current.usage:
                value = usage.get(key)
                if isinstance(value, (int, float)):
                    current.usage[key] += int(value)

    close_current()

    for i, ex in enumerate(exchanges):
        if i + 1 < len(exchanges):
            ex.feedback_text = exchanges[i + 1].prompt_text
        elif hook_prompt:
            ex.feedback_text = _clean_prompt(hook_prompt)
    return exchanges


def find_transcripts(root: str | Path) -> list[Path]:
    root = Path(root)
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*.jsonl") if p.is_file())
