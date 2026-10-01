"""Phase 6 tests: دستیار هوشمند — کش معنایی + بازیابی منابع + مسیریابی مدل."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_daneshyar.db")

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.db import AsyncSessionLocal, Base, engine
from app.services.assistant import jaccard, normalize_query, pick_tier
from scripts.seed import seed


@pytest.fixture()
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture()
async def seeded(client):
    async with AsyncSessionLocal() as session:
        await seed(session)
    yield


def auth(token):
    return {"Authorization": f"Bearer {token}"}


async def login(client, username):
    r = await client.post("/auth/login", json={"username": username, "password": "pass123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


# ------------------------- unit: نرمال‌سازی/شباهت/مسیریابی -------------------------


def test_normalize_query_persian():
    # حذف اعراب/تشریح + ارقام فارسی → لاتین
    assert normalize_query("  تعدادِ زیر‌مجموعه‌ها ۲؟ ") == "تعداد زیر مجموعه ها 2"
    # ي عربی → ی فارسی و ك عربی → ک فارسی
    assert normalize_query("کليد") == normalize_query("کلید")
    assert normalize_query("کتاب") == normalize_query("كتاب")
    # علامت سؤال عربی حذف می‌شود
    assert normalize_query("مجموعه چیست؟") == normalize_query("مجموعه چیست")


def test_jaccard_similarity():
    assert jaccard("a b c", "a b c") == 1.0
    assert jaccard("a b", "c d") == 0.0
    assert 0 < jaccard("a b c", "a b d") < 1


def test_pick_tier_routing():
    assert pick_tier("مجموعه چیست؟") == "small"
    assert pick_tier("چرا تعداد زیرمجموعه‌ها 2 به توان n است و تفاوت آن با توابع چیست؟") == "large"
    assert pick_tier(" ".join(["خیلی"] * 12)) == "large"


# ------------------------- API: چت + کش معنایی -------------------------


@pytest.mark.anyio
async def test_chat_returns_sources_and_persists(client, seeded):
    stok = await login(client, "student1")

    r = await client.post(
        "/assistant/chat",
        headers=auth(stok),
        json={"message": "تعداد زیرمجموعه‌ها چند است؟"},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["reply"]
    assert out["cached"] is False
    # بازیابی باید مبحث «تعداد زیرمجموعه‌ها» را پیدا کند
    assert any("زیرمجموعه" in s["title"] for s in out["sources"])
    conv_id = out["conversation_id"]

    # پیام‌ها ذخیره شدند
    r = await client.get(f"/assistant/conversations/{conv_id}", headers=auth(stok))
    msgs = r.json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["sources"]  # منابع روی پیام هم ثبت شده

    # پرسش تکراری → کش معنایی (cached=True)
    r = await client.post(
        "/assistant/chat",
        headers=auth(stok),
        json={"message": "تعداد زیرمجموعه‌ها چند است؟", "conversation_id": conv_id},
    )
    assert r.json()["cached"] is True
    assert r.json()["model_tier"] == "small"


@pytest.mark.anyio
async def test_chat_cache_is_semantic_not_exact(client, seeded):
    """نرمال‌سازی اعراب/ي عربی/؟ : پرسش متفاوت در متن ولی یکی در نرمال → کش."""
    stok = await login(client, "student1")
    r = await client.post(
        "/assistant/chat", headers=auth(stok), json={"message": "تعداد زیر‌مجموعه‌ها چند است؟"}
    )
    assert r.json()["cached"] is False
    r = await client.post(
        "/assistant/chat", headers=auth(stok), json={"message": "تعدادِ زير مجموعه ها چند است؟"}
    )
    # بعد از نرمال‌سازی دقیقاً یکی است → کش معنایی
    assert r.json()["cached"] is True


@pytest.mark.anyio
async def test_chat_isolation_between_users(client, seeded):
    stok = await login(client, "student1")
    r = await client.post("/assistant/chat", headers=auth(stok), json={"message": "مجموعه چیست"})
    conv_id = r.json()["conversation_id"]

    stok2 = await login(client, "student2")
    r = await client.get(f"/assistant/conversations/{conv_id}", headers=auth(stok2))
    assert r.status_code == 404


@pytest.mark.anyio
async def test_conversations_list(client, seeded):
    stok = await login(client, "student1")
    await client.post("/assistant/chat", headers=auth(stok), json={"message": "نسبت‌های مثلثاتی"})
    r = await client.get("/assistant/conversations", headers=auth(stok))
    assert r.status_code == 200
    assert len(r.json()["conversations"]) >= 1


@pytest.mark.anyio
async def test_cache_never_leaks_personal_data(client, seeded):
    """حریم خصوصی: کش فقط بخش عمومی را نگه می‌دارد؛ وضعیت دانش‌آموز اول
    در پاسخ دانش‌آموز دوم ظاهر نمی‌شود (حتی با پرسش یکسان/مشابه)."""
    q = "تعداد زیرمجموعه‌ها چند است؟"

    # student1 پرسش را می‌پرسد (شواهد دارد → پاسخ شخصی‌شده شامل وضعیت اوست)
    st1 = await login(client, "student1")
    r1 = await client.post("/assistant/chat", headers=auth(st1), json={"message": q})
    assert r1.json()["cached"] is False
    reply1 = r1.json()["reply"]
    # پاسخ اول شامل وضعیت شخصی student1 است (یا حداقل بخش شخصی دارد)

    # student2 با همان پرسش → کش می‌خورد ولی نباید داده‌ای از student1 ببیند
    st2 = await login(client, "student2")
    r2 = await client.post("/assistant/chat", headers=auth(st2), json={"message": q})
    out2 = r2.json()
    assert out2["cached"] is True
    reply2 = out2["reply"]

    # نام دانش‌آموز اول و مقادیر تسلط/ماندگاری اختصاصی او نباید در پاسخ دوم باشد
    assert "محمد رضایی" not in reply2
    # رکورد کش فقط بخش عمومی را نگه داشته (قالب intro || tail)
    from app.models.assistant import SemanticCache
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(SemanticCache))).scalars().all()
        for row in rows:
            assert " || " in row.response, "کش نباید پاسخ کامل/شخصی را نگه دارد"

    # هر دو کاربر پاسخ شخصی خودشان را می‌گیرند: وضعیت student1 در پاسخ او هست
    assert "وضعیت شما" in reply1
    assert "وضعیت شما" in reply2
