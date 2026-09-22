"""CoWork Index API istemcisi + yerel durum (host tarafı, yalnızca stdlib).

Hook ve backfill bu modülü paylaşır. Ayarlar öncelik sırasıyla:
ortam değişkenleri > ~/.cowork_index/config.json > varsayılanlar.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from connectors.claude_code.transcript import Exchange

STATE_DIR = Path(os.environ.get("COWORK_STATE_DIR", Path.home() / ".cowork_index"))
CONFIG_FILE = STATE_DIR / "config.json"
STATE_FILE = STATE_DIR / "claude_code_state.json"
LOG_FILE = STATE_DIR / "hook.log"
CHUNK_SIZE = 20


def load_config() -> dict[str, Any]:
    cfg: dict[str, Any] = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cfg = {}
    cfg.setdefault("api_base_url", "http://localhost:8000")
    cfg.setdefault("employee_full_name", getpass.getuser())
    cfg.setdefault("team_name", None)
    cfg.setdefault("tool_name", "Claude")
    cfg["api_base_url"] = os.environ.get("COWORK_API_BASE_URL", cfg["api_base_url"])
    cfg["employee_full_name"] = os.environ.get("COWORK_EMPLOYEE_NAME", cfg["employee_full_name"])
    cfg["team_name"] = os.environ.get("COWORK_TEAM_NAME", cfg["team_name"])
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state() -> dict[str, str]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def save_state(state: dict[str, str]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def log(message: str) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(message.rstrip() + "\n")
    except OSError:
        pass


def exchange_fingerprint(ex: Exchange) -> str:
    payload = ex.to_payload()
    payload.pop("transcript_path", None)
    return hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def select_changed(exchanges: list[Exchange], state: dict[str, str]) -> list[Exchange]:
    changed = []
    for ex in exchanges:
        if state.get(ex.external_id) != exchange_fingerprint(ex):
            changed.append(ex)
    return changed


def post_exchanges(exchanges: list[Exchange], cfg: dict[str, Any], timeout: float = 60.0) -> list[dict]:
    results: list[dict] = []
    for i in range(0, len(exchanges), CHUNK_SIZE):
        chunk = exchanges[i : i + CHUNK_SIZE]
        body = {
            "source": "claude_code",
            "employee_full_name": cfg["employee_full_name"],
            "team_name": cfg.get("team_name"),
            "tool_name": cfg.get("tool_name", "Claude"),
            "exchanges": [ex.to_payload() for ex in chunk],
        }
        data = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        req = urllib.request.Request(
            cfg["api_base_url"].rstrip("/") + "/connectors/exchanges",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            results.append(json.loads(resp.read().decode("utf-8")))
    return results


def api_reachable(cfg: dict[str, Any], timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(cfg["api_base_url"].rstrip("/") + "/health", timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def sync_exchanges(exchanges: list[Exchange], cfg: dict[str, Any], *, force: bool = False, timeout: float = 60.0) -> dict[str, Any]:
    state = load_state()
    todo = exchanges if force else select_changed(exchanges, state)
    summary = {"total": len(exchanges), "sent": 0, "created": 0, "updated": 0, "errors": []}
    if not todo:
        return summary
    results = post_exchanges(todo, cfg, timeout=timeout)
    for r in results:
        summary["created"] += int(r.get("created", 0))
        summary["updated"] += int(r.get("updated", 0))
        summary["errors"].extend(r.get("errors", []))
        summary["classifier"] = r.get("classifier")
    summary["sent"] = len(todo)
    for ex in todo:
        state[ex.external_id] = exchange_fingerprint(ex)
    save_state(state)
    return summary
