from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.models import Employee, Team, Tool
from src.schemas import (
    EmployeeCreate,
    EmployeeRead,
    TeamCreate,
    TeamRead,
    ToolCreate,
    ToolRead,
)

router = APIRouter(tags=["reference-data"])


@router.post("/teams", response_model=TeamRead, status_code=201)
async def create_team(payload: TeamCreate, session: AsyncSession = Depends(get_session)):
    team = Team(**payload.model_dump())
    session.add(team)
    await session.commit()
    await session.refresh(team)
    return team


@router.get("/teams", response_model=list[TeamRead])
async def list_teams(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Team))
    return result.scalars().all()


@router.post("/employees", response_model=EmployeeRead, status_code=201)
async def create_employee(payload: EmployeeCreate, session: AsyncSession = Depends(get_session)):
    team = await session.get(Team, payload.team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="team_id bulunamadı")
    employee = Employee(**payload.model_dump())
    session.add(employee)
    await session.commit()
    await session.refresh(employee)
    return employee


@router.get("/employees", response_model=list[EmployeeRead])
async def list_employees(team_id: int | None = None, session: AsyncSession = Depends(get_session)):
    query = select(Employee)
    if team_id is not None:
        query = query.where(Employee.team_id == team_id)
    result = await session.execute(query)
    return result.scalars().all()


@router.get("/employees/{employee_id}", response_model=EmployeeRead)
async def get_employee(employee_id: int, session: AsyncSession = Depends(get_session)):
    employee = await session.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Çalışan bulunamadı")
    return employee


@router.post("/tools", response_model=ToolRead, status_code=201)
async def create_tool(payload: ToolCreate, session: AsyncSession = Depends(get_session)):
    tool = Tool(**payload.model_dump())
    session.add(tool)
    await session.commit()
    await session.refresh(tool)
    return tool


@router.get("/tools", response_model=list[ToolRead])
async def list_tools(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Tool))
    return result.scalars().all()
