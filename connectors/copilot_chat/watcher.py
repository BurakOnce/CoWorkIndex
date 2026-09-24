"""Copilot Chat için "canlı" yakalama -- Claude Code'un aksine burada bir
hook API'si yok, bu yüzden periyodik olarak `chatSessions/*.jsonl`
dosyalarının değişip değişmediğine (mtime) bakan basit bir bekleme döngüsü
kullanılır.

    python -m connectors.copilot_chat.watcher --interval 15

Arka planda bırakmak için: bir terminalde çalıştır ve açık bırak, ya da
Windows Görev Zamanlayıcı'nda oturum açılışında başlatacak bir görev kur.
Ctrl+C ile durur.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from connectors.copilot_chat import client  # noqa: E402
from connectors.copilot_chat.session_store import find_sessions, parse_session_file  # noqa: E402


def poll_once(cfg: dict, mtimes: dict[str, float], project_filter: str | None) -> dict[str, float]:
    sessions = find_sessions()
    if project_filter:
        sessions = [(p, proj) for p, proj in sessions if proj and project_filter.lower() in proj.lower()]

    new_mtimes = dict(mtimes)
    for path, project in sessions:
        key = str(path)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtimes.get(key) == mtime:
            continue  # dosya değişmedi

        exchanges = parse_session_file(path, project=project)
        if not exchanges:
            new_mtimes[key] = mtime
            continue
        if not client.api_reachable(cfg):
            # mtime kaydedilmez -> bir sonraki turda yeniden denenir
            client.log(f"API erişilemez ({cfg['api_base_url']}), {path.name} sonra denenecek")
            continue
        try:
            summary = client.sync_exchanges(exchanges, cfg, timeout=60.0)
        except Exception as exc:  # noqa: BLE001 -- izleyici hiç çökmemeli
            client.log(f"{path.name}: gönderim hatası {exc!r}, sonra denenecek")
            continue
        new_mtimes[key] = mtime
        if summary["sent"]:
            msg = (
                f"{path.name}: sent={summary['sent']} created={summary['created']} "
                f"updated={summary['updated']} errors={len(summary['errors'])}"
            )
            client.log(msg)
            print(msg, flush=True)
    return new_mtimes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=float, default=15.0, help="Kontrol aralığı (saniye)")
    parser.add_argument("--employee")
    parser.add_argument("--team")
    parser.add_argument("--api")
    parser.add_argument("--project", help="Yalnızca yolu bu metni içeren proje klasörleri")
    args = parser.parse_args(argv)

    cfg = client.load_config()
    if args.employee:
        cfg["employee_full_name"] = args.employee
    if args.team:
        cfg["team_name"] = args.team
    if args.api:
        cfg["api_base_url"] = args.api
    client.save_config(cfg)

    print(f"Copilot Chat izleyici başladı -- her {args.interval:.0f}s'de bir kontrol ediyor. Durdurmak için Ctrl+C.")
    print(f"  employee: {cfg['employee_full_name']}  api: {cfg['api_base_url']}")
    mtimes: dict[str, float] = {}
    try:
        while True:
            mtimes = poll_once(cfg, mtimes, args.project)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Durduruldu.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
