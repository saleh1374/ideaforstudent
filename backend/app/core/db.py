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
        await conn.run_sync(_ensure_new_columns)


def _ensure_new_columns(sync_conn) -> None:
    """مهاجرت سبک برای دیتابیس‌های موجود (SQLite): افزودن ستون‌هایی که بعداً
    به مدل اضافه شده‌اند — چون create_all جدول‌های موجود را تغییر نمی‌دهد."""
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    columns = {
        (table, col["name"])
        for table in inspector.get_table_names()
        for col in inspector.get_columns(table)
    }
    migrations = [
        ("employments", "district_id", "ALTER TABLE employments ADD COLUMN district_id INTEGER REFERENCES districts(id)"),
    ]
    for table, column, ddl in migrations:
        if (table, column) not in columns and table in inspector.get_table_names():
            sync_conn.execute(text(ddl))
