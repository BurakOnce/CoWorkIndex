"""Gerçek AI araçlarından canlı veri alan bağlayıcı uç noktaları.

Akış: bağlayıcı (örn. Claude Code hook'u) ham etkileşimi gönderir ->
sunucu davranışsal sinyalleri çıkarır (heuristik ya da Claude) ->
`interaction_events`'e upsert -> (açıksa) içerik `interaction_contents`'e
-> ilgili çalışanın skoru anında yeniden hesaplanır.
"""

from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.analysis import claude_classifier
from src.analysis.extractor import extract
from src.config import settings
from src.cost_service import _event_cost_usd, _load_pricing
from src.db import get_session
from src.models import (
    ActionType,
    Employee,
    InteractionContent,
    InteractionEvent,
    OutcomeStatus,
    PersuasionDirection,
    TaskCategory,
    Team,
    Tool,
)
from src.schemas import (
    ConnectorExchangeBatch,
    ConnectorExchangeResult,
    ConnectorSourceStatus,
    ConnectorStatus,
    LiveInteractionRead,
    ProjectSummary,
)
from src.scoring_service import compute_and_store_employee_score

router = APIRouter(prefix="/connectors", tags=["connectors"])


def project_short_name(path: str | None) -> str | None:
    """"C:\\Projects\\Python\\CoWorkIndex" -> "CoWorkIndex". Aynı proje farklı
    klasör yollarından (örn. taşınmış/fork'lanmış) gelse de tek isim altında
    toplanır; tam yol içerik tablosunda saklı kalır."""
    if not path:
        return None
    name = path.replace("\\", "/").rstrip("/").split("/")[-1].strip()
    return name[:200] or None


async def _resolve_employee(session: AsyncSession, full_name: str, team_name: str | None, role: str | None) -> Employee:
    employee = (
        await session.execute(select(Employee).where(Employee.full_name == full_name))
    ).scalar_one_or_none()
    if employee is not None:
        return employee
    team_name = team_name or settings.connector_default_team
    team = (await session.execute(select(Team).where(Team.name == team_name))).scalar_one_or_none()
    if team is None:
        team = Team(name=team_name, department="Belirtilmemiş")
        session.add(team)
        await session.flush()
    employee = Employee(
        full_name=full_name,
        team_id=team.id,
        role=role or settings.connector_default_role,
        hire_date=date.today(),
    )
    session.add(employee)
    await session.flush()
    return employee


async def _resolve_tool(session: AsyncSession, name: str) -> Tool:
    tool = (await session.execute(select(Tool).where(Tool.name == name))).scalar_one_or_none()
    if tool is None:
        tool = Tool(name=name)
        session.add(tool)
        await session.flush()
    return tool


@router.post("/exchanges", response_model=ConnectorExchangeResult, status_code=201)
async def ingest_exchanges(payload: ConnectorExchangeBatch, session: AsyncSession = Depends(get_session)):
    if not payload.exchanges:
        raise HTTPException(status_code=422, detail="exchanges boş olamaz")

    employee = await _resolve_employee(session, payload.employee_full_name, payload.team_name, payload.role)
    tool = await _resolve_tool(session, payload.tool_name)
    await session.commit()

    created = updated = 0
    errors: list[str] = []
    classifier_used = "heuristic"

    for ex in payload.exchanges:
        tool_calls = [t.model_dump() for t in ex.tool_calls]
        try:
            result = await extract(
                prompt_text=ex.prompt_text,
                response_text=ex.response_text,
                feedback_text=ex.feedback_text,
                tool_calls=tool_calls,
                usage=ex.usage,
                interrupted=ex.interrupted,
                turn_index=ex.turn_index,
            )
        except Exception as exc:  # sinyal çıkarımı hiçbir zaman ingest'i düşürmemeli
            errors.append(f"{ex.external_id}: extract failed: {exc}")
            continue
        classifier_used = result.classifier

        existing = (
            await session.execute(
                select(InteractionEvent)
                .options(selectinload(InteractionEvent.content))
                .where(InteractionEvent.source == payload.source, InteractionEvent.external_id == ex.external_id)
            )
        ).scalar_one_or_none()

        fields = dict(result.event_fields)
        fields["action_type"] = ActionType(fields["action_type"])
        fields["persuasion_direction"] = PersuasionDirection(fields["persuasion_direction"])
        fields["outcome_status"] = OutcomeStatus(fields["outcome_status"])
        fields["task_category"] = TaskCategory(fields["task_category"])
        base = {
            "employee_id": employee.id,
            "tool_id": tool.id,
            "occurred_at": ex.started_at,
            "session_id": ex.session_id[:64],
            "source": payload.source,
            "external_id": ex.external_id,
            "project": project_short_name(ex.project),
            **fields,
        }
        if existing is None:
            event = InteractionEvent(**base)
            session.add(event)
            existing_content = None
            created += 1
        else:
            event = existing
            for key, value in base.items():
                setattr(event, key, value)
            existing_content = existing.content  # selectinload ile yüklendi
            updated += 1
        await session.flush()

        if settings.capture_content:
            content = existing_content or InteractionContent(event_id=event.id)
            content.model = ex.model
            content.project = ex.project
            content.prompt_text = ex.prompt_text
            content.response_text = ex.response_text
            content.feedback_text = ex.feedback_text
            content.tool_calls_json = json.dumps(tool_calls, ensure_ascii=False)
            content.usage_json = json.dumps(ex.usage, ensure_ascii=False)
            content.signals_json = json.dumps(result.signals, ensure_ascii=False, default=str)
            content.classifier = result.classifier
            content.started_at = ex.started_at
            content.ended_at = ex.ended_at
            if existing_content is None:
                session.add(content)
        elif existing_content is not None:
            # İçerik yakalama sonradan kapatıldıysa eski içerik de silinir.
            await session.delete(existing_content)

        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            errors.append(f"{ex.external_id}: {exc}")

    await compute_and_store_employee_score(session, employee.id)

    return ConnectorExchangeResult(
        employee_id=employee.id,
        employee_full_name=employee.full_name,
        received=len(payload.exchanges),
        created=created,
        updated=updated,
        classifier=classifier_used,
        capture_content=settings.capture_content,
        errors=errors,
    )


@router.get("/interactions", response_model=list[LiveInteractionRead])
async def list_interactions(
    limit: int = Query(default=50, ge=1, le=500),
    employee_id: int | None = None,
    source: str | None = None,
    project: str | None = None,
    include_content: bool = True,
    session: AsyncSession = Depends(get_session),
):
    """Bağlayıcılardan gelen son etkileşimler (canlı akış görünümü)."""
    query = (
        select(InteractionEvent, Employee.full_name, Tool.name)
        .join(Employee, Employee.id == InteractionEvent.employee_id)
        .join(Tool, Tool.id == InteractionEvent.tool_id)
        .options(selectinload(InteractionEvent.content))
        .where(InteractionEvent.source.is_not(None))
        .order_by(InteractionEvent.occurred_at.desc(), InteractionEvent.id.desc())
        .limit(limit)
    )
    if employee_id is not None:
        query = query.where(InteractionEvent.employee_id == employee_id)
    if source:
        query = query.where(InteractionEvent.source == source)
    if project:
        query = query.where(InteractionEvent.project == project)

    rows = (await session.execute(query)).all()
    pricing = _load_pricing()
    out: list[LiveInteractionRead] = []
    for event, employee_name, tool_name in rows:
        content = event.content
        item = LiveInteractionRead(
            event_id=event.id,
            employee_id=event.employee_id,
            employee_full_name=employee_name,
            tool_name=tool_name,
            source=event.source,
            external_id=event.external_id,
            session_id=event.session_id,
            occurred_at=event.occurred_at,
            dialogue_turn_count=event.dialogue_turn_count,
            action_type=event.action_type,
            had_disagreement=event.had_disagreement,
            persuasion_direction=event.persuasion_direction,
            outcome_status=event.outcome_status,
            critical_check_flag=event.critical_check_flag,
            task_category=event.task_category,
            directive_language_ratio=event.directive_language_ratio,
            politeness_marker_count=event.politeness_marker_count,
            avg_sentence_length=event.avg_sentence_length,
            exclamation_density=event.exclamation_density,
            input_tokens=event.input_tokens,
            output_tokens=event.output_tokens,
            cost_usd=round(
                _event_cost_usd(
                    pricing, tool_name, event.input_tokens, event.output_tokens,
                    content.model if content is not None else None,
                ),
                6,
            ),
        )
        item.project = event.project
        if content is not None:
            item.model = content.model
            item.classifier = content.classifier
            if include_content:
                item.prompt_text = content.prompt_text
                item.response_text = content.response_text
                item.feedback_text = content.feedback_text
                item.tool_calls = json.loads(content.tool_calls_json) if content.tool_calls_json else None
                item.signals = json.loads(content.signals_json) if content.signals_json else None
        out.append(item)
    return out


@router.get("/projects", response_model=list[ProjectSummary])
async def list_projects(session: AsyncSession = Depends(get_session)):
    """Bağlayıcı verisindeki projeler (dashboard'daki proje filtresi)."""
    rows = (
        await session.execute(
            select(
                InteractionEvent.project,
                func.count(InteractionEvent.id),
                func.count(func.distinct(InteractionEvent.employee_id)),
                func.count(func.distinct(InteractionEvent.session_id)),
                func.min(InteractionEvent.occurred_at),
                func.max(InteractionEvent.occurred_at),
            )
            .where(InteractionEvent.project.is_not(None))
            .group_by(InteractionEvent.project)
            .order_by(func.max(InteractionEvent.occurred_at).desc())
        )
    ).all()
    return [
        ProjectSummary(
            project=r[0],
            event_count=r[1],
            employee_count=r[2],
            session_count=r[3],
            first_occurred_at=r[4],
            last_occurred_at=r[5],
        )
        for r in rows
    ]


@router.get("/status", response_model=ConnectorStatus)
async def connector_status(session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(
            select(
                InteractionEvent.source,
                func.count(InteractionEvent.id),
                func.count(func.distinct(InteractionEvent.session_id)),
                func.count(func.distinct(InteractionEvent.employee_id)),
                func.min(InteractionEvent.occurred_at),
                func.max(InteractionEvent.occurred_at),
            )
            .where(InteractionEvent.source.is_not(None))
            .group_by(InteractionEvent.source)
        )
    ).all()
    mode = (settings.signal_classifier or "auto").lower()
    return ConnectorStatus(
        capture_content=settings.capture_content,
        classifier_mode=mode,
        claude_available=claude_classifier.available(),
        sources=[
            ConnectorSourceStatus(
                source=r[0],
                event_count=r[1],
                session_count=r[2],
                employee_count=r[3],
                first_occurred_at=r[4],
                last_occurred_at=r[5],
            )
            for r in rows
        ],
    )
