from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.routers import connectors, costs, events, ingestion, quality, reference_data, scores
from src.scheduler import shutdown_scheduler, start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(
    title="CoWork Index API",
    description=(
        "Çalışanların AI araçlarıyla etkileşimlerinden, prompt içeriğini hiç "
        "okumadan/saklamadan, yalnızca davranışsal meta-sinyalleri toplayarak "
        "olgunluk skoru ve davranış arketipi üreten API."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(reference_data.router)
app.include_router(events.router)
app.include_router(scores.router)
app.include_router(quality.router)
app.include_router(ingestion.router)
app.include_router(costs.router)
app.include_router(connectors.router)


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}
