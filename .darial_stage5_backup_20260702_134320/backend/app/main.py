from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401
from app.api.observability_routes import router as observability_router
from app.api.routes import router
from app.core.config import settings
from app.core.database import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup/shutdown lifecycle.

    MVP note:
    - create_all keeps the current educational/demo setup working;
    - Alembic migrations should replace it before production deployment.
    """
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Darial — enterprise AI observability, FinOps and governance control plane"
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.include_router(observability_router, prefix="/api")


@app.get("/")
def root():
    return {
        "message": "Darial AI Control Center backend is running",
        "version": settings.APP_VERSION,
        "product": "AI Observability, FinOps and Governance",
        "docs_url": "/docs",
        "api_health_url": "/api/health",
        "observability_summary_url": "/api/observability/dashboard/summary",
    }
