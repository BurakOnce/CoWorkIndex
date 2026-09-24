"""interaction_events.project'i, interaction_contents'teki tam yoldan
`project_short_name` ile YENİDEN hesaplar. `project_short_name` mantığı
değiştiğinde (örn. bir proje kökünü artık daha doğru tanıyoruz) geçmiş
kayıtları düzeltmek için kullanılır -- bağlayıcıları yeniden çalıştırmadan.

    python -m scripts.recompute_project_names
    python -m scripts.recompute_project_names --dry-run
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from src.db import async_session_factory as SessionLocal
from src.models import InteractionContent, InteractionEvent
from src.routers.connectors import project_short_name


async def main(dry_run: bool) -> None:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(InteractionEvent.id, InteractionEvent.project, InteractionContent.project)
                .join(InteractionContent, InteractionContent.event_id == InteractionEvent.id)
            )
        ).all()
        changed = 0
        for event_id, old_short, full_path in rows:
            new_short = project_short_name(full_path)
            if new_short != old_short:
                changed += 1
                print(f"  event {event_id}: {old_short!r} -> {new_short!r}  (yol: {full_path})")
                if not dry_run:
                    event = await session.get(InteractionEvent, event_id)
                    event.project = new_short
        print(f"toplam event: {len(rows)}, değişen: {changed}")
        if not dry_run:
            await session.commit()


async def _run(dry_run: bool) -> None:
    try:
        await main(dry_run)
    finally:
        from src.db import engine

        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(_run(args.dry_run))
