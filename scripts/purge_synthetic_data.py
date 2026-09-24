"""Sentetik/demo/Excel verisini siler; yalnızca bağlayıcı (gerçek AI) verisi kalır.

    python -m scripts.purge_synthetic_data          # sil ve skorları yeniden hesapla
    python -m scripts.purge_synthetic_data --dry-run

Silinenler: `source` alanı boş olan event'ler (demo üretici, Excel, simülatör),
hiç event'i kalmayan çalışanların skor snapshot'ları ve kendileri, boş kalan
takımlar. Bağlayıcı event'lerine (source dolu) dokunulmaz.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import delete, exists, select

from src.db import async_session_factory as SessionLocal
from src.models import Employee, InteractionEvent, ScoreSnapshot, Team
from src.scoring_service import compute_and_store_employee_score


async def main(dry_run: bool) -> None:
    async with SessionLocal() as session:
        synthetic_events = (
            await session.execute(select(InteractionEvent.id).where(InteractionEvent.source.is_(None)))
        ).scalars().all()
        print(f"sentetik event: {len(synthetic_events)}")
        # pytest'in ürettiği bağlayıcı fixture'ları ("Test Connector <id>",
        # "Test Copilot <id>", ilerideki bağlayıcılar da aynı "Test <Kaynak> "
        # önekini kullanmalı ki burada tek desenle yakalansın).
        test_employee_ids = (
            await session.execute(select(Employee.id).where(Employee.full_name.like("Test %")))
        ).scalars().all()
        print(f"test fixture çalışanı: {len(test_employee_ids)}")
        if not dry_run:
            await session.execute(delete(InteractionEvent).where(InteractionEvent.source.is_(None)))
            if test_employee_ids:
                await session.execute(
                    delete(InteractionEvent).where(InteractionEvent.employee_id.in_(test_employee_ids))
                )
            await session.flush()

        has_events = exists().where(InteractionEvent.employee_id == Employee.id)
        orphan_employee_ids = (
            await session.execute(select(Employee.id).where(~has_events))
        ).scalars().all()
        print(f"event'i kalmayan çalışan: {len(orphan_employee_ids)}")
        if not dry_run and orphan_employee_ids:
            await session.execute(delete(ScoreSnapshot).where(ScoreSnapshot.employee_id.in_(orphan_employee_ids)))
            await session.execute(delete(Employee).where(Employee.id.in_(orphan_employee_ids)))
            await session.flush()

        has_members = exists().where(Employee.team_id == Team.id)
        empty_team_ids = (await session.execute(select(Team.id).where(~has_members))).scalars().all()
        print(f"boş takım: {len(empty_team_ids)}")
        if not dry_run and empty_team_ids:
            await session.execute(delete(Team).where(Team.id.in_(empty_team_ids)))

        if dry_run:
            await session.rollback()
            return
        await session.commit()

        remaining = (await session.execute(select(Employee.id))).scalars().all()
        # Kalan çalışanların snapshot'ları sentetik event'leri de içeriyordu;
        # yalnızca gerçek veriyle yeniden hesapla.
        await session.execute(delete(ScoreSnapshot).where(ScoreSnapshot.employee_id.in_(remaining)))
        await session.commit()
        for employee_id in remaining:
            await compute_and_store_employee_score(session, employee_id)
        print(f"kalan çalışan: {len(remaining)} -- skorlar yeniden hesaplandı")


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
