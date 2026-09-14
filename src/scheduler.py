"""APScheduler ile near-real-time skor güncellemesi ve periyodik denetim.

Tek event geldiğinde senkron recompute zaten ucuz ve yeterlidir
(src/routers/events.py). Bu scheduler, senkron yoldan kaçırılmış olabilecek
çalışanları (örn. import sırasında hata sonrası) yakalamak ve düzenli veri
kalitesi denetimi çalıştırmak için ikinci bir güvenlik ağı sağlar.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from src.config import settings
from src.db import async_session_factory
from src.models import Employee
from src.quality_checks import run_all_quality_checks
from src.scoring_service import compute_and_store_employee_score

logger = logging.getLogger("scheduler")

scheduler = AsyncIOScheduler()


async def recompute_all_scores_job() -> None:
    async with async_session_factory() as session:
        employee_ids = (await session.execute(select(Employee.id))).scalars().all()
        for employee_id in employee_ids:
            await compute_and_store_employee_score(session, employee_id)
        logger.info("Scheduler: %d çalışan için skor yeniden hesaplandı", len(employee_ids))


async def run_quality_audit_job() -> None:
    async with async_session_factory() as session:
        checks = await run_all_quality_checks(session)
        logger.info("Scheduler: %d veri kalitesi kontrolü koşuldu", len(checks))


def start_scheduler() -> None:
    if not settings.scheduler_enabled:
        logger.info("Scheduler devre dışı (SCHEDULER_ENABLED=false)")
        return

    scheduler.add_job(
        recompute_all_scores_job,
        "interval",
        minutes=settings.score_recompute_interval_minutes,
        id="recompute_all_scores",
        replace_existing=True,
    )
    scheduler.add_job(
        run_quality_audit_job,
        "interval",
        minutes=settings.quality_audit_interval_minutes,
        id="run_quality_audit",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Scheduler başlatıldı: skor güncelleme her %d dk, kalite denetimi her %d dk",
        settings.score_recompute_interval_minutes,
        settings.quality_audit_interval_minutes,
    )


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
