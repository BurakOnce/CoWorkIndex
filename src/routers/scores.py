from collections import Counter
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.models import Employee, ScoreSnapshot, Team
from src.schemas import CompanyScore, EmployeeScore, ScoreTrendPoint, TeamScore
from src.scoring_service import compute_and_store_employee_score

router = APIRouter(prefix="/scores", tags=["scores"])


async def _latest_snapshot_subquery(session: AsyncSession):
    return (
        select(
            ScoreSnapshot.employee_id,
            func.max(ScoreSnapshot.computed_at).label("latest_computed_at"),
        )
        .group_by(ScoreSnapshot.employee_id)
        .subquery()
    )


def _to_employee_score(employee: Employee, snapshot: ScoreSnapshot) -> EmployeeScore:
    return EmployeeScore(
        employee_id=employee.id,
        full_name=employee.full_name,
        team_id=employee.team_id,
        period_start=snapshot.period_start,
        period_end=snapshot.period_end,
        usage_score=snapshot.usage_score,
        approval_score=snapshot.approval_score,
        dialogue_score=snapshot.dialogue_score,
        tone_score=snapshot.tone_score,
        outcome_score=snapshot.outcome_score,
        critical_thinking_score=snapshot.critical_thinking_score,
        composite_score=snapshot.composite_score,
        archetype=snapshot.archetype,
        computed_at=snapshot.computed_at,
    )


@router.get("/employees", response_model=list[EmployeeScore])
async def list_employee_scores(session: AsyncSession = Depends(get_session)):
    """Skoru hesaplanmış tüm çalışanların en güncel skorlarını döndürür.

    Dashboard'daki "Çalışan Bazlı Analiz" sekmesi bunu kullanır.
    """
    latest_sub = await _latest_snapshot_subquery(session)
    query = (
        select(ScoreSnapshot, Employee)
        .join(
            latest_sub,
            (ScoreSnapshot.employee_id == latest_sub.c.employee_id)
            & (ScoreSnapshot.computed_at == latest_sub.c.latest_computed_at),
        )
        .join(Employee, Employee.id == ScoreSnapshot.employee_id)
        .order_by(Employee.full_name)
    )
    rows = (await session.execute(query)).all()
    return [_to_employee_score(employee, snapshot) for snapshot, employee in rows]


@router.get("/employees/{employee_id}", response_model=EmployeeScore)
async def get_employee_score(employee_id: int, session: AsyncSession = Depends(get_session)):
    employee = await session.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Çalışan bulunamadı")

    snapshot = (
        await session.execute(
            select(ScoreSnapshot)
            .where(ScoreSnapshot.employee_id == employee_id)
            .order_by(ScoreSnapshot.computed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if snapshot is None:
        raise HTTPException(
            status_code=404, detail="Bu çalışan için henüz hesaplanmış bir skor yok"
        )

    return _to_employee_score(employee, snapshot)


@router.post("/employees/{employee_id}/recompute", response_model=EmployeeScore, status_code=201)
async def recompute_employee_score(
    employee_id: int,
    period_end: date | None = None,
    window_days: int = 30,
    session: AsyncSession = Depends(get_session),
):
    """Belirli bir dönem sonu için skoru yeniden hesaplar.

    Üretimde skorlar event sonrası otomatik güncellenir (bkz. POST /events);
    bu endpoint esas olarak event_simulator.py'nin geçmiş dönemler için
    trend snapshot'ları üretebilmesi ve demo/hata giderme amaçlı manuel
    tetikleme için vardır.
    """
    employee = await session.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Çalışan bulunamadı")

    snapshot = await compute_and_store_employee_score(
        session, employee_id, period_end=period_end, window_days=window_days
    )
    return _to_employee_score(employee, snapshot)


@router.get("/teams/{team_id}", response_model=TeamScore)
async def get_team_score(team_id: int, session: AsyncSession = Depends(get_session)):
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Takım bulunamadı")

    latest_sub = await _latest_snapshot_subquery(session)
    query = (
        select(ScoreSnapshot)
        .join(
            latest_sub,
            (ScoreSnapshot.employee_id == latest_sub.c.employee_id)
            & (ScoreSnapshot.computed_at == latest_sub.c.latest_computed_at),
        )
        .join(Employee, Employee.id == ScoreSnapshot.employee_id)
        .where(Employee.team_id == team_id)
    )
    snapshots = (await session.execute(query)).scalars().all()

    if not snapshots:
        raise HTTPException(status_code=404, detail="Bu takım için henüz skor verisi yok")

    archetype_distribution = Counter(s.archetype.value for s in snapshots)
    avg_composite = sum(s.composite_score for s in snapshots) / len(snapshots)

    return TeamScore(
        team_id=team.id,
        team_name=team.name,
        employee_count=len(snapshots),
        avg_composite_score=round(avg_composite, 2),
        archetype_distribution=dict(archetype_distribution),
        period_start=min(s.period_start for s in snapshots),
        period_end=max(s.period_end for s in snapshots),
    )


@router.get("/company", response_model=CompanyScore)
async def get_company_score(
    period_start: date | None = None,
    period_end: date | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Şirket geneli özet.

    `period_start`/`period_end` verilmezse varsayılan olarak **son 30 gün**
    kullanılır (dashboard'un "Şirket Genel Görünüm" sekmesindeki tarih
    aralığı seçicisinin varsayılanı da budur). Belirtilen aralığa denk gelen
    (haftalık üretilen) skor snapshot'ları üzerinden ortalama alınır -- bu,
    "şu tarih aralığına bakayım" senaryosunu, yeniden hesaplama yapmadan,
    zaten var olan geçmiş snapshot'ları kullanarak destekler.
    """
    period_end = period_end or date.today()
    period_start = period_start or (period_end - timedelta(days=30))

    query = select(ScoreSnapshot).where(
        ScoreSnapshot.period_end >= period_start,
        ScoreSnapshot.period_end <= period_end,
    )
    snapshots = (await session.execute(query)).scalars().all()

    if not snapshots:
        raise HTTPException(
            status_code=404, detail="Bu tarih aralığında şirket genelinde skor verisi yok"
        )

    n = len(snapshots)
    archetype_distribution = Counter(s.archetype.value for s in snapshots)
    employee_count = len({s.employee_id for s in snapshots})

    return CompanyScore(
        employee_count=employee_count,
        avg_composite_score=round(sum(s.composite_score for s in snapshots) / n, 2),
        avg_usage_score=round(sum(s.usage_score for s in snapshots) / n, 2),
        avg_approval_score=round(sum(s.approval_score for s in snapshots) / n, 2),
        avg_dialogue_score=round(sum(s.dialogue_score for s in snapshots) / n, 2),
        avg_tone_score=round(sum(s.tone_score for s in snapshots) / n, 2),
        avg_outcome_score=round(sum(s.outcome_score for s in snapshots) / n, 2),
        avg_critical_thinking_score=round(sum(s.critical_thinking_score for s in snapshots) / n, 2),
        archetype_distribution=dict(archetype_distribution),
        period_start=period_start,
        period_end=period_end,
    )


@router.get("/trend", response_model=list[ScoreTrendPoint])
async def get_score_trend(
    period: str = Query(default="monthly", pattern="^(monthly|weekly)$"),
    session: AsyncSession = Depends(get_session),
):
    if period == "monthly":
        # Ayın ilk günü -- SQL Server'ın date_trunc karşılığı yok.
        bucket_expr = func.datefromparts(
            func.year(ScoreSnapshot.period_end), func.month(ScoreSnapshot.period_end), 1
        )
    else:
        # Haftanın ilk günü (sunucunun DATEFIRST ayarına göre).
        bucket_expr = func.dateadd(
            literal_column("day"),
            -(func.datepart(literal_column("weekday"), ScoreSnapshot.period_end) - 1),
            ScoreSnapshot.period_end,
        )

    # Bucket ifadesi bir alt sorguda önceden hesaplanır: SQL Server, aynı
    # karmaşık ifadenin SELECT ve GROUP BY'da tekrarını (aggregate'lerle
    # yan yana) her zaman güvenilir şekilde eşleştiremiyor ve "GROUP BY
    # listesinde değil" hatası verebiliyor -- alt sorgu bunu ortadan kaldırır.
    windowed = select(
        ScoreSnapshot.employee_id,
        ScoreSnapshot.composite_score,
        ScoreSnapshot.period_start,
        ScoreSnapshot.period_end,
        bucket_expr.label("bucket"),
    ).subquery()

    query = (
        select(
            windowed.c.bucket,
            func.avg(windowed.c.composite_score).label("avg_composite"),
            func.count(func.distinct(windowed.c.employee_id)).label("employee_count"),
            func.min(windowed.c.period_start).label("period_start"),
            func.max(windowed.c.period_end).label("period_end"),
        )
        .group_by(windowed.c.bucket)
        .order_by(windowed.c.bucket)
    )
    rows = (await session.execute(query)).all()

    return [
        ScoreTrendPoint(
            period_start=row.period_start,
            period_end=row.period_end,
            avg_composite_score=round(row.avg_composite, 2),
            employee_count=row.employee_count,
        )
        for row in rows
    ]
