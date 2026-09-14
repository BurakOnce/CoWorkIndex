from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.demo_data import DEFAULT_TOOL, TOOLS
from src.ingestion_service import build_template_workbook, import_from_excel, seed_demo_data

router = APIRouter(prefix="/ingestion", tags=["ingestion"])

TEMPLATE_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.post("/seed-demo-data")
async def trigger_seed_demo_data(
    months: int = 6,
    tool_name: str = DEFAULT_TOOL,
    session: AsyncSession = Depends(get_session),
):
    """Tek tıkla sentetik/test verisi üretir (dashboard'daki demo butonu).

    `tool_name`: bu koşuda üretilecek event'lerin hangi AI aracı/modeli
    üzerinden geldiği varsayılacak (bkz. `src.demo_data.TOOLS`).
    """
    if not 1 <= months <= 24:
        raise HTTPException(status_code=422, detail="months 1 ile 24 arasında olmalı")
    if tool_name not in TOOLS:
        raise HTTPException(
            status_code=422, detail=f"tool_name şunlardan biri olmalı: {TOOLS}"
        )
    return await seed_demo_data(session, months=months, tool_name=tool_name)


@router.get("/template")
async def download_template(session: AsyncSession = Depends(get_session)):
    """Toplu içe aktarma için doldurulacak Excel şablonunu indirir.

    Şablon, kadrodaki mevcut çalışanları bir referans sayfasında listeler
    (kadro sabit olduğu için "events" sayfası bu isimlere referans verir).
    """
    content = await build_template_workbook(session)
    return Response(
        content=content,
        media_type=TEMPLATE_MEDIA_TYPE,
        headers={
            "Content-Disposition": "attachment; filename=ai_usage_maturity_sablon.xlsx"
        },
    )


@router.post("/import-excel")
async def upload_excel(
    file: UploadFile = File(...), session: AsyncSession = Depends(get_session)
):
    """Doldurulmuş Excel dosyasındaki "events" sayfasını toplu olarak
    sisteme işler (kadro sabit olduğundan çalışanlar yalnızca mevcut
    kadro içinden ada göre eşleştirilir, yeni çalışan oluşturulmaz).
    Gerçek bir şirketin kendi AI kullanım logunu (gateway/extension'dan
    dışa aktarılmış olabilecek) bulk import etmesini temsil eder.
    """
    if not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=422, detail="Yalnızca .xlsx dosyaları kabul edilir")

    file_bytes = await file.read()
    result = await import_from_excel(session, file_bytes)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    return result
