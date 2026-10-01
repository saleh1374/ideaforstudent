"""سازندهٔ آزمون معلم + تحلیل پس از آزمون (سند پنل معلم §8 و §10).

پوشش: جریان کامل «ساخت ← هدف/بلوپرینت ← مونتاژ سؤال ← ویرایش ← انتشار ←
شرکت دانش‌آموز ← تحلیل آیتم»، پاسخ نرمِ کسری بانک، گاردهای مالکیت/RBAC،
و تشخیص خودکار «سؤال بد» (قدرت تفکیک زیر ۰٫۱۵ و اختلاف دشواری بیش از ۰٫۳).
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_exambuilder.db")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.core.db import AsyncSessionLocal, Base, engine
from app.models.assessment import Exam, ExamAttempt
from app.models.exam_builder import ItemAnalysis
from app.models.org import User
from app.services.assessment import submit_attempt
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


async def login(c, username):
    r = await c.post("/auth/login", json={"username": username, "password": "pass123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


async def make_exam(c, h, **overrides):
    payload = {
        "title_fa": "آزمون تشخیصی تعداد زیرمجموعه‌ها",
        "class_id": 1,
        "exam_type": "diagnostic",
        "mode": "standard",
        "negative_marking_k": 0.25,
        "opens_at": "2030-01-05T08:00:00",
        "closes_at": "2030-01-07T10:00:00",
    }
    payload.update(overrides)
    r = await c.post("/teacher/exams", headers=h, json=payload)
    assert r.status_code == 200, r.text
    return r.json()["exam"]


GOAL = "می‌خواهم بفهمم چرا بچه‌ها در تعداد زیرمجموعه‌ها مشکل دارند"


async def build_exam(c, h) -> tuple[dict, list[dict]]:
    """ساخت آزمون + بلوپرینت از هدف + مونتاژ سؤال‌ها از بانک."""
    exam = await make_exam(c, h)
    r = await c.post(f"/teacher/exams/{exam['id']}/blueprint", headers=h, json={"goal": GOAL})
    assert r.status_code == 200, r.text
    r = await c.post(f"/teacher/exams/{exam['id']}/items", headers=h, json={"source": "blueprint"})
    assert r.status_code == 200, r.text
    r = await c.get(f"/teacher/exams/{exam['id']}", headers=h)
    assert r.status_code == 200, r.text
    detail = r.json()
    return detail, detail["items"]


# --------------------------- جریان کامل سازنده ---------------------------


@pytest.mark.anyio
async def test_exam_builder_end_to_end(client, seeded):
    h = auth(await login(client, "teacher1"))

    # فهرست خالی
    r = await client.get("/teacher/exams", headers=h)
    assert r.status_code == 200 and r.json()["exams"] == []

    # ---- ساخت پیش‌نویس ----
    exam = await make_exam(client, h)
    assert exam["status"] == "draft"
    assert exam["type_fa"] == "آزمون تشخیصی"
    assert exam["class_name"] == "۱۰۱"
    assert exam["negative_marking_k"] == 0.25
    eid = exam["id"]

    # اعتبارسنجی‌ها
    r = await client.post(
        "/teacher/exams", headers=h,
        json={"title_fa": "x", "class_id": 1, "exam_type": "nope"},
    )
    assert r.status_code == 400
    r = await client.post(
        "/teacher/exams", headers=h,
        json={"title_fa": "x", "class_id": 1, "negative_marking_k": 2.0},
    )
    assert r.status_code == 400

    # ---- بلوپرینت از هدف (§8.2) ----
    r = await client.post(f"/teacher/exams/{eid}/blueprint", headers=h, json={"goal": GOAL})
    assert r.status_code == 200, r.text
    bp = r.json()
    assert bp["ok"] is True
    assert bp["target_topic"]["title"] == "تعداد زیرمجموعه‌ها"
    rows = bp["rows"]
    kinds = [row["item_kind"] for row in rows]
    assert kinds == ["concept_base", "prerequisite_skill", "direct_application", "reasoning"]
    assert sum(row["count"] for row in rows) == 8  # آزمون تشخیصی ۸سؤالی (§8.5)
    prereq = rows[1]
    assert prereq["topic_title"].startswith("مجموعه")  # پیش‌نیازِ مبحث هدف
    assert "پیش‌نیاز" in prereq["diagnostic_purpose"]
    assert all(row["topic_title"] and row["diagnostic_purpose"] for row in rows)
    assert "بلوپرینت" in bp["summary_fa"]

    # ---- مونتاژ سؤال از بانک: پاسخ نرم هنگام کسری ----
    r = await client.post(f"/teacher/exams/{eid}/items", headers=h, json={"source": "blueprint"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["attached"] == 4  # بانک: ۲ سؤال مبحث هدف + ۲ سؤال پیش‌نیاز
    assert res["ok"] is False and res["reason"]  # کسری بانک → {ok:false, reason}

    # تکرار → بدون سؤال تکراری
    r = await client.post(f"/teacher/exams/{eid}/items", headers=h, json={"source": "blueprint"})
    assert r.status_code == 200 and r.json()["attached"] == 0

    # ---- جزئیات ----
    r = await client.get(f"/teacher/exams/{eid}", headers=h)
    assert r.status_code == 200
    detail = r.json()
    items = detail["items"]
    assert len(items) == 4
    assert detail["exam"]["has_blueprint"] is True
    assert detail["goal"] == GOAL
    assert all(it["correct_option"] in "ABCD" for it in items)
    assert len(detail["blueprint"]) == 4

    # ---- ویرایش سؤال: امتیاز + ترتیب ----
    last = items[-1]
    r = await client.patch(
        f"/teacher/exams/{eid}/items/{last['exam_item_id']}",
        headers=h,
        json={"points": 2.5, "order": 1},
    )
    assert r.status_code == 200, r.text
    r = await client.get(f"/teacher/exams/{eid}", headers=h)
    items = r.json()["items"]
    assert items[0]["exam_item_id"] == last["exam_item_id"]
    assert items[0]["points"] == 2.5
    assert sorted(it["order"] for it in items) == [1, 2, 3, 4]  # قید یکتایی حفظ شد

    # ---- سؤال دستی با علت هر گزینهٔ غلط (§5.3) ----
    r = await client.post(
        f"/teacher/exams/{eid}/items",
        headers=h,
        json={
            "source": "custom",
            "body": "اگر |A|=5 باشد تعداد زیرمجموعه‌های A چند است؟",
            "options": {"A": "۱۶", "B": "۲۵", "C": "۳۲", "D": "۶۴"},
            "correct_option": "C",
            "distractor_causes": {"A": "calculation", "B": "conceptual"},
            "points": 2.0,
            "difficulty": "medium",
            "misconception": "اشتباه ۲^n با n",
        },
    )
    assert r.status_code == 200, r.text

    # علت نامعتبر → 400
    r = await client.post(
        f"/teacher/exams/{eid}/items",
        headers=h,
        json={
            "source": "custom",
            "body": "سؤال خراب",
            "options": {"A": "۱", "B": "۲", "C": "۳", "D": "۴"},
            "correct_option": "A",
            "distractor_causes": {"B": "not_a_cause"},
        },
    )
    assert r.status_code == 400

    # ---- ویرایش بلوپرینت توسط معلم ----
    edited = [
        {k: row[k] for k in ("topic_id", "count", "item_kind", "diagnostic_purpose")}
        for row in rows
    ]
    edited[0]["count"] = 5
    r = await client.patch(f"/teacher/exams/{eid}", headers=h, json={"blueprint": edited})
    assert r.status_code == 200, r.text
    r = await client.get(f"/teacher/exams/{eid}", headers=h)
    assert r.json()["blueprint"][0]["count"] == 5

    edited[0]["count"] = 0
    r = await client.patch(f"/teacher/exams/{eid}", headers=h, json={"blueprint": edited})
    assert r.status_code == 400

    # بازخوانی نهایی سؤال‌ها (۵ سؤال: ۴ بانکی + ۱ دستی)
    r = await client.get(f"/teacher/exams/{eid}", headers=h)
    items = r.json()["items"]
    assert len(items) == 5

    # ---- انتشار (§8.3) ----
    r = await client.post(f"/teacher/exams/{eid}/publish", headers=h)
    assert r.status_code == 200, r.text
    pub = r.json()
    assert pub["exam"]["status"] == "published"
    assert pub["exam"]["scope"] == "class"  # استاندارد → ورود به برد
    assert "منتشر" in pub["note_fa"]

    r = await client.post(f"/teacher/exams/{eid}/publish", headers=h)
    assert r.status_code == 409
    r = await client.patch(f"/teacher/exams/{eid}", headers=h, json={"title_fa": "جدید"})
    assert r.status_code == 409
    r = await client.delete(f"/teacher/exams/{eid}/items/{items[0]['exam_item_id']}", headers=h)
    assert r.status_code == 409

    # ---- دانش‌آموز شرکت می‌کند ----
    sh = auth(await login(client, "student1"))
    r = await client.get("/student/exams", headers=sh)
    assert r.status_code == 200
    assert any(e["id"] == eid for e in r.json()["exams"])
    r = await client.post(f"/student/exams/{eid}/start", headers=sh)
    assert r.status_code == 200, r.text
    start = r.json()
    assert len(start["items"]) == 5
    correct_of = {it["exam_item_id"]: it["correct_option"] for it in items}
    answers = [
        {"exam_item_id": it["exam_item_id"], "selected": correct_of[it["exam_item_id"]],
         "confidence": 4, "time_spent_ms": 30000}
        for it in start["items"]
    ]
    r = await client.post(f"/student/exams/{eid}/submit", headers=sh, json={"answers": answers})
    assert r.status_code == 200, r.text
    assert r.json()["percent"] == 100.0

    # ---- تحلیل پس از آزمون (§10.1) ----
    r = await client.get(f"/teacher/exams/{eid}/item-analysis", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["attempts"] == 1
    assert len(data["items"]) == 5
    assert data["thresholds"]["discrimination_min"] == 0.15
    assert data["note_fa"] and "قدرت تفکیک" in data["note_fa"]  # زیر ۴ تلاش
    for row in data["items"]:
        assert row["responses_count"] == 1
        assert row["correct_pct"] == 100.0
        assert row["discrimination"] is None  # تلاش کافی نیست
        assert row["avg_time_ms"] == 30000
        assert row["comment_fa"]
    # سؤال‌های متوسط (prior=0.6) با دشواری تجربی ۱٫۰ ⇒ اختلاف ۰٫۴ > ۰٫۳ ⇒ بازبینی
    flagged = [row for row in data["items"] if row["needs_review"]]
    assert len(flagged) == 2
    assert all("اختلاف دشواری" in row["review_reasons"][0] for row in flagged)
    assert all("⚠" in row["comment_fa"] for row in flagged)
    healthy = [row for row in data["items"] if not row["needs_review"]]
    assert len(healthy) == 3
    assert all("⚠" not in row["comment_fa"] for row in healthy)

    # فهرست، شمارش تلاش‌ها را نشان می‌دهد
    r = await client.get("/teacher/exams", headers=h)
    row = next(e for e in r.json()["exams"] if e["id"] == eid)
    assert row["attempts_count"] == 1 and row["item_count"] == 5


# ------------------------ تشخیص خودکار «سؤال بد» (§10.2) ------------------------

MATRIX = [
    [1, 0, 1, 0],
    [1, 0, 1, 0],
    [1, 0, 0, 0],
    [1, 0, 0, 0],
    [1, 1, 0, 0],
    [1, 1, 0, 0],
    [1, 1, 1, 0],
    [1, 1, 0, 1],
]
STUDENTS = ["student1", "student2", "student3", "student4", "student5", "s2student1", "s2student2", "s2student3"]


async def seed_attempts(exam_id: int, items: list[dict]) -> None:
    """۸ تلاش تصحیح‌شده با الگوی کنترل‌شده (پاسخ درست/غلط هر سؤال)."""
    items_by_order = sorted(items, key=lambda it: it["order"])
    async with AsyncSessionLocal() as s:
        exam = await s.get(Exam, exam_id)
        users = (
            await s.execute(select(User).where(User.username.in_(STUDENTS)).order_by(User.id))
        ).scalars().all()
        assert len(users) == len(MATRIX)
        for user, row in zip(users, MATRIX):
            attempt = ExamAttempt(exam_id=exam_id, student_user_id=user.id, status="in_progress")
            s.add(attempt)
            await s.flush()
            answers = []
            for it, ok in zip(items_by_order, row):
                correct = it["correct_option"]
                selected = correct if ok else ("A" if correct != "A" else "B")
                answers.append(
                    {
                        "exam_item_id": it["exam_item_id"],
                        "selected": selected,
                        "confidence": 3,
                        "time_spent_ms": 25000,
                    }
                )
            await submit_attempt(s, exam=exam, attempt=attempt, answers=answers)
        await s.commit()


@pytest.mark.anyio
async def test_item_analysis_flags_bad_items(client, seeded):
    h = auth(await login(client, "teacher1"))
    detail, items = await build_exam(client, h)
    assert len(items) == 4
    await seed_attempts(detail["exam"]["id"], items)

    r = await client.get(f"/teacher/exams/{detail['exam']['id']}/item-analysis", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["attempts"] == 8
    rows = sorted(data["items"], key=lambda x: x["order"])
    assert len(rows) == 4

    # سالم: قدرت تفکیک بالا و اختلاف دشواری کم
    healthy = next(x for x in rows if x["order"] == 2)
    assert healthy["discrimination"] is not None and healthy["discrimination"] >= 0.15
    assert healthy["needs_review"] is False

    # سؤال بد ۱: همه درست ⇒ قدرت تفکیک ۰٫۰ < ۰٫۱۵
    weak_disc = next(x for x in rows if x["order"] == 1)
    assert weak_disc["discrimination"] == 0.0
    assert weak_disc["needs_review"] is True
    assert "قدرت تفکیک" in weak_disc["review_reasons"][0]

    # سؤال بد ۲ و ۳: اختلاف دشواری تجربی و پیش‌فرض > ۰٫۳
    for order in (3, 4):
        row = next(x for x in rows if x["order"] == order)
        assert row["needs_review"] is True
        assert any("اختلاف دشواری" in reason for reason in row["review_reasons"])
        assert "⚠" in row["comment_fa"]
    assert data["flagged_count"] == 3

    # پرتکرارترین گزینهٔ غلط + کج‌فهمی مرتبط (§10.1)
    row3 = next(x for x in rows if x["order"] == 3)
    assert row3["top_wrong_option"] == "A"
    assert row3["top_wrong_pct"] == 100.0
    assert "مفهومی" in row3["misconception"]  # علت گزینهٔ A از distractor_causes

    # زمان: دادهٔ یکنواخت ⇒ بدون پرچم z (پرشِ زمانی صادقانه رد می‌شود)
    assert all(x["avg_time_ms"] == 25000 for x in rows)
    assert all(not any("زمان" in reason for reason in x["review_reasons"]) for x in rows)

    # پایداری پرچم در جدول اختصاصی (بدون افزودن ستون به جدول‌های موجود)
    async with AsyncSessionLocal() as s:
        stored = (
            await s.execute(select(ItemAnalysis).where(ItemAnalysis.exam_id == detail["exam"]["id"]))
        ).scalars().all()
        assert len(stored) == 4
        assert sum(row.needs_review for row in stored) == 3


# ------------------------------ گاردها و دسترسی ------------------------------


@pytest.mark.anyio
async def test_exam_builder_guards(client, seeded):
    # دانش‌آموز → 403
    sh = auth(await login(client, "student1"))
    r = await client.post(
        "/teacher/exams", headers=sh,
        json={"title_fa": "آزمون من", "class_id": 1},
    )
    assert r.status_code == 403

    h1 = auth(await login(client, "teacher1"))
    h2 = auth(await login(client, "teacher2"))

    # teacher1 فقط کلاس خودش را دارد (کلاس ۲ مال teacher2 است)
    r = await client.post(
        "/teacher/exams", headers=h1,
        json={"title_fa": "دست‌درازی", "class_id": 2},
    )
    assert r.status_code == 403
    r = await client.post(
        "/teacher/exams", headers=h1,
        json={"title_fa": "نامعتبر", "class_id": 999},
    )
    assert r.status_code == 403

    exam = await make_exam(client, h1)
    eid = exam["id"]

    # teacher2 هیچ دسترسی‌ای به آزمون معلم دیگر ندارد
    for method, url in [
        ("GET", f"/teacher/exams/{eid}"),
        ("GET", f"/teacher/exams/{eid}/item-analysis"),
    ]:
        r = await client.request(method, url, headers=h2)
        assert r.status_code == 403, url
    r = await client.patch(f"/teacher/exams/{eid}", headers=h2, json={"title_fa": "x"})
    assert r.status_code == 403
    r = await client.post(f"/teacher/exams/{eid}/blueprint", headers=h2, json={"goal": "هدف"})
    assert r.status_code == 403
    r = await client.post(f"/teacher/exams/{eid}/items", headers=h2, json={"source": "blueprint"})
    assert r.status_code == 403
    r = await client.post(f"/teacher/exams/{eid}/publish", headers=h2)
    assert r.status_code == 403

    # فهرست teacher2 خالی است (مالکیت)
    r = await client.get("/teacher/exams", headers=h2)
    assert r.json()["exams"] == []

    # آزمون ناموجود → 404
    r = await client.get("/teacher/exams/9999", headers=h1)
    assert r.status_code == 404

    # انتشار بدون سؤال → 400 (خطای درون‌خطی)
    r = await client.post(f"/teacher/exams/{eid}/publish", headers=h1)
    assert r.status_code == 400
    # مونتاژ بدون بلوپرینت → 400
    r = await client.post(f"/teacher/exams/{eid}/items", headers=h1, json={"source": "blueprint"})
    assert r.status_code == 400
    # بلوپرینت بدون هدف → 400
    r = await client.post(f"/teacher/exams/{eid}/blueprint", headers=h1, json={"goal": "   "})
    assert r.status_code == 400
    # حالت/نوع نامعتبر → 400
    r = await client.post(
        "/teacher/exams", headers=h1,
        json={"title_fa": "x", "class_id": 1, "mode": "weird"},
    )
    assert r.status_code == 400

    # ---- حالت تشخیصی شخصی (§8.3): فقط SLM، بدون برد ----
    personal = await make_exam(client, h1, title_fa="تشخیصی شخصی", mode="personal_diagnostic")
    r = await client.post(
        f"/teacher/exams/{personal['id']}/items",
        headers=h1,
        json={"source": "bank", "item_id": 1},
    )
    assert r.status_code == 200, r.text
    # سؤال تکراری از بانک → 409
    r = await client.post(
        f"/teacher/exams/{personal['id']}/items",
        headers=h1,
        json={"source": "bank", "item_id": 1},
    )
    assert r.status_code == 409

    r = await client.post(f"/teacher/exams/{personal['id']}/publish", headers=h1)
    assert r.status_code == 200, r.text
    assert r.json()["exam"]["scope"] == "personal"
    assert "تشخیصی شخصی" in r.json()["exam"]["mode_fa"]
