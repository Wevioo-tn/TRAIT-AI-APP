"""FastAPI application entrypoint."""
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import router as auth_router
from app.api.routes.traites import router as traites_router
from app.core.config import get_settings
from app.db.session import get_session

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(traites_router, prefix=settings.api_prefix)


@app.get(f"{settings.api_prefix}/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    await session.execute(text("SELECT 1"))
    return {"status": "ok", "environment": settings.environment}
