"""Geçmiş Claude Code oturumlarını toplu içe aktarır.

    python -m connectors.claude_code.backfill --employee "Burak Önce"
    python -m connectors.claude_code.backfill --project CoWorkIndex --dry-run

Varsayılan kök: ~/.claude/projects (Claude Code'un transcript dizini).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from connectors.claude_code import client  # noqa: E402
from connectors.claude_code.transcript import find_transcripts, parse_transcript  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Claude Code transcript backfill -> CoWork Index")
    parser.add_argument("--root", default=str(Path.home() / ".claude" / "projects"))
    parser.add_argument("--employee", help="Çalışan tam adı (varsayılan: ~/.cowork_index/config.json)")
    parser.add_argument("--team", help="Çalışan yoksa oluşturulacağı takım")
    parser.add_argument("--api", help="API adresi (varsayılan: config / http://localhost:8000)")
    parser.add_argument("--project", help="Yalnızca yolu bu metni içeren transcript'ler")
    parser.add_argument("--limit", type=int, default=0, help="En fazla bu kadar transcript")
    parser.add_argument("--force", action="store_true", help="Değişmemiş olsa da yeniden gönder")
    parser.add_argument("--dry-run", action="store_true", help="Göndermeden sadece say")
    args = parser.parse_args(argv)

    cfg = client.load_config()
    if args.employee:
        cfg["employee_full_name"] = args.employee
    if args.team:
        cfg["team_name"] = args.team
    if args.api:
        cfg["api_base_url"] = args.api

    paths = find_transcripts(args.root)
    if args.project:
        paths = [p for p in paths if args.project.lower() in str(p).lower()]
    if args.limit:
        paths = paths[: args.limit]
    if not paths:
        print("Transcript bulunamadı:", args.root)
        return 1
    if not args.dry_run and not client.api_reachable(cfg):
        print("API erişilemiyor:", cfg["api_base_url"])
        return 2

    grand = {"transcripts": 0, "exchanges": 0, "sent": 0, "created": 0, "updated": 0, "errors": 0}
    for path in paths:
        exchanges = parse_transcript(path)
        grand["transcripts"] += 1
        grand["exchanges"] += len(exchanges)
        if not exchanges:
            continue
        if args.dry_run:
            print(f"{path.name}: {len(exchanges)} etkileşim (dry-run)")
            continue
        summary = client.sync_exchanges(exchanges, cfg, force=args.force, timeout=600.0)
        grand["sent"] += summary["sent"]
        grand["created"] += summary["created"]
        grand["updated"] += summary["updated"]
        grand["errors"] += len(summary["errors"])
        print(
            f"{path.name}: {len(exchanges)} etkileşim, gönderilen={summary['sent']} "
            f"yeni={summary['created']} güncellenen={summary['updated']} "
            f"sınıflandırıcı={summary.get('classifier', '-')} hata={len(summary['errors'])}"
        )
        for err in summary["errors"][:5]:
            print("   !", err)
    print("TOPLAM:", grand, "| çalışan:", cfg["employee_full_name"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
