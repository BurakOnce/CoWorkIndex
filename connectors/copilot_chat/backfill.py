"""VS Code Copilot Chat oturumlarını toplu içe aktarır.

    python -m connectors.copilot_chat.backfill --employee "Burak Önce"
    python -m connectors.copilot_chat.backfill --dry-run --debug

`--debug`, ayrıştıramadığı ya da boş bulduğu dosyaları da listeler --
bu format resmi olmadığından ilk gerçek Copilot konuşmandan sonra bunu
çalıştırıp çıkışı kontrol etmen önerilir.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from connectors.copilot_chat import client  # noqa: E402
from connectors.copilot_chat.session_store import find_sessions, parse_session_file  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VS Code Copilot Chat backfill -> CoWork Index")
    parser.add_argument("--vscode-user-dir", help="Varsayılan: %%APPDATA%%/Code/User (VSCODE_USER_DIR ile de ayarlanabilir)")
    parser.add_argument("--employee", help="Çalışan tam adı (varsayılan: ~/.cowork_index/copilot_chat_config.json)")
    parser.add_argument("--team")
    parser.add_argument("--api")
    parser.add_argument("--project", help="Yalnızca yolu bu metni içeren proje klasörleri")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--debug", action="store_true", help="Boş/ayrıştırılamayan dosyaları da göster")
    args = parser.parse_args(argv)

    cfg = client.load_config()
    if args.employee:
        cfg["employee_full_name"] = args.employee
    if args.team:
        cfg["team_name"] = args.team
    if args.api:
        cfg["api_base_url"] = args.api

    sessions = find_sessions(args.vscode_user_dir)
    if args.project:
        sessions = [(p, proj) for p, proj in sessions if proj and args.project.lower() in proj.lower()]
    if not sessions:
        print("Copilot Chat oturum dosyası bulunamadı (VS Code User dizini altında workspaceStorage/*/chatSessions).")
        return 1
    if not args.dry_run and not client.api_reachable(cfg):
        print("API erişilemiyor:", cfg["api_base_url"])
        return 2

    grand = {"files": 0, "exchanges": 0, "sent": 0, "created": 0, "updated": 0, "errors": 0, "empty_or_unparsed": 0}
    for path, project in sessions:
        grand["files"] += 1
        exchanges = parse_session_file(path, project=project)
        if not exchanges:
            grand["empty_or_unparsed"] += 1
            if args.debug:
                print(f"{path.name}: 0 etkileşim (boş ya da tanınamayan şekil) [{project}]")
            continue
        grand["exchanges"] += len(exchanges)
        if args.dry_run:
            print(f"{path.name}: {len(exchanges)} etkileşim (dry-run) [{project}]")
            continue
        summary = client.sync_exchanges(exchanges, cfg, force=args.force, timeout=600.0)
        grand["sent"] += summary["sent"]
        grand["created"] += summary["created"]
        grand["updated"] += summary["updated"]
        grand["errors"] += len(summary["errors"])
        print(
            f"{path.name}: {len(exchanges)} etkileşim, gönderilen={summary['sent']} "
            f"yeni={summary['created']} güncellenen={summary['updated']} hata={len(summary['errors'])}"
        )
        for err in summary["errors"][:5]:
            print("   !", err)

    print("TOPLAM:", grand, "| çalışan:", cfg["employee_full_name"])
    if grand["exchanges"] == 0:
        print(
            "Uyarı: hiç etkileşim bulunamadı. Ya henüz Copilot Chat ile gerçek bir "
            "konuşma yapılmadı, ya da VS Code'un iç depolama biçimi bu sürümde "
            "farklı -- `--debug` ile dosya listesini kontrol edin."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
