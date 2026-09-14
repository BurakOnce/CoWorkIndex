"""Periyodik veri kalitesi denetimleri.

Write-time doğrulama (Pydantic + veritabanı CHECK constraint'leri) zaten
kirli veriyi baştan reddeder. Burada koşulan kontroller onun tamamlayıcısı:
referans bütünlüğü, tekrar eden kayıt, tazelik (freshness) ve anomali
taraması gibi "veri zamanla nasıl davranıyor" sorularına bakar.
"""

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Employee,
    InteractionEvent,
    QualityCheckRun,
    QualityCheckStatus,
    Tool,
)
from src.utils import utcnow

FRESHNESS_THRESHOLD_HOURS = 48
ANOMALY_DAILY_EVENT_THRESHOLD = 60


async def _check_referential_integrity(session: AsyncSession) -> QualityCheckRun:
    orphan_employee_refs = (
        await session.execute(
            select(func.count())
            .select_from(InteractionEvent)
            .outerjoin(Employee, InteractionEvent.employee_id == Employee.id)
            .where(Employee.id.is_(None))
        )
    ).scalar_one()

    orphan_tool_refs = (
        await session.execute(
            select(func.count())
            .select_from(InteractionEvent)
            .outerjoin(Tool, InteractionEvent.tool_id == Tool.id)
            .where(Tool.id.is_(None))
        )
    ).scalar_one()

    affected = orphan_employee_refs + orphan_tool_refs
    status = QualityCheckStatus.passed if affected == 0 else QualityCheckStatus.failed
    details = (
        f"orphan employee_id referansı: {orphan_employee_refs}, "
        f"orphan tool_id referansı: {orphan_tool_refs}"
    )
    return QualityCheckRun(
        check_name="referential_integrity",
        status=status,
        affected_row_count=affected,
        details=details,
    )


async def _check_duplicate_events(session: AsyncSession) -> QualityCheckRun:
    dup_query = (
        select(
            InteractionEvent.session_id,
            InteractionEvent.employee_id,
            InteractionEvent.occurred_at,
            func.count().label("cnt"),
        )
        .group_by(
            InteractionEvent.session_id, InteractionEvent.employee_id, InteractionEvent.occurred_at
        )
        .having(func.count() > 1)
    )
    duplicates = (await session.execute(dup_query)).all()
    affected = sum(row.cnt - 1 for row in duplicates)
    status = QualityCheckStatus.passed if affected == 0 else QualityCheckStatus.warning
    return QualityCheckRun(
        check_name="duplicate_events",
        status=status,
        affected_row_count=affected,
        details=f"{len(duplicates)} tekrar eden (session_id, employee_id, occurred_at) grubu bulundu",
    )


async def _check_freshness(session: AsyncSession) -> QualityCheckRun:
    latest = (await session.execute(select(func.max(InteractionEvent.occurred_at)))).scalar_one()
    if latest is None:
        return QualityCheckRun(
            check_name="freshness",
            status=QualityCheckStatus.failed,
            affected_row_count=0,
            details="Hiç event bulunamadı",
        )

    age_hours = (utcnow() - latest).total_seconds() / 3600
    status = (
        QualityCheckStatus.passed
        if age_hours <= FRESHNESS_THRESHOLD_HOURS
        else QualityCheckStatus.warning
    )
    return QualityCheckRun(
        check_name="freshness",
        status=status,
        affected_row_count=0,
        details=f"Son event {age_hours:.1f} saat önce geldi (eşik: {FRESHNESS_THRESHOLD_HOURS} saat)",
    )


async def _check_daily_volume_anomaly(session: AsyncSession) -> QualityCheckRun:
    occurred_date = cast(InteractionEvent.occurred_at, Date)
    query = (
        select(
            InteractionEvent.employee_id,
            occurred_date.label("day"),
            func.count().label("cnt"),
        )
        .group_by(InteractionEvent.employee_id, occurred_date)
        .having(func.count() > ANOMALY_DAILY_EVENT_THRESHOLD)
    )
    anomalies = (await session.execute(query)).all()
    affected = len(anomalies)
    status = QualityCheckStatus.passed if affected == 0 else QualityCheckStatus.warning
    return QualityCheckRun(
        check_name="daily_volume_anomaly",
        status=status,
        affected_row_count=affected,
        details=(
            f"{affected} çalışan-gün kombinasyonu günlük {ANOMALY_DAILY_EVENT_THRESHOLD} event "
            "eşiğini aştı"
        ),
    )


async def run_all_quality_checks(session: AsyncSession) -> list[QualityCheckRun]:
    checks = [
        await _check_referential_integrity(session),
        await _check_duplicate_events(session),
        await _check_freshness(session),
        await _check_daily_volume_anomaly(session),
    ]

    # run_at'i burada tek bir Python değeriyle sabitliyoruz: SQL Server'ın
    # GETUTCDATE() server_default'u her INSERT ifadesi için ayrı ayrı
    # değerlendirilir (Postgres'in transaction-sabit now()'ının aksine), bu
    # yüzden 4 satır arasında milisaniyelik farklar oluşabilir. get_quality_report
    # bu koşuyu run_at eşitliğiyle tek seferde seçtiği için değer paylaşılmalı.
    shared_run_at = utcnow()
    for check in checks:
        check.run_at = shared_run_at

    session.add_all(checks)
    await session.commit()
    for check in checks:
        await session.refresh(check)
    return checks
