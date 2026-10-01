"""آزمون‌های رسمی ناحیه، تحلیل سؤال، مداخله آموزشی و مأموریت مدارس
(district spec §20–§21, §25–§27): چرخه وضعیت آزمون + ممیزی انتشار، نتایج
با سرکوب حداقل جمعیت، تحلیل سؤال با علامت «نیازمند بازبینی»، سنجش اثر
مداخله (پیش/پس/ماندگاری) و داشبورد پیشرفت مأموریت."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_districtexams.db")

from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.db import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.assessment import QuestionItem
from app.models.catalog import Topic
from app.models.district_exams import DistrictExam
from app.models.org import District, School, User
from app.models.rbac import AuditLog
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


async def login(client, username, password="pass123"):
    r = await client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


async def user_id(username: str) -> int:
    async with AsyncSessionLocal() as s:
        return (
            (await s.execute(select(User.id).where(User.username == username))).scalar_one()
        )


async def audit_rows(action: str) -> list[tuple[int | None, str | None]]:
    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id))
        ).scalars().all()
        return [(r.actor_user_id, r.detail) for r in rows]


async def topic_id_by_title(title: str) -> int:
    async with AsyncSessionLocal() as s:
        return (await s.execute(select(Topic.id).where(Topic.title_fa == title))).scalar_one()


async def question_bank() -> list[QuestionItem]:
    """کل بانک سؤال ریاضی دهم به ترتیب شناسه (۴ سؤال seed + سؤال‌های تست)."""
    async with AsyncSessionLocal() as s:
        return list((await s.execute(select(QuestionItem).order_by(QuestionItem.id))).scalars())


async def outside_school() -> int:
    """مدرسه‌ای در ناحیه دیگر — برای بررسی ایزوله‌بودن حوزه ناحیه."""
    async with AsyncSessionLocal() as s:
        district = District(province_id=1, name="ناحیه ۲ تهران")
        s.add(district)
        await s.flush()
        school = School(
            district_id=district.id,
            province_id=1,
            name="مدرسه خارج از ناحیه",
            school_code="S-9001",
            school_type="high_school",
            ownership_type="private",
        )
        s.add(school)
        await s.commit()
        return school.id


EXAM_PAYLOAD = {
    "title_fa": "آزمون رسمی ناحیه — ریاضی دهم، دوره ۱",
    "grade": "grade_10",
    "subject": "math",
    "school_ids": [1, 2],
    "blueprint": "سرفصل: مجموعه‌ها و عملیات روی مجموعه‌ها — ۶ سؤال چهارگزینه‌ای",
}


# ------------------------- §20 چرخه وضعیت + گاردها -------------------------


@pytest.mark.anyio
async def test_official_exam_lifecycle_and_guards(client, seeded):
    dtok = await login(client, "districtadmin")
    stok = await login(client, "schooladmin")
    ptok = await login(client, "provinceadmin")

    # ---- گاردهای حوزه: مدیر مدرسه و مدیر کل → 403 ----
    r = await client.get("/district/exams", headers=auth(stok))
    assert r.status_code == 403
    r = await client.post("/district/exams", headers=auth(stok), json=EXAM_PAYLOAD)
    assert r.status_code == 403
    r = await client.get("/district/exams", headers=auth(ptok))
    assert r.status_code == 403
    r = await client.patch("/district/exams/1/status", headers=auth(stok), json={"status": "published"})
    assert r.status_code == 403

    # ---- اعتبارسنجی‌های ساخت ----
    bad = {**EXAM_PAYLOAD, "title_fa": "   "}
    r = await client.post("/district/exams", headers=auth(dtok), json=bad)
    assert r.status_code == 400

    bad = {**EXAM_PAYLOAD, "school_ids": []}
    r = await client.post("/district/exams", headers=auth(dtok), json=bad)
    assert r.status_code == 400

    outside = await outside_school()
    bad = {**EXAM_PAYLOAD, "school_ids": [outside]}
    r = await client.post("/district/exams", headers=auth(dtok), json=bad)
    assert r.status_code == 400  # مدرسه خارج از ناحیه

    # درس بدون بانک سؤال و بدون item_ids صریح
    bad = {**EXAM_PAYLOAD, "subject": "geology"}
    r = await client.post("/district/exams", headers=auth(dtok), json=bad)
    assert r.status_code == 400
    assert "بانک سؤال" in r.json()["detail"]

    bad = {**EXAM_PAYLOAD, "opens_at": "2026-01-10T10:00:00", "closes_at": "2026-01-09T10:00:00"}
    r = await client.post("/district/exams", headers=auth(dtok), json=bad)
    assert r.status_code == 400

    # ---- ساخت موفق (نمونه خودکار از بانک) ----
    r = await client.post("/district/exams", headers=auth(dtok), json=EXAM_PAYLOAD)
    assert r.status_code == 200, r.text
    exam = r.json()["exam"]
    exam_id, backing_id = exam["id"], exam["exam_id"]
    assert exam["status"] == "draft"
    assert exam["status_fa"] == "پیش‌نویس"
    assert exam["next_statuses"] == ["published"]
    assert {sc["id"] for sc in exam["schools"]} == {1, 2}
    assert len(exam["items"]) == 4  # نمونه خودکار از بانک ریاضی دهم (۴ سؤال seed)
    assert exam["created_by_name"] == "مدیر ناحیه"

    created = await audit_rows("district_exam_created")
    assert len(created) == 1
    assert created[0][0] == await user_id("districtadmin")

    # ---- ساخت با item_ids صریح ----
    bank = await question_bank()
    r = await client.post(
        "/district/exams",
        headers=auth(dtok),
        json={**EXAM_PAYLOAD, "title_fa": "آزمون با سؤال صریح", "item_ids": [bank[0].id, bank[1].id]},
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["exam"]["items"]) == 2
    r = await client.post(
        "/district/exams",
        headers=auth(dtok),
        json={**EXAM_PAYLOAD, "title_fa": "سؤال ناموجود", "item_ids": [999999]},
    )
    assert r.status_code == 400

    # ---- گذارهای نامجاز ----
    r = await client.patch(
        f"/district/exams/{exam_id}/status", headers=auth(dtok), json={"status": "closed"}
    )
    assert r.status_code == 400
    r = await client.patch(
        f"/district/exams/{exam_id}/status", headers=auth(dtok), json={"status": "archived"}
    )
    assert r.status_code == 400

    # ---- انتشار + ممیزی «چه کسی منتشر کرد؟» ----
    r = await client.patch(
        f"/district/exams/{exam_id}/status", headers=auth(dtok), json={"status": "published"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["exam"]["status"] == "published"
    published = await audit_rows("district_exam_published")
    assert len(published) == 1
    assert published[0][0] == await user_id("districtadmin")
    assert "district=1" in (published[0][1] or "")

    # آزمون پیوندی منتشر شد → دانش‌آموز آن را در فهرست می‌بیند
    s1tok = await login(client, "student1")
    r = await client.get("/student/exams", headers=auth(s1tok))
    titles = [e["title"] for e in r.json()["exams"]]
    assert EXAM_PAYLOAD["title_fa"] in titles

    # ---- فهرست + فیلتر وضعیت ----
    r = await client.get("/district/exams", headers=auth(dtok))
    body = r.json()
    assert body["total"] == 2
    by_id = {row["id"]: row for row in body["exams"]}
    assert by_id[exam_id]["schools_count"] == 2
    assert by_id[exam_id]["items_count"] == 4
    assert by_id[exam_id]["participants"] == 0
    r = await client.get("/district/exams", headers=auth(dtok), params={"status": "draft"})
    assert r.json()["total"] == 1  # فقط «آزمون با سؤال صریح»
    r = await client.get("/district/exams", headers=auth(dtok), params={"status": "published"})
    assert r.json()["total"] == 1

    # ---- بازگشت به پیش‌نویس (بدون پاسخ) و انتشار دوباره ----
    r = await client.patch(
        f"/district/exams/{exam_id}/status", headers=auth(dtok), json={"status": "draft"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["exam"]["status"] == "draft"
    assert len(await audit_rows("district_exam_unpublished")) == 1
    r = await client.patch(
        f"/district/exams/{exam_id}/status", headers=auth(dtok), json={"status": "published"}
    )
    assert r.status_code == 200

    # ---- ایزوله‌بودن ناحیه: آزمون ناحیه دیگر → 404 ----
    async with AsyncSessionLocal() as s:
        other = DistrictExam(district_id=99, title_fa="ناحیه دیگر", grade="grade_10", subject="math", status="draft")
        s.add(other)
        await s.commit()
        other_id = other.id
    r = await client.get(f"/district/exams/{other_id}", headers=auth(dtok))
    assert r.status_code == 404
    r = await client.get(f"/district/exams/{other_id}/results", headers=auth(dtok))
    assert r.status_code == 404

    # ---- جزئیات ----
    r = await client.get(f"/district/exams/{exam_id}", headers=auth(dtok))
    assert r.status_code == 200
    detail = r.json()["exam"]
    assert detail["blueprint"] == EXAM_PAYLOAD["blueprint"]
    assert len(detail["schools"]) == 2
    assert len(detail["items"]) == 4
    assert detail["next_statuses"] == ["draft", "graded"]
    assert backing_id == detail["exam_id"]


# ------------------------- نتایج + §21 تحلیل سؤال -------------------------


async def add_review_items() -> tuple[int, int]:
    """دو سؤال «نیازمند بازبینی» مهندسی‌شده برای §21:
    - سؤال سختی که گروه ضعیف درست می‌زند → قدرت تفکیک منفی (< 0.15)
    - سؤال سختی که همه درست می‌زنند → فاصله تجربی/پیشینی > 0.3"""
    topic_id = await topic_id_by_title("مجموعه‌ها و عملیات")
    async with AsyncSessionLocal() as s:
        q5 = QuestionItem(
            topic_id=topic_id,
            body="کدام گزینه درباره تعداد زیرمجموعه‌ها درست است؟",
            options={"A": "2^n", "B": "n!", "C": "n+1", "D": "n^2"},
            correct_option="A",
            difficulty="hard",
            difficulty_weight=1.5,
            misconception="کج‌فهمی نامعتبر بودن توان ۲",
            distractor_causes={"B": "conceptual", "C": "calculation"},
        )
        q6 = QuestionItem(
            topic_id=topic_id,
            body="قضیه: هر مجموعه با خودش برابر است. تعداد زیرمجموعه‌های مجموعه تهی؟",
            options={"A": "0", "B": "1", "C": "2", "D": "3"},
            correct_option="D",
            difficulty="hard",
            difficulty_weight=1.5,
        )
        s.add_all([q5, q6])
        await s.commit()
        return q5.id, q6.id


# الگوی پاسخ‌ها: (دانش‌آموز → ترتیب سؤال‌های «درست»؛ بقیه غلط؛ سؤال ۵ برای
# student1-3 خالی می‌ماند). ترتیب سؤال‌ها = ترتیب شناسه بانک (۱..۶).
S2_CORRECT_A = {1, 2, 3, 4, 6}   # s2student1..5
S2_CORRECT_B = {1, 2, 3, 6}      # s2student6..10
S1_ANSWERS = {
    "student1": {1, 3, 4, 5, 6},
    "student2": {1, 3, 4, 5, 6},
    "student3": {1, 6},           # سؤال ۵ را خالی می‌گذارد
    "student4": {1, 4, 5, 6},
    "student5": {1, 5, 6},
}
S1_BLANK = {"student3": 5}


@pytest.mark.anyio
async def test_official_exam_results_and_item_analysis(client, seeded):
    dtok = await login(client, "districtadmin")
    await add_review_items()

    r = await client.post("/district/exams", headers=auth(dtok), json=EXAM_PAYLOAD)
    assert r.status_code == 200, r.text
    exam = r.json()["exam"]
    exam_id, backing_id = exam["id"], exam["exam_id"]

    # نقشه ترتیب سؤال → شناسه سؤال + گزینه درست
    order_to_item = {it["order"]: it["item_id"] for it in exam["items"]}
    assert len(order_to_item) == 6
    bank = {q.id: q for q in await question_bank()}

    r = await client.patch(
        f"/district/exams/{exam_id}/status", headers=auth(dtok), json={"status": "published"}
    )
    assert r.status_code == 200, r.text

    # نتایج پیش از شرکت دانش‌آموزان: صفر شرکت‌کننده، زیر حد نصاب
    r = await client.get(f"/district/exams/{exam_id}/results", headers=auth(dtok))
    assert r.status_code == 200
    res0 = r.json()
    assert res0["overall"]["participants"] == 0
    assert res0["overall"]["avg_percent"] is None
    assert res0["overall"]["suppressed"] is True

    # ---- ۱۵ دانش‌آموز (۵ نفر مدرسه ۱ + ۱۰ نفر مدرسه ۲) شرکت می‌کنند ----
    async def take_exam(username: str, correct_orders: set[int], blank_order: int | None = None):
        tok = await login(client, username)
        r = await client.post(f"/student/exams/{backing_id}/start", headers=auth(tok))
        assert r.status_code == 200, r.text
        answers = []
        for it in r.json()["items"]:
            order = it["order"]
            item = bank[order_to_item[order]]
            if blank_order is not None and order == blank_order:
                answers.append({"exam_item_id": it["exam_item_id"], "selected": None, "time_spent_ms": 30000})
            elif order in correct_orders:
                answers.append(
                    {"exam_item_id": it["exam_item_id"], "selected": item.correct_option, "confidence": 4, "time_spent_ms": 30000}
                )
            else:
                wrong = "B" if item.correct_option == "A" else "A"
                answers.append(
                    {"exam_item_id": it["exam_item_id"], "selected": wrong, "confidence": 3, "time_spent_ms": 30000}
                )
        r = await client.post(
            f"/student/exams/{backing_id}/submit", headers=auth(tok), json={"answers": answers}
        )
        assert r.status_code == 200, r.text
        return r.json()["percent"]

    for i in range(1, 11):
        await take_exam(f"s2student{i}", S2_CORRECT_A if i <= 5 else S2_CORRECT_B)
    for username, orders in S1_ANSWERS.items():
        await take_exam(username, orders, blank_order=S1_BLANK.get(username))

    # ---- نتایج تجمیعی با سرکوب حداقل جمعیت ----
    r = await client.get(f"/district/exams/{exam_id}/results", headers=auth(dtok))
    assert r.status_code == 200, r.text
    res = r.json()
    overall = res["overall"]
    assert overall["participants"] == 15
    assert overall["eligible"] == 15
    assert overall["participation_rate"] == 100.0
    assert overall["suppressed"] is False
    assert overall["avg_percent"] == pytest.approx(71.1, abs=0.1)
    assert overall["pass_rate"] == pytest.approx(86.7, abs=0.1)
    assert overall["pass_percent"] == 60.0
    assert overall["outside_participants"] == 0
    assert "حداقل" in res["note_fa"]

    schools = {row["school_id"]: row for row in res["schools"]}
    assert set(schools) == {1, 2}
    # مدرسه ۱: ۵ شرکت‌کننده < حداقل جمعیت ۱۰ → سرکوب
    assert schools[1]["participants"] == 5
    assert schools[1]["suppressed"] is True
    assert schools[1]["avg_percent"] is None
    assert schools[1]["pass_rate"] is None
    # مدرسه ۲: ۱۰ شرکت‌کننده → اعداد نمایش داده می‌شود
    assert schools[2]["participants"] == 10
    assert schools[2]["suppressed"] is False
    assert schools[2]["avg_percent"] == pytest.approx(75.0, abs=0.1)
    assert schools[2]["pass_rate"] == pytest.approx(100.0, abs=0.1)

    classes = {row["name"]: row for row in res["classes"]}
    assert set(classes) == {"۱۰۱", "۱۰۲", "۲۰۱"}
    assert classes["۲۰۱"]["suppressed"] is False
    assert classes["۲۰۱"]["participants"] == 10
    assert classes["۱۰۱"]["suppressed"] is True
    assert classes["۱۰۲"]["suppressed"] is True

    # ---- تحلیل سؤال (§21) ----
    r = await client.get(f"/district/exams/{exam_id}/item-analysis", headers=auth(dtok))
    assert r.status_code == 200, r.text
    analysis = r.json()
    items = {row["order"]: row for row in analysis["items"]}
    assert len(items) == 6
    assert analysis["thresholds"]["discrimination"] == 0.15
    assert analysis["thresholds"]["difficulty_gap"] == 0.3

    # سؤال ۱ (همه درست — easy): بدون علامت
    it1 = items[1]
    assert it1["responses"] == 15
    assert it1["pct_correct"] == 100.0
    assert it1["empirical_difficulty"] == 1.0
    assert it1["needs_review"] is False
    assert it1["review_reasons"] == []

    # سؤال ۲ (easy، گروه مدرسه ۱ غلط): پرتکرارترین گزینه غلط + کج‌فهمی علت
    it2 = items[2]
    assert it2["pct_correct"] == pytest.approx(66.7, abs=0.1)
    assert it2["top_distractor"] == "A"
    assert it2["top_distractor_cause"] == "conceptual"
    assert it2["discrimination"] is not None and it2["discrimination"] > 0.15
    assert it2["needs_review"] is False

    # سؤال ۳ (medium): کج‌همی مرتبطِ بانک سؤال سر جایش است
    it3 = items[3]
    assert it3["misconception"] == "اشتباه 2^n با n"
    assert it3["top_distractor"] == "A"
    assert it3["top_distractor_cause"] == "calculation"

    # سؤال ۵ (ساخته‌شده): قدرت تفکیک منفی → نیازمند بازبینی + ۱ پاسخ خالی
    it5 = items[5]
    assert it5["responses"] == 15
    assert it5["discrimination"] is not None and it5["discrimination"] < 0.15
    assert it5["blank_pct"] == pytest.approx(6.7, abs=0.1)
    assert it5["needs_review"] is True
    assert [rr["code"] for rr in it5["review_reasons"]] == ["discrimination"]
    assert it5["misconception"] == "کج‌فهمی نامعتبر بودن توان ۲"
    assert it5["top_distractor"] == "B"
    assert it5["top_distractor_cause"] == "conceptual"

    # سؤال ۶ (همه درست ولی سخت): فاصله تجربی/پیشینی → نیازمند بازبینی
    it6 = items[6]
    assert it6["pct_correct"] == 100.0
    assert it6["empirical_difficulty"] == 1.0
    assert it6["prior_difficulty"] == 0.45
    assert it6["needs_review"] is True
    assert [rr["code"] for rr in it6["review_reasons"]] == ["difficulty_gap"]

    # میانگین زمان پاسخ (§21)
    assert all(it["avg_time_ms"] == 30000 for it in items.values())

    # ---- تصحیح/بستن + ممیزی؛ بازگشت به پیش‌نویس بعد از پاسخ ممنوع ----
    r = await client.patch(
        f"/district/exams/{exam_id}/status", headers=auth(dtok), json={"status": "draft"}
    )
    assert r.status_code == 409

    r = await client.patch(
        f"/district/exams/{exam_id}/status", headers=auth(dtok), json={"status": "graded"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["exam"]["status"] == "graded"
    assert len(await audit_rows("district_exam_graded")) == 1

    # شرکت‌کنندگان در فهرست لحاظ شدند
    r = await client.get("/district/exams", headers=auth(dtok))
    row = next(x for x in r.json()["exams"] if x["id"] == exam_id)
    assert row["participants"] == 15

    # نتایج پس از تصحیح همچنان در دسترس‌اند
    r = await client.get(f"/district/exams/{exam_id}/results", headers=auth(dtok))
    assert r.json()["overall"]["participants"] == 15

    r = await client.patch(
        f"/district/exams/{exam_id}/status", headers=auth(dtok), json={"status": "closed"}
    )
    assert r.status_code == 200
    assert len(await audit_rows("district_exam_closed")) == 1
    r = await client.patch(
        f"/district/exams/{exam_id}/status", headers=auth(dtok), json={"status": "published"}
    )
    assert r.status_code == 400  # از بسته‌شده هیچ گذاری مجاز نیست


# ------------------------- §25–§26 مداخله و سنجش اثر -------------------------


@pytest.mark.anyio
async def test_intervention_effect_verdicts(client, seeded):
    dtok = await login(client, "districtadmin")
    stok = await login(client, "schooladmin")
    topic_id = await topic_id_by_title("مجموعه‌ها و عملیات")

    # ---- گاردها ----
    r = await client.get("/district/interventions", headers=auth(stok))
    assert r.status_code == 403

    # ---- اعتبارسنجی ----
    r = await client.post(
        "/district/interventions",
        headers=auth(dtok),
        json={"title_fa": "بدون عنوان", "type": "magic", "school_ids": [1]},
    )
    assert r.status_code == 400
    r = await client.post(
        "/district/interventions",
        headers=auth(dtok),
        json={"title_fa": "خارج از ناحیه", "type": "course", "school_ids": [999]},
    )
    assert r.status_code == 400
    # بدون before و بدون مبحث
    r = await client.post(
        "/district/interventions",
        headers=auth(dtok),
        json={"title_fa": "نیازمند سنجش", "type": "course", "school_ids": [1]},
    )
    assert r.status_code == 400
    # before خودکار از تجمیع: زیر حداقل جمعیت (فقط مدرسه ۱) → 400
    r = await client.post(
        "/district/interventions",
        headers=auth(dtok),
        json={
            "title_fa": "زیر حد نصاب",
            "type": "course",
            "school_ids": [1],
            "topic_id": topic_id,
        },
    )
    assert r.status_code == 400
    assert "حداقل جمعیت" in r.json()["detail"]

    # ---- مداخله اثربخش: before 45 → after 70 → retention 65 ----
    r = await client.post(
        "/district/interventions",
        headers=auth(dtok),
        json={
            "title_fa": "برنامه جبر ترمیمی",
            "type": "course",
            "school_ids": [1, 2],
            "topic_id": topic_id,
            "grade": "grade_10",
            "before_mastery": 45.0,
            "notes": "۲ هفته دوره ضمن خدمت",
        },
    )
    assert r.status_code == 200, r.text
    iv = r.json()["intervention"]
    iv1 = iv["id"]
    assert iv["type_fa"] == "دوره آموزشی"
    assert iv["before_mastery"] == 45.0
    assert iv["verdict"] == "pending"
    assert iv["verdict_fa"] == "در انتظار بازآزمون"
    assert iv["start_date"] is not None and iv["end_date"] is not None

    # سنجش ماندگاری بدون بازآزمون → 409
    r = await client.patch(
        f"/district/interventions/{iv1}",
        headers=auth(dtok),
        json={"stage": "retention", "mastery": 60.0},
    )
    assert r.status_code == 409
    # مرحله نامعتبر / مقدار خارج از دامنه → 400
    r = await client.patch(
        f"/district/interventions/{iv1}", headers=auth(dtok), json={"stage": "x", "mastery": 60.0}
    )
    assert r.status_code == 400
    r = await client.patch(
        f"/district/interventions/{iv1}", headers=auth(dtok), json={"stage": "after", "mastery": 140.0}
    )
    assert r.status_code == 400
    # فقط stage یا فقط mastery → 400
    r = await client.patch(
        f"/district/interventions/{iv1}", headers=auth(dtok), json={"stage": "after"}
    )
    assert r.status_code == 400

    # بازآزمون: رشد ۲۵ واحدی
    r = await client.patch(
        f"/district/interventions/{iv1}",
        headers=auth(dtok),
        json={"stage": "after", "mastery": 70.0},
    )
    assert r.status_code == 200, r.text
    iv = r.json()["intervention"]
    assert iv["delta_after"] == 25.0
    assert iv["verdict"] == "needs_retention"
    assert iv["next_stage"] == "retention"

    # ماندگاری ۳ هفته بعد: ۶۱٪ → بالاتر از before + حداقل رشد → اثر داشته
    r = await client.patch(
        f"/district/interventions/{iv1}",
        headers=auth(dtok),
        json={"stage": "retention", "mastery": 61.0},
    )
    assert r.status_code == 200, r.text
    iv = r.json()["intervention"]
    assert iv["delta_retention"] == 16.0
    assert iv["verdict"] == "effective"
    assert iv["verdict_fa"] == "اثر داشته"

    # ---- مداخله بی‌اثر: بازآزمون بهبودی نشان نمی‌دهد ----
    r = await client.post(
        "/district/interventions",
        headers=auth(dtok),
        json={
            "title_fa": "نظارت بدون اثر",
            "type": "supervision",
            "school_ids": [2],
            "topic_id": topic_id,
            "before_mastery": 40.0,
        },
    )
    assert r.status_code == 200, r.text
    iv2 = r.json()["intervention"]["id"]
    r = await client.patch(
        f"/district/interventions/{iv2}",
        headers=auth(dtok),
        json={"stage": "after", "mastery": 42.0},
    )
    assert r.status_code == 200
    assert r.json()["intervention"]["verdict"] == "ineffective"
    assert r.json()["intervention"]["verdict_fa"] == "بی‌اثر"
    assert r.json()["intervention"]["delta_after"] == 2.0

    # ---- نیاز به توجه: رشد اولیه ولی افت ماندگاری ----
    r = await client.post(
        "/district/interventions",
        headers=auth(dtok),
        json={
            "title_fa": "برنامه آموزشی متزلزل",
            "type": "program",
            "school_ids": [1, 2],
            "topic_id": topic_id,
            "before_mastery": 40.0,
        },
    )
    iv3 = r.json()["intervention"]["id"]
    r = await client.patch(
        f"/district/interventions/{iv3}",
        headers=auth(dtok),
        json={"stage": "after", "mastery": 70.0},
    )
    assert r.json()["intervention"]["verdict"] == "needs_retention"
    r = await client.patch(
        f"/district/interventions/{iv3}",
        headers=auth(dtok),
        json={"stage": "retention", "mastery": 44.0},
    )
    iv = r.json()["intervention"]
    assert iv["verdict"] == "needs_attention"
    assert iv["verdict_fa"] == "نیاز به توجه"

    # ---- before خودکار از تجمیع تسط (بالای حداقل جمعیت) ----
    r = await client.post(
        "/district/interventions",
        headers=auth(dtok),
        json={
            "title_fa": "اندازه‌گیری خودکار",
            "type": "course",
            "school_ids": [1, 2],
            "topic_id": topic_id,
        },
    )
    assert r.status_code == 200, r.text
    auto = r.json()["intervention"]
    assert auto["before_mastery"] is not None
    assert 0.0 <= auto["before_mastery"] <= 100.0

    # ---- بستن مداخله + ممیزی؛ اندازه‌گیری بعد از بستن ممنوع ----
    r = await client.patch(
        f"/district/interventions/{iv1}", headers=auth(dtok), json={"status": "closed"}
    )
    assert r.status_code == 200
    assert r.json()["intervention"]["status_fa"] == "بسته‌شده"
    assert len(await audit_rows("district_intervention_closed")) == 1
    r = await client.patch(
        f"/district/interventions/{iv1}",
        headers=auth(dtok),
        json={"stage": "after", "mastery": 80.0},
    )
    assert r.status_code == 409

    # ---- فهرست: همه ردیف‌ها با verdict ----
    r = await client.get("/district/interventions", headers=auth(dtok))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    verdicts = {row["id"]: row["verdict"] for row in body["interventions"]}
    assert verdicts[iv1] == "effective"
    assert verdicts[iv2] == "ineffective"
    assert verdicts[iv3] == "needs_attention"
    row = next(x for x in body["interventions"] if x["id"] == iv1)
    assert {sc["id"] for sc in row["schools"]} == {1, 2}
    assert row["topic_title"] == "مجموعه‌ها و عملیات"

    # ایزوله‌بودن ناحیه: مداخله ناحیه دیگر نه دیده می‌شود نه قابل تغییر است
    async with AsyncSessionLocal() as s:
        from app.models.district_exams import DistrictIntervention

        other = DistrictIntervention(district_id=99, title_fa="ناحیه دیگر", type="course", status="active")
        s.add(other)
        await s.commit()
        other_id = other.id
    r = await client.get("/district/interventions", headers=auth(dtok))
    assert r.json()["total"] == 4
    assert all(row["id"] != other_id for row in r.json()["interventions"])
    r = await client.patch(
        f"/district/interventions/{other_id}", headers=auth(dtok), json={"status": "cancelled"}
    )
    assert r.status_code == 404
    r = await client.patch(
        "/district/interventions/9999", headers=auth(dtok), json={"status": "cancelled"}
    )
    assert r.status_code == 404


# ------------------------- §27 مأموریت برای مدارس -------------------------


@pytest.mark.anyio
async def test_missions_progress_and_status(client, seeded):
    dtok = await login(client, "districtadmin")
    stok = await login(client, "schooladmin")
    topic_id = await topic_id_by_title("مجموعه‌ها و عملیات")

    # ---- گاردها و اعتبارسنجی ----
    r = await client.get("/district/missions", headers=auth(stok))
    assert r.status_code == 403
    r = await client.post(
        "/district/missions",
        headers=auth(dtok),
        json={
            "title_fa": "بدون هدف",
            "goal": "",
            "topic_id": topic_id,
            "target_mastery": 70,
            "school_ids": [1],
        },
    )
    assert r.status_code == 400
    r = await client.post(
        "/district/missions",
        headers=auth(dtok),
        json={
            "title_fa": "هدف نامعتبر",
            "goal": "تسلط",
            "topic_id": topic_id,
            "target_mastery": 150,
            "school_ids": [1],
        },
    )
    assert r.status_code == 400
    r = await client.post(
        "/district/missions",
        headers=auth(dtok),
        json={
            "title_fa": "مبحث ناموجود",
            "goal": "تسلط",
            "topic_id": 99999,
            "target_mastery": 70,
            "school_ids": [1],
        },
    )
    assert r.status_code == 404
    r = await client.post(
        "/district/missions",
        headers=auth(dtok),
        json={"title_fa": "مدرسه ناموجود", "goal": "تسلط", "topic_id": topic_id, "target_mastery": 70, "school_ids": [999]},
    )
    assert r.status_code == 400

    # ---- ایجاد مأموریت + ممیزی سازنده (مهلت پیش‌فرض ~۲ هفته) ----
    r = await client.post(
        "/district/missions",
        headers=auth(dtok),
        json={
            "title_fa": "مأموریت مجموعه‌ها",
            "goal": "طی دو هفته، تسط مبحث مجموعه‌ها به حداقل ۹۹٪ برسد",
            "topic_id": topic_id,
            "target_mastery": 99.0,
            "school_ids": [1, 2],
        },
    )
    assert r.status_code == 200, r.text
    mission = r.json()["mission"]
    mission_id = mission["id"]
    assert mission["status"] == "active"
    assert mission["status_fa"] == "در حال اجرا"
    assert mission["schools_count"] == 2
    assert mission["days_left"] > 0  # مهلت پیش‌فرض ~۲ هفته
    created = await audit_rows("mission_created")
    assert len(created) == 1
    assert created[0][0] == await user_id("districtadmin")
    assert f"target=99.0" in (created[0][1] or "")

    # ---- داشبورد پیشرفت: سرکوب + وضعیت مدرسه‌ها ----
    r = await client.get(f"/district/missions/{mission_id}", headers=auth(dtok))
    assert r.status_code == 200, r.text
    detail = r.json()["mission"]
    assert detail["topic_title"] == "مجموعه‌ها و عملیات"
    schools = {sc["school_id"]: sc for sc in detail["schools"]}
    assert set(schools) == {1, 2}
    # مدرسه ۱: ۴ دانش‌آموز دارای داده < حداقل جمعیت → سرکوب
    assert schools[1]["suppressed"] is True
    assert schools[1]["avg_mastery"] is None
    assert schools[1]["status"] == "suppressed"
    assert schools[1]["status_fa"] == "زیر حد نصاب"
    # مدرسه ۲: ۱۰ دانش‌آموز دارای داده → عدد دیده می‌شود و هدف ۹۹٪ را ندارد
    assert schools[2]["suppressed"] is False
    assert schools[2]["avg_mastery"] is not None
    assert schools[2]["completed"] is False
    assert schools[2]["status"] in ("active", "overdue")
    assert detail["completed_count"] == 0
    assert detail["suppressed_count"] == 1
    assert detail["progress_avg"] is not None
    assert "حداقل" in detail["note_fa"]

    # ---- مأموریت تکمیل‌شده (هدف پایین) ----
    r = await client.post(
        "/district/missions",
        headers=auth(dtok),
        json={
            "title_fa": "مأموریت آسان",
            "goal": "هر مدرسه به تسط حداقل ۱۰٪ برسد",
            "topic_id": topic_id,
            "target_mastery": 10.0,
            "school_ids": [1, 2],
        },
    )
    assert r.status_code == 200, r.text
    easy = r.json()["mission"]
    assert easy["status"] == "completed"
    assert easy["status_fa"] == "تکمیل‌شده"
    assert easy["completed_count"] == 1  # فقط مدرسه ۲ قابل اندازه‌گیری است

    # ---- مأموریت عقب‌افتاده (مهلت گذشته) ----
    r = await client.post(
        "/district/missions",
        headers=auth(dtok),
        json={
            "title_fa": "مأموریت عقب‌افتاده",
            "goal": "مهلت گذشته",
            "topic_id": topic_id,
            "target_mastery": 99.0,
            "school_ids": [1, 2],
            "deadline": (date.today() - timedelta(days=1)).isoformat(),
        },
    )
    assert r.status_code == 200, r.text
    overdue = r.json()["mission"]
    assert overdue["status"] == "overdue"
    assert overdue["status_fa"] == "عقب‌افتاده"
    assert overdue["days_left"] < 0
    schools2 = {sc["school_id"]: sc for sc in overdue["schools"]}
    assert schools2[2]["status"] == "overdue"

    # ---- فهرست + ایزوله‌بودن ناحیه ----
    r = await client.get("/district/missions", headers=auth(dtok))
    body = r.json()
    assert body["total"] == 3
    statuses = {row["title_fa"]: row["status"] for row in body["missions"]}
    assert statuses["مأموریت مجموعه‌ها"] == "active"
    assert statuses["مأموریت آسان"] == "completed"
    assert statuses["مأموریت عقب‌افتاده"] == "overdue"

    async with AsyncSessionLocal() as s:
        from app.models.district_exams import DistrictMission

        other = DistrictMission(
            district_id=99, title_fa="مأموریت ناحیه دیگر", goal="x", topic_id=topic_id, target_mastery=50, deadline=date.today()
        )
        s.add(other)
        await s.commit()
        other_id = other.id
    r = await client.get(f"/district/missions/{other_id}", headers=auth(dtok))
    assert r.status_code == 404


# ------------------------- گزینه‌های مبحث (فرم‌ها) -------------------------


@pytest.mark.anyio
async def test_topics_options_endpoint(client, seeded):
    dtok = await login(client, "districtadmin")
    stok = await login(client, "schooladmin")

    r = await client.get("/district/topics", headers=auth(dtok))
    assert r.status_code == 200, r.text
    topics = r.json()["topics"]
    assert any(t["title"] == "مجموعه‌ها و عملیات" and t["subject"] == "math" for t in topics)
    assert all({"id", "title", "subject", "grade"} <= set(t) for t in topics)

    r = await client.get("/district/topics", headers=auth(stok))
    assert r.status_code == 403
