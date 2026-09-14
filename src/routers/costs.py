from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.cost_service import compute_cost_summary, compute_cost_summary_by_employee
from src.db import get_session
from src.models import Employee, Team
from src.schemas import CostSummary

router = APIRouter(prefix="/costs", tags=["costs"])


@router.get("/company", response_model=CostSummary)
async def get_company_cost(
    window_days: int | None = None, session: AsyncSession = Depends(get_session)
):
    return await compute_cost_summary(session, scope="company", window_days=window_days)


@router.get("/employees", response_model=list[CostSummary])
async def list_employee_costs(
    window_days: int | None = None, session: AsyncSession = Depends(get_session)
):
    """Tüm çalışanların maliyet/verimlilik özetini döndürür (dashboard'daki
    tam tablo görünümü için)."""
    return await compute_cost_summary_by_employee(session, window_days=window_days)


@router.get("/teams/{team_id}", response_model=CostSummary)
async def get_team_cost(
    team_id: int, window_days: int | None = None, session: AsyncSession = Depends(get_session)
):
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Takım bulunamadı")
    return await compute_cost_summary(session, scope="team", scope_id=team_id, window_days=window_days)


@router.get("/employees/{employee_id}", response_model=CostSummary)
async def get_employee_cost(
    employee_id: int, window_days: int | None = None, session: AsyncSession = Depends(get_session)
):
    employee = await session.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Çalışan bulunamadı")
    return await compute_cost_summary(
        session, scope="employee", scope_id=employee_id, window_days=window_days
    )
