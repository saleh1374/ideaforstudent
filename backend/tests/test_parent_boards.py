"""Phase 5 tests: پنل والدین (§17) + بردها با نام مستعار و حداقل جمعیت ۱۰."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_daneshyar.db")

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.db import AsyncSessionLocal, Base, engine
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


# ------------------------- پنل والدین -------------------------


@pytest.mark.anyio
async def test_parent_sees_only_own_child(client, seeded):
    ptok = await login(client, "parent1")

    r = await client.get("/parent/children", headers=auth(ptok))
    assert r.status_code == 200
    children = r.json()["children"]
    assert len(children) == 1
    child_id = children[0]["id"]

    r = await client.get(f"/parent/children/{child_id}/overview", headers=auth(ptok))
    assert r.status_code == 200, r.text
    ov = r.json()
    assert "progress_pct" in ov and "mastery_pct" in ov
    assert "status_counts" in ov and "weak_topics" in ov
    # اصل حریم خصوصی: بدون رتبه/مقایسه با دیگران
    assert "rank" not in ov
    assert "peers" not in ov
    assert ov["note_fa"]


@pytest.mark.anyio
async def test_parent_cannot_see_other_students(client, seeded):
    ptok = await login(client, "parent1")
    # student2 هیچ والد متصلی ندارد → هر شناسه‌ای که پیوند نداشته باشد 403
    r = await client.get("/parent/children/6/overview", headers=auth(ptok))
    assert r.status_code == 403

    # دانش‌آموز هم نمی‌تواند پنل والدین را بخواند (فرزند متصل نیست)
    stok = await login(client, "student1")
    r = await client.get("/parent/children/5/overview", headers=auth(stok))
    assert r.status_code == 403


# ------------------------- بردها -------------------------


@pytest.mark.anyio
async def test_school_board_pseudonym_and_suppression(client, seeded):
    stok = await login(client, "student1")
    r = await client.get("/boards/school/1", headers=auth(stok))
    assert r.status_code == 200, r.text
    board = r.json()
    assert board["min_group"] == 10
    assert board["note_fa"]

    # نام مستعار: هیچ نام واقعی کلاس/معلم نباید برگردد
    for row in board["rows"]:
        assert row["key"].startswith("ک-")
        assert "name" not in row and "class_name" not in row

    # مدرسه ۱ فقط ۵ دانش‌آموز دارد → همه ردیف‌ها suppressed و بدون عدد
    assert len(board["rows"]) == 2
    for row in board["rows"]:
        assert row["suppressed"] is True
        assert row["avg_mastery"] is None
        assert row["weak_count"] is None

    # جمع کل مدرسه هم زیر حد نصاب → سرکوب
    assert board["total"]["suppressed"] is True
    assert board["total"]["avg_mastery"] is None


@pytest.mark.anyio
async def test_province_board_school2_visible_school1_suppressed(client, seeded):
    stok = await login(client, "student1")
    r = await client.get("/boards/province/1", headers=auth(stok))
    assert r.status_code == 200, r.text
    board = r.json()
    assert len(board["rows"]) == 2  # مدرسه ۱ و ۲

    rows = {row["key"]: row for row in board["rows"]}
    # مدرسه دوم ۱۰ دانش‌آموز با شواهد کافی → عدد نمایش داده می‌شود
    visible = [row for row in board["rows"] if not row["suppressed"]]
    suppressed = [row for row in board["rows"] if row["suppressed"]]
    assert len(visible) == 1 and len(suppressed) == 1
    # مدرسه سرکوب‌شده، مدرسه ۱ (۵ دانش‌آموز) است
    assert rows["م-۱"]["suppressed"] is True
    assert rows["م-۲"]["suppressed"] is False
    assert rows["م-۲"]["avg_mastery"] is not None


@pytest.mark.anyio
async def test_national_board_min_group(client, seeded):
    stok = await login(client, "student1")
    r = await client.get("/boards/national", headers=auth(stok))
    assert r.status_code == 200, r.text
    board = r.json()
    assert len(board["rows"]) == 1  # فقط استان تهران
    row = board["rows"][0]
    assert row["key"].startswith("استان-")
    # ۱۵ دانش‌آموز (۵ + ۱۰) با شواهد کافی → بالای حداقل جمعیت ۱۰
    assert row["suppressed"] is False
    assert row["avg_mastery"] is not None
