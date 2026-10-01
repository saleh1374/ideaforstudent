from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_models() -> None:
    from app import models  # noqa: F401  (register all models)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
