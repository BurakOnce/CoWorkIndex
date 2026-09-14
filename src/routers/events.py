from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.models import InteractionEvent
from src.schemas import (
    InteractionEventBatchCreate,
    InteractionEventBatchResult,
    InteractionEventCreate,
    InteractionEventRead,
)
from src.scoring_service import compute_and_store_employee_score

router = APIRouter(prefix="/events", tags=["events"])


@router.post("", response_model=InteractionEventRead, status_code=201)
async def create_event(payload: InteractionEventCreate, session: AsyncSession = Depends(get_session)):
    event = InteractionEvent(**payload.model_dump())
    session.add(event)
    try:
        await session.commit()
    except Exception as exc:  # FK ihlali, CHECK constraint ihlali vb.
        await session.rollback()
        raise HTTPException(status_code=422, detail=f"Event kaydedilemedi: {exc}") from exc
    await session.refresh(event)

    # Near-real-time skor güncellemesi: tek event geldiğinde küçük veri
    # hacminde bu senkron recompute ucuzdur. Yüksek trafikte scheduler.py
    # bunu periyodik toplu güncellemeye devrederdi.
    await compute_and_store_employee_score(session, event.employee_id)

    return event


@router.post("/batch", response_model=InteractionEventBatchResult, status_code=201)
async def create_events_batch(
    payload: InteractionEventBatchCreate, session: AsyncSession = Depends(get_session)
):
    accepted = 0
    errors: list[str] = []
    touched_employee_ids: set[int] = set()

    for item in payload.events:
        event = InteractionEvent(**item.model_dump())
        session.add(event)
        try:
            await session.commit()
            accepted += 1
            touched_employee_ids.add(item.employee_id)
        except Exception as exc:
            await session.rollback()
            errors.append(str(exc))

    for employee_id in touched_employee_ids:
        await compute_and_store_employee_score(session, employee_id)

    return InteractionEventBatchResult(
        accepted_count=accepted, rejected_count=len(errors), errors=errors
    )
