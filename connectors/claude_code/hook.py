"""Claude Code hook giriş noktası (Stop + UserPromptSubmit).

Claude Code, ayarlarda kayıtlı bu komutu her cevap bittiğinde (Stop) ve her
yeni prompt gönderildiğinde (UserPromptSubmit) çalıştırır; stdin'e oturum
bilgisini JSON olarak verir. Biz o oturumun transcript'ini okuyup değişen
etkileşimleri CoWork Index API'sine göndeririz.

Kural: hook Claude'u asla bloklamamalı -- her hata yutulur, çıkış kodu 0.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from connectors.claude_code import client  # noqa: E402
from connectors.claude_code.transcript import parse_transcript  # noqa: E402


def main() -> int:
    if os.environ.get("COWORK_HOOK_DISABLED"):
        return 0
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        return 0

    transcript_path = data.get("transcript_path")
    event_name = data.get("hook_event_name", "?")
    hook_prompt = data.get("prompt") if event_name == "UserPromptSubmit" else None
    if not transcript_path or not Path(transcript_path).exists():
        client.log(f"{datetime.now().astimezone().isoformat(timespec="seconds")} {event_name}: transcript yok ({transcript_path})")
        return 0

    cfg = client.load_config()
    try:
        exchanges = parse_transcript(transcript_path, hook_prompt=hook_prompt)
        if not client.api_reachable(cfg):
            client.log(f"{datetime.now().astimezone().isoformat(timespec="seconds")} {event_name}: API erişilemez ({cfg['api_base_url']})")
            return 0
        summary = client.sync_exchanges(exchanges, cfg, timeout=50.0)
        client.log(
            f"{datetime.now().astimezone().isoformat(timespec="seconds")} {event_name} session={data.get('session_id')} "
            f"total={summary['total']} sent={summary['sent']} created={summary['created']} "
            f"updated={summary['updated']} classifier={summary.get('classifier')} errors={len(summary['errors'])}"
        )
    except Exception as exc:  # noqa: BLE001 -- hook hiçbir koşulda Claude'u düşürmemeli
        client.log(f"{datetime.now().astimezone().isoformat(timespec="seconds")} {event_name}: HATA {exc!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
