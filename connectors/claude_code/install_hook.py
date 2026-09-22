"""Claude Code ayarlarına (~/.claude/settings.json) CoWork Index hook'unu kaydeder.

    python -m connectors.claude_code.install_hook --employee "Burak Önce"
    python -m connectors.claude_code.install_hook --uninstall

Idempotent: aynı komut zaten kayıtlıysa tekrar eklemez. Mevcut diğer hook
ayarlarına dokunmaz.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from connectors.claude_code import client  # noqa: E402

SETTINGS_FILE = Path.home() / ".claude" / "settings.json"
HOOK_EVENTS = ("Stop", "UserPromptSubmit")
MARKER = "connectors/claude_code/hook.py"


def hook_command() -> str:
    hook_path = Path(__file__).resolve().parent / "hook.py"
    return f'"{sys.executable}" "{hook_path}"'


def _load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise SystemExit(f"{SETTINGS_FILE} geçerli JSON değil; elle düzeltin.")
    return {}


def _is_ours(entry: dict) -> bool:
    for h in entry.get("hooks", []):
        if MARKER.replace("/", "\\") in str(h.get("command", "")) or MARKER in str(h.get("command", "")).replace("\\", "/"):
            return True
    return False


def install(employee: str | None, team: str | None, api: str | None) -> None:
    settings = _load_settings()
    hooks = settings.setdefault("hooks", {})
    command = hook_command()
    for event in HOOK_EVENTS:
        entries = hooks.setdefault(event, [])
        entries[:] = [e for e in entries if not _is_ours(e)]
        entries.append({"hooks": [{"type": "command", "command": command, "timeout": 60}]})
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")

    cfg = client.load_config()
    if employee:
        cfg["employee_full_name"] = employee
    if team:
        cfg["team_name"] = team
    if api:
        cfg["api_base_url"] = api
    client.save_config(cfg)
    print(f"Hook kaydedildi: {SETTINGS_FILE}")
    print(f"  events   : {', '.join(HOOK_EVENTS)}")
    print(f"  command  : {command}")
    print(f"Bağlayıcı ayarı: {client.CONFIG_FILE}")
    print(f"  employee : {cfg['employee_full_name']}")
    print(f"  api      : {cfg['api_base_url']}")
    print("Not: Claude Code'un yeni ayarı görmesi için oturumu yeniden başlatın.")


def uninstall() -> None:
    settings = _load_settings()
    hooks = settings.get("hooks", {})
    removed = 0
    for event in HOOK_EVENTS:
        entries = hooks.get(event, [])
        before = len(entries)
        entries[:] = [e for e in entries if not _is_ours(e)]
        removed += before - len(entries)
        if not entries:
            hooks.pop(event, None)
    if not hooks:
        settings.pop("hooks", None)
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Kaldırılan hook girdisi: {removed}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--employee")
    parser.add_argument("--team")
    parser.add_argument("--api")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args(argv)
    if args.uninstall:
        uninstall()
    else:
        install(args.employee, args.team, args.api)
    return 0


if __name__ == "__main__":
    sys.exit(main())
