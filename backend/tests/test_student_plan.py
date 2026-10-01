"""تقویم/برنامه دوره‌ای + تاریخچه تحلیلی آزمون (دانش‌آموز) — student spec §4, §7, §13."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_studentplan.db")

from datetime import date, datetime, timedelta

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


async def take_exam(client, token, exam_id, selection="A"):
    """شروع + ثبت آزمون: selection یک گزینهٔ ثابت است یا 'CORRECT' / 'MIXED'.

    MIXED: سؤال‌های زوج درست، فرد غلط — برای مرور ترکیبی."""
    r = await client.post(f"/student/exams/{exam_id}/start", headers=auth(token))
    assert r.status_code == 200, r.text
    items = r.json()["items"]

    correct = {}
    if selection in ("CORRECT", "MIXED"):
        from app.models.assessment import ExamItem, QuestionItem
        from sqlalchemy import select as sa_select

        async with AsyncSessionLocal() as session:
            eis = (
                await session.execute(sa_select(ExamItem).where(ExamItem.exam_id == exam_id))
            ).scalars().all()
            for ei in eis:
                q = await session.get(QuestionItem, ei.item_id)
                correct[ei.id] = q.correct_option

    answers = []
    for idx, it in enumerate(items):
        cid = it["exam_item_id"]
        if selection == "MIXED":
            corr = correct.get(cid, "A")
            sel = corr if idx % 2 == 0 else next(k for k in it["options"] if k != corr)
        elif selection == "CORRECT":
            sel = correct.get(cid, "A")
        else:
            sel = selection
        answers.append(
            {
                "exam_item_id": cid,
                "selected": sel,
                "confidence": 3,
                "time_spent_ms": 4000,
            }
        )
    r = await client.post(
        f"/student/exams/{exam_id}/submit", headers=auth(token), json={"answers": answers}
    )
    assert r.status_code == 200, r.text
    return r.json(), [it["exam_item_id"] for it in items]


def all_items(days):
    return [it for d in days for it in d["items"]]


# ------------------------------------------------------------------ تقویم


@pytest.mark.anyio
async def test_calendar_default_range_and_kinds(client, seeded):
    stok = await login(client, "student1")
    r = await client.get("/student/calendar", headers=auth(stok))
    assert r.status_code == 200, r.text
    body = r.json()

    today = date.today()
    assert body["today"] == today.isoformat()
    assert body["from"] == today.isoformat()
    assert len(body["days"]) == 7
    assert body["days"][0]["is_today"] is True
    assert body["days"][0]["weekday"] in [
        "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه",
    ]
    assert body["days"][1]["is_today"] is False

    kinds = {it["kind"] for it in all_items(body["days"])}
    # دورهٔ ۱۴ روزهٔ جاری + آزمون دوره ۱ + مأموریت روزانه
    assert "period" in kinds
    assert "exam" in kinds
    assert "mission" in kinds

    # مأموریت امروز در سطح بالا هم هست
    assert body["mission"] is not None
    assert "مأموریت" in body["mission"]["title"]
    assert isinstance(body["mission"]["tasks"], list)

    # هایلایت «امروز» روی آیتم‌های امروز
    today_items = body["days"][0]["items"]
    assert any(it.get("highlight") == "today" for it in today_items)

    # آزمون دوره ۱ باز است (از دیروز تا ۶ روز بعد)
    exam_items = [it for it in all_items(body["days"]) if it["kind"] == "exam"]
    assert exam_items
    assert all("آزمون دوره ۱" in it["title"] for it in exam_items)

    # خلاصهٔ نما فارسی/عددی
    assert body["summary"]["free_today"] == (date.today().weekday() in (3, 4))
    assert body["summary"]["suggested_minutes"] in (60, 150)


@pytest.mark.anyio
async def test_calendar_range_validation(client, seeded):
    stok = await login(client, "student1")
    today = date.today()

    # بازهٔ سفارشی
    r = await client.get(
        f"/student/calendar?from={today.isoformat()}&to={(today + timedelta(days=2)).isoformat()}",
        headers=auth(stok),
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["days"]) == 3

    # تاریخ خراب ⇒ 400
    r = await client.get("/student/calendar?from=12-34-56", headers=auth(stok))
    assert r.status_code == 400
    assert "نامعتبر" in r.json()["detail"]

    # پایان قبل از شروع ⇒ 400
    r = await client.get(
        f"/student/calendar?from={(today + timedelta(days=5)).isoformat()}&to={today.isoformat()}",
        headers=auth(stok),
    )
    assert r.status_code == 400

    # بازهٔ خیلی بلند ⇒ 400
    r = await client.get(
        f"/student/calendar?from={today.isoformat()}&to={(today + timedelta(days=120)).isoformat()}",
        headers=auth(stok),
    )
    assert r.status_code == 400


@pytest.mark.anyio
async def test_calendar_tasks_overdue_and_mission(client, seeded):
    """کار برنامه در روز خودش گروه‌بندی می‌شود؛ کار جا‌مانده روی امروز با هایلایت overdue."""
    from app.models.slm import PlanTask

    stok = await login(client, "student1")
    today = date.today()

    async with AsyncSessionLocal() as session:
        session.add(
            PlanTask(
                student_user_id=(await _student_id(session, "student1")),
                topic_id=None,
                task_type="spaced_review",
                payload={},
                for_date=today - timedelta(days=3),  # جا‌مانده
                priority=3.0,
                status="pending",
            )
        )
        session.add(
            PlanTask(
                student_user_id=(await _student_id(session, "student1")),
                topic_id=None,
                task_type="lesson",
                payload={},
                for_date=today,
                priority=2.0,
                status="pending",
            )
        )
        await session.commit()

    r = await client.get("/student/calendar", headers=auth(stok))
    assert r.status_code == 200, r.text
    body = r.json()

    tasks = [it for it in all_items(body["days"]) if it["kind"] == "task"]
    assert len(tasks) == 2
    overdue = [t for t in tasks if t["highlight"] == "overdue"]
    assert len(overdue) == 1
    assert "جا‌مانده" in overdue[0]["detail"]
    assert body["summary"]["overdue"] >= 1
    assert body["summary"]["pending_tasks"] >= 1

    # مأموریت امروز کارها را با اولویت می‌آورد
    mission = body["mission"]
    assert mission["status"] == "pending"
    assert len(mission["tasks"]) == 2
    assert mission["tasks"][0]["priority"] >= mission["tasks"][1]["priority"]

    # انجام کار ⇒ مأموریت امروز done می‌شود
    task_id = mission["tasks"][0]["id"]
    r = await client.post(
        f"/student/tasks/{task_id}/complete", headers=auth(stok), json={"minicheck_passed": False}
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"/student/tasks/{mission['tasks'][1]['id']}/complete",
        headers=auth(stok),
        json={"minicheck_passed": True},
    )
    assert r.status_code == 200, r.text

    r = await client.get("/student/calendar", headers=auth(stok))
    mission = r.json()["mission"]
    assert mission["status"] == "done"


async def _student_id(session, username):
    from app.models.org import User
    from sqlalchemy import select as sa_select

    return (
        (await session.execute(sa_select(User.id).where(User.username == username))).scalar_one()
    )


@pytest.mark.anyio
async def test_calendar_retest_cycle_lifecycle(client, seeded):
    """خطای باز ⇒ آیتم چرخه ترمیم (needs_build)؛ پس از ساخت بازآزمون، خودِ آزمون در تقویم."""
    stok = await login(client, "student1")

    # بدون خطا: چرخه‌ای در کار نیست
    r = await client.get("/student/calendar", headers=auth(stok))
    kinds = {it["kind"] for it in all_items(r.json()["days"])}
    assert "retest" not in kinds

    await take_exam(client, stok, 1, selection="A")

    r = await client.get("/student/calendar", headers=auth(stok))
    retest_items = [it for it in all_items(r.json()["days"]) if it["kind"] == "retest"]
    assert retest_items
    assert retest_items[0]["status"] == "needs_build"
    assert "بازآزمون" in retest_items[0]["detail"]

    # ساخت بازآزمون ⇒ آزمونِ هدف‌مند با kind=retest در تقویم می‌آید
    r = await client.post("/student/retest/build", headers=auth(stok))
    assert r.status_code == 200, r.text
    exam_id = r.json()["exam_id"]

    r = await client.get("/student/calendar", headers=auth(stok))
    days = r.json()["days"]
    retest_items = [it for it in all_items(days) if it["kind"] == "retest"]
    assert retest_items
    # آیتم تکراری نسازد: یا خودِ آزمون است یا چرخه — نه هر دو در یک روز
    for d in days:
        day_cycle = [i for i in d["items"] if i["kind"] == "retest"]
        assert len(day_cycle) <= 1
    assert any(i["ref"]["type"] == "exam" and i["ref"]["id"] == exam_id for i in retest_items)


@pytest.mark.anyio
async def test_calendar_hides_other_students_targeted_retest(client, seeded):
    """بازآزمون ترمیمیِ دانش‌آموز دیگر (scope=student) نباید در تقویم دیگری دیده شود."""
    stok1 = await login(client, "student1")
    await take_exam(client, stok1, 1, selection="A")
    r = await client.post("/student/retest/build", headers=auth(stok1))
    assert r.status_code == 200, r.text
    retest_exam_id = r.json()["exam_id"]

    # خود دانش‌آموز می‌بیند
    r = await client.get("/student/calendar", headers=auth(stok1))
    seen_own = [
        it for it in all_items(r.json()["days"])
        if it["ref"].get("type") == "exam" and it["ref"].get("id") == retest_exam_id
    ]
    assert seen_own

    # دانش‌آموز دیگر نمی‌بیند
    stok3 = await login(client, "student3")
    r = await client.get("/student/calendar", headers=auth(stok3))
    seen_other = [
        it for it in all_items(r.json()["days"])
        if it["ref"].get("type") == "exam" and it["ref"].get("id") == retest_exam_id
    ]
    assert not seen_other
    # و تاریخچهٔ دانش‌آموز دیگر خالی است
    r = await client.get("/student/exam-history", headers=auth(stok3))
    assert r.json()["attempts"] == []


# ------------------------------------------------------- تاریخچه تحلیلی آزمون


@pytest.mark.anyio
async def test_exam_history_counts_and_delta(client, seeded):
    stok = await login(client, "student1")

    # بدون تلاش: خالی
    r = await client.get("/student/exam-history", headers=auth(stok))
    assert r.status_code == 200, r.text
    assert r.json()["attempts"] == []
    assert r.json()["summary"]["attempts"] == 0

    # تلاش اول: همه A (بعضی غلط)
    res1, item_ids = await take_exam(client, stok, 1, selection="A")
    r = await client.get("/student/exam-history", headers=auth(stok))
    data = r.json()
    assert data["summary"]["attempts"] == 1
    a1 = data["attempts"][0]
    assert a1["percent"] == res1["percent"]
    assert a1["delta_percent"] is None  # تلاش اول همان آزمون
    assert a1["correct"] + a1["wrong"] + a1["unanswered"] == 4
    assert a1["correct"] + a1["wrong"] == 4  # همه پاسخ داده شده
    assert a1["time_spent_ms"] == 4 * 4000
    assert a1["errors_recorded"] >= 1
    assert a1["exam_title"].startswith("آزمون دوره ۱")
    assert a1["negative_marking"]["applied"] is False  # k=0 در آزمون seed
    assert a1["topics"] and all(t["status"] for t in a1["topics"])
    assert len(data["trend"]) == 1

    # تلاش دوم با پاسخ‌های درست ⇒ تغییر نسبت به تلاش قبلی
    res2, _ = await take_exam(client, stok, 1, selection="CORRECT")
    r = await client.get("/student/exam-history", headers=auth(stok))
    data = r.json()
    assert data["summary"]["attempts"] == 2
    a2 = data["attempts"][1]
    assert a2["delta_percent"] == round(res2["percent"] - res1["percent"], 2)
    assert a2["delta_percent"] > 0
    assert data["trend"][-1]["percent"] == res2["percent"]
    assert data["summary"]["avg_percent"] is not None
    assert data["summary"]["best_percent"] >= a2["percent"] - 0.01


@pytest.mark.anyio
async def test_exam_history_privacy(client, seeded):
    """فقط تلاش‌های خود دانش‌آموز؛ دیگری نه فهرست را می‌بیند نه مرور تک‌تلاش را."""
    stok1 = await login(client, "student1")
    await take_exam(client, stok1, 1, selection="A")

    r = await client.get("/student/exam-history", headers=auth(stok1))
    attempt_id = r.json()["attempts"][0]["id"]

    stok2 = await login(client, "student2")
    r = await client.get("/student/exam-history", headers=auth(stok2))
    assert r.status_code == 200
    assert r.json()["attempts"] == []

    # مرور تک‌تلاش دیگری ⇒ 404 (بدون افشای وجود)
    r = await client.get(f"/student/exam-history/{attempt_id}", headers=auth(stok2))
    assert r.status_code == 404

    # ناموجود ⇒ 404
    r = await client.get("/student/exam-history/999999", headers=auth(stok1))
    assert r.status_code == 404


@pytest.mark.anyio
async def test_attempt_detail_drilldown(client, seeded):
    stok = await login(client, "student1")
    res, item_ids = await take_exam(client, stok, 1, selection="MIXED")

    r = await client.get("/student/exam-history", headers=auth(stok))
    attempt_id = r.json()["attempts"][0]["id"]

    r = await client.get(f"/student/exam-history/{attempt_id}", headers=auth(stok))
    assert r.status_code == 200, r.text
    detail = r.json()

    # مرور سؤال‌به‌سؤال
    qs = detail["questions"]
    assert len(qs) == 4
    assert {q["exam_item_id"] for q in qs} == set(item_ids)
    causes = {"conceptual", "prerequisite", "calculation", "careless", "time_management", "guess"}
    wrong = 0
    for q in qs:
        assert q["body"]
        assert q["options"] and q["correct_option"] in q["options"]
        assert q["selected"] is not None
        if not q["is_correct"]:
            wrong += 1
            assert q["error_cause"] in causes  # یکی از ۶ علت
            assert q["error_record"] is not None
            assert q["selected"] != q["correct_option"]
        else:
            assert q["error_cause"] is None
            assert q["error_record"] is None
        assert q["topic_title"]
    assert wrong == 2  # سؤال‌های فرد (MIXED)

    # علت‌های خلاصه‌شده فقط از همان ۶ علت
    assert detail["causes"]
    assert set(detail["causes"]) <= causes

    # دلتای تسط مبحث‌ها قبل/بعد
    tb = detail["topics_before_after"]
    assert tb
    for row in tb:
        assert row["before_e"] >= 0 and row["after_e"] >= 0
        assert row["delta_e"] == round(row["after_e"] - row["before_e"], 2)
        assert row["status_before"] in {"mastered", "consolidating", "weak", "critical", "unknown"}
        assert row["status_after"] in {"mastered", "consolidating", "weak", "critical", "unknown"}
    # پس از پاسخ درستِ بعضی سؤالات، تسط مبحث‌ها بالا رفته است
    assert any(row["delta_e"] > 0 for row in tb)

    assert detail["attempt"]["id"] == attempt_id
    assert detail["attempt"]["percent"] == res["percent"]
    assert detail["attempt"]["errors_recorded"] == wrong


@pytest.mark.anyio
async def test_attempt_detail_marks_unanswered(client, seeded):
    """تلاش ناقص: سؤال‌های بی‌پاسخ با answered=False گزارش می‌شوند."""
    stok = await login(client, "student1")
    r = await client.post("/student/exams/1/start", headers=auth(stok))
    items = r.json()["items"]
    # فقط اولین سؤال را جواب بده
    answers = [
        {"exam_item_id": items[0]["exam_item_id"], "selected": "B", "confidence": 4, "time_spent_ms": 2000}
    ]
    r = await client.post("/student/exams/1/submit", headers=auth(stok), json={"answers": answers})
    assert r.status_code == 200, r.text

    r = await client.get("/student/exam-history", headers=auth(stok))
    a = r.json()["attempts"][0]
    assert a["unanswered"] == 3

    r = await client.get(f"/student/exam-history/{a['id']}", headers=auth(stok))
    qs = r.json()["questions"]
    assert len(qs) == 4
    assert sum(1 for q in qs if not q["answered"]) == 3
    assert sum(1 for q in qs if q["is_correct"]) == 1
