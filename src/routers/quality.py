from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.models import QualityCheckRun, QualityCheckStatus
from src.quality_checks import run_all_quality_checks
from src.schemas import QualityCheckRunRead, QualityReport

router = APIRouter(prefix="/quality", tags=["quality"])

_STATUS_SEVERITY = {
    QualityCheckStatus.passed: 0,
    QualityCheckStatus.warning: 1,
    QualityCheckStatus.failed: 2,
}


def _overall_status(checks: list[QualityCheckRun]) -> QualityCheckStatus:
    if not checks:
        return QualityCheckStatus.warning
    worst = max(checks, key=lambda c: _STATUS_SEVERITY[c.status])
    return worst.status


@router.post("/run", response_model=QualityReport, status_code=201)
async def trigger_quality_run(session: AsyncSession = Depends(get_session)):
    checks = await run_all_quality_checks(session)
    return QualityReport(
        generated_at=datetime.now(timezone.utc),
        checks=[QualityCheckRunRead.model_validate(c) for c in checks],
        overall_status=_overall_status(checks),
    )


@router.get("/report", response_model=QualityReport)
async def get_quality_report(session: AsyncSession = Depends(get_session)):
    latest_run_at = (await session.execute(select(QualityCheckRun.run_at).order_by(QualityCheckRun.run_at.desc()).limit(1))).scalar_one_or_none()

    if latest_run_at is None:
        checks: list[QualityCheckRun] = []
    else:
        # run_all_quality_checks() aynı koşudaki tüm kontrollere aynı run_at
        # değerini atar (bkz. quality_checks.py); bu yüzden eşitlikle o
        # koşuyu tek seferde seçebiliriz.
        checks = (
            (
                await session.execute(
                    select(QualityCheckRun)
                    .where(QualityCheckRun.run_at == latest_run_at)
                    .order_by(QualityCheckRun.check_name)
                )
            )
            .scalars()
            .all()
        )

    return QualityReport(
        generated_at=datetime.now(timezone.utc),
        checks=[QualityCheckRunRead.model_validate(c) for c in checks],
        overall_status=_overall_status(checks),
    )
