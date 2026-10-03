"""برد «جایگاه من» (سند دانش‌آموز §8.1–8.4): سه نما، صدک، حریم خصوصی، نشان‌ها."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_daneshyar.db")

from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.core.db import AsyncSessionLocal, Base, engine
from app.core.passwords import hash_password
from app.models.assessment import Exam, ExamAttempt
from app.models.org import StudentProfile, User
from app.services.boards import growth_gain, percentile, student_alias
from scripts.seed import seed


@pytest.fixture()
async def client():
    async with engine.begin() as conn:
        from app.core.db import Base

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


async def _uid(session, username: str) -> int:
    row = (await session.execute(select(User).where(User.username == username))).scalars().first()
    assert row is not None, username
    return row.id


async def make_peers(session, n: int, school_id: int = 1, class_id: int = 1) -> list[int]:
    """n دانش‌آموز جدید در مدرسهٔ ۱ — برای آزمون پنجرهٔ ده‌نفرهٔ برد."""
    ids: list[int] = []
    for i in range(n):
        u = User(
            username=f"boardpeer{i}",
            password_hash=hash_password("pass123"),
            full_name=f"دانش‌آموز آزمایشی {i}",
            system_role="student",
        )
        session.add(u)
        await session.flush()
        session.add(
            StudentProfile(user_id=u.id, grade="grade_10", school_id=school_id, class_id=class_id)
        )
        ids.append(u.id)
    await session.commit()
    return ids


async def add_official(session, pairs: list[tuple[int, float]], exam_type: str = "period_exam") -> None:
    """pairs: [(student_user_id, percent), ...] به‌عنوان آزمون رسمی تصحیح‌شده."""
    exam = Exam(
        title_fa="آزمون دوره‌ای آزمایشی",
        exam_type=exam_type,
        grade="10",
        subject="math",
        status="graded",
    )
    session.add(exam)
    await session.flush()
    for sid, pct in pairs:
        session.add(
            ExamAttempt(
                exam_id=exam.id,
                student_user_id=sid,
                status="graded",
                raw_score=pct,
                percent=pct,
                submitted_at=datetime.utcnow(),
            )
        )
    await session.commit()


# ------------------------- فرمول‌ها (§8.3) -------------------------


def test_percentile_formula():
    # درصد کسانی که نمره‌شان پایین‌تر از x است (+ نیمی از برابرها)
    assert percentile([], 70) is None
    assert percentile([50, 60, 70, 80], 70) == 62.5
    assert percentile([50, 60, 70, 80], 90) == 100.0
    assert percentile([50, 60, 70, 80], 40) == 0.0


def test_growth_gain_hides_when_prev_above_95():
    assert growth_gain(85, 60) == 0.625
    assert growth_gain(96, 97) is None  # prev ≥ 95 → رشد پنهان
    assert growth_gain(70, None) is None
    assert growth_gain(None, 60) is None


def test_alias_is_persian_and_stable():
    a1, a2 = student_alias(5), student_alias(5)
    assert a1 == a2
    assert a1 != student_alias(6)
    # نام مستعار نباید نام واقعی دانش‌آموز باشد
    assert "دانش‌آموز" not in a1


# ------------------------- جایگاه من (§8.1) -------------------------


@pytest.mark.anyio
async def test_my_board_three_lenses_and_privacy(client, seeded):
    stok = await login(client, "student1")
    async with AsyncSessionLocal() as session:
        me = await _uid(session, "student1")
        peers = [await _uid(session, f"student{i}") for i in range(2, 6)]
        # دو آزمون رسمی برای خودم → رشد محاسبه می‌شود
        await add_official(session, [(me, 60.0), (me, 85.0)])
        # آزمون رسمی هم‌کلاسی‌ها
        await add_official(session, [(peers[0], 90.0), (peers[1], 70.0), (peers[2], 50.0), (peers[3], 40.0)])
        # آزمون غیررسمی (خودسنجی/تشخیصی) نباید وارد برد شود (§8.2)
        await add_official(session, [(me, 99.0)], exam_type="diagnostic")

    r = await client.get("/boards/me", headers=auth(stok))
    assert r.status_code == 200, r.text
    board = r.json()
    assert board["available"] is True
    assert board["min_group"] == 10

    # سه نما (§8.1)
    keys = [lens["key"] for lens in board["lenses"]]
    assert keys == ["performance", "growth", "mastery"]

    me_block = board["me"]
    # فقط آزمون رسمی: نمره ۸۵ (نه ۹۹ خودسنجی)
    assert me_block["performance"] == 85.0
    assert me_block["prev_performance"] == 60.0
    assert me_block["growth_pct"] == 62.5
    assert me_block["official_count"] == 2

    # رتبهٔ عملکرد: ۹۰ > ۸۵ > ۷۰ > ۵۰ > ۴۰ → جایگاه من دوم
    perf = next(l for l in board["lenses"] if l["key"] == "performance")
    assert perf["my_rank"] == 2
    assert perf["count"] == 5
    assert perf["rows"][0]["alias"] != perf["rows"][1]["alias"]
    assert perf["rows"][1]["is_me"] is True

    # رشد حداقل ۳ آزمون رسمی می‌خواهد (§8.3) → برای من واجد شرایط نیست
    growth = next(l for l in board["lenses"] if l["key"] == "growth")
    assert growth["eligible"] is False
    assert growth["my_rank"] is None

    # حریم خصوصی: فقط نام مستعار، بدون نام واقعی (§8.2)
    real_names = ["دانش‌آموز", "احمدی", "رضایی"]
    for lens in board["lenses"]:
        for row in lens["rows"]:
            assert row["alias"] and not any(n in row["alias"] for n in real_names)

    # زیر حداقل جمعیت → آمار گروهی حذف می‌شود (§8.2)
    assert board["averages"]["school"]["suppressed"] is True
    assert board["averages"]["school"]["value"] is None
    assert board["averages"]["province"]["suppressed"] is True
    assert board["averages"]["national_percentile"]["suppressed"] is True
    assert board["notes_fa"]


@pytest.mark.anyio
async def test_my_board_growth_requires_three_official_exams(client, seeded):
    stok = await login(client, "student1")
    async with AsyncSessionLocal() as session:
        me = await _uid(session, "student1")
        await add_official(session, [(me, 55.0), (me, 65.0), (me, 80.0)])

    r = await client.get("/boards/me", headers=auth(stok))
    assert r.status_code == 200, r.text
    growth = next(l for l in r.json()["lenses"] if l["key"] == "growth")
    assert growth["eligible"] is True
    assert growth["my_rank"] == 1
    # g = (80 − 65) / (100 − 65) = 0.4286 → ۴۲٫۹٪
    assert r.json()["me"]["growth_pct"] == 42.9


@pytest.mark.anyio
async def test_board_visible_window_is_top10_plus_self_neighbours(client, seeded):
    stok = await login(client, "student1")
    async with AsyncSessionLocal() as session:
        me = await _uid(session, "student1")
        peers = await make_peers(session, 14)
        # ۱۲ نفر بالاتر از من، من در جایگاه ۱۳، و ۲ نفر پایین‌تر
        pairs: list[tuple[int, float]] = [(me, 70.0)]
        pairs += [(peers[i], float(99 - i)) for i in range(12)]
        pairs += [(peers[12], 69.0), (peers[13], 68.0)]
        await add_official(session, pairs)

    r = await client.get("/boards/me", headers=auth(stok))
    assert r.status_code == 200, r.text
    perf = next(l for l in r.json()["lenses"] if l["key"] == "performance")
    ranks = [row["rank"] for row in perf["rows"]]
    # ده نفر برتر نمایش داده می‌شوند
    assert ranks[:10] == list(range(1, 11))
    # جایگاه من با یک نفر بالا و پایین
    me_row = next(row for row in perf["rows"] if row["is_me"])
    assert me_row["rank"] == 13
    assert 12 in ranks and 13 in ranks and 14 in ranks
    # پایینِ جدول حذف می‌شود تا رتبهٔ پایین باعث شرمندگی نشود (§8.2)
    assert 11 not in ranks and 15 not in ranks
    assert perf["count"] == 15


@pytest.mark.anyio
async def test_badges_follow_growth_and_behaviour_not_only_score(client, seeded):
    stok = await login(client, "student1")
    async with AsyncSessionLocal() as session:
        me = await _uid(session, "student1")
        await add_official(session, [(me, 60.0), (me, 85.0)])

    r = await client.get("/boards/me/badges", headers=auth(stok))
    assert r.status_code == 200, r.text
    body = r.json()
    titles = [b["title_fa"] for b in body["badges"]]
    assert "پیشرفت ویژه" in titles
    assert "ماندگاری برتر" in titles
    assert "بدون خطای تکراری" in titles
    assert "مشارکت در برنامه" in titles

    progress_badge = next(b for b in body["badges"] if b["key"] == "special_progress")
    assert progress_badge["earned"] is True  # g = 0.625 ≥ 0.4
    assert body["earned_count"] >= 1
    assert body["note_fa"]


@pytest.mark.anyio
async def test_non_student_gets_graceful_message(client, seeded):
    ttok = await login(client, "teacher1")
    r = await client.get("/boards/me", headers=auth(ttok))
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["note_fa"]
