"""آزمون‌های سند صلاحیت معلم: تخصیص دو آزمون (درس + مدیریت کلاس) توسط
ناحیه، نمای معلم، پنهان‌بودن پاسخ درست، تصحیح و ارزیابی صلاحیت پس از هر دو
آزمون، گاردهای حوزه (معلم دیگر / ناحیه دیگر / مدیر مدرسه)، اقدام اصلاحی
و لاگ ممیزی + idempotency بودن تخصیص."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_daneshyar.db")

from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.db import AsyncSessionLocal, Base, engine
from app.core.passwords import hash_password
from app.main import app
from app.models.org import District, User
from app.models.rbac import AuditLog, Permission, PermissionAssignment, Role
from app.models.teacher_assessment import (
    TeacherAttemptAnswer,
    TeacherExam,
    TeacherExamAttempt,
    TeacherExamItem,
    TeacherExamQuestion,
    TeacherIntervention,
    TeacherQualification,
)
from app.services.teacher_qualification import current_school_year
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


async def audit_rows(action: str, contains: str | None = None) -> list[tuple[int | None, str | None]]:
    """رویدادهای یکسان در لاگ ممیزی (اختیاراً فقط ردیف‌های حاوی متن)."""
    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id))
        ).scalars().all()
        out = [(r.actor_user_id, r.detail) for r in rows]
    if contains is not None:
        out = [(a, d) for a, d in out if d and contains in d]
    return out


async def bank_count(kind: str, subject: str | None = None) -> int:
    async with AsyncSessionLocal() as s:
        q = select(TeacherExamQuestion).where(TeacherExamQuestion.kind == kind)
        if subject is not None:
            q = q.where(TeacherExamQuestion.subject == subject)
        return len((await s.execute(q)).scalars().all())


async def wrong_answers(exam_id: int) -> list[dict]:
    """پاسخ‌های عمداً غلط برای هر آیتم (برای رسیدن به نمره صفر)."""
    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                select(TeacherExamItem, TeacherExamQuestion)
                .join(TeacherExamQuestion, TeacherExamQuestion.id == TeacherExamItem.question_id)
                .where(TeacherExamItem.exam_id == exam_id)
                .order_by(TeacherExamItem.order)
            )
        ).all()
    out = []
    for item, question in rows:
        wrong = next(opt for opt in ("A", "B", "C", "D") if opt != question.correct_option)
        out.append({"item_id": item.id, "option": wrong})
    return out


async def make_other_district_admin() -> int:
    """مدیر ناحیه دیگر (با مجوزهای کامل در حوزه ناحیه خودش) — برای بررسی
    ایزوله‌بودن حوزه ناحیه."""
    async with AsyncSessionLocal() as s:
        district = District(province_id=1, name="ناحیه ۲ تهران")
        s.add(district)
        await s.flush()
        user = User(
            username="districtadmin2",
            password_hash=hash_password("pass123"),
            full_name="مدیر ناحیه ۲",
            system_role="district_admin",
        )
        s.add(user)
        await s.flush()
        role = (await s.execute(select(Role).where(Role.key == "district_admin"))).scalar_one()
        for key in ("view_district_analytics", "manage_teacher_qualifications"):
            perm = (
                await s.execute(select(Permission).where(Permission.key == key))
            ).scalar_one()
            s.add(
                PermissionAssignment(
                    user_id=user.id,
                    role_id=role.id,
                    permission_id=perm.id,
                    scope_type="district",
                    scope_id=district.id,
                    is_active=True,
                )
            )
        await s.commit()
        return user.id


def split_by_kind(exams: list[dict]) -> dict[str, int]:
    return {e["kind"]: e["id"] for e in exams}


# ------------------------- تخصیص + گاردهای حوزه -------------------------


@pytest.mark.anyio
async def test_assign_creates_two_exams_and_scope_guards(client, seeded):
    dtok = await login(client, "districtadmin")
    teacher2 = await user_id("teacher2")
    year = current_school_year()

    # سال تحصیلی قطعی و با قالب درست
    assert current_school_year(datetime(2026, 10, 1)) == "1405-1406"
    assert current_school_year(datetime(2026, 4, 5)) == "1404-1405"
    assert len(year.split("-")) == 2

    r = await client.post(
        "/district/teacher-qualifications/assign",
        headers=auth(dtok),
        json={"teacher_user_id": teacher2, "subject": "math"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] is True
    assert body["school_year"] == year
    kinds = {e["kind"] for e in body["exams"]}
    assert kinds == {"subject", "classroom_management"}
    by_kind = split_by_kind(body["exams"])

    async with AsyncSessionLocal() as s:
        # نمونه‌برداری سؤال از بانک (کمتر از ظرفیت بانک = کل بانک)
        for kind, exam_id in by_kind.items():
            items = (
                await s.execute(
                    select(TeacherExamItem).where(TeacherExamItem.exam_id == exam_id)
                )
            ).scalars().all()
            expected = min(
                10,
                await bank_count(kind, "math" if kind == "subject" else None),
            )
            assert len(items) == expected
            exam = await s.get(TeacherExam, exam_id)
            assert exam.teacher_user_id == teacher2
            assert exam.status == "assigned"
            assert exam.due_at is not None
            assert exam.subject_key == ("math" if kind == "subject" else "")

        # رکورد صلاحیت pending با پیوند به هر دو آزمون
        qual = (
            await s.execute(
                select(TeacherQualification).where(
                    TeacherQualification.teacher_user_id == teacher2,
                    TeacherQualification.subject == "math",
                    TeacherQualification.school_year == year,
                )
            )
        ).scalar_one()
        assert qual.status == "pending"
        assert qual.subject_exam_id == by_kind["subject"]
        assert qual.management_exam_id == by_kind["classroom_management"]
        assert qual.district_id == 1

    # رویداد ممیزی تخصیص (یکی برای هر آزمون)
    assigned = await audit_rows("teacher_exam_assigned", contains=f"teacher={teacher2}")
    assert len(assigned) == 2
    assert assigned[0][0] == await user_id("districtadmin")

    # نمای معلمِ مقصد
    t2tok = await login(client, "teacher2")
    r = await client.get("/teacher/assessments", headers=auth(t2tok))
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["school_year"] == year
    assert len(view["exams"]) == 2
    assert all(e["percent"] is None for e in view["exams"])
    assert len(view["qualifications"]) == 1
    assert view["qualifications"][0]["status"] == "pending"
    assert {e["qualification"]["status"] for e in view["exams"]} == {"pending"}

    # نمای معلمی که seed برایش تخصیص داده (بدون نمره جعلی)
    t1tok = await login(client, "teacher1")
    r = await client.get("/teacher/assessments", headers=auth(t1tok))
    assert r.status_code == 200
    seeded_view = r.json()
    assert len(seeded_view["exams"]) == 2
    assert {e["status"] for e in seeded_view["exams"]} == {"assigned"}
    assert all(e["percent"] is None for e in seeded_view["exams"])

    # پرسش‌نامه آزمون: هرگز پاسخ درست افشا نمی‌شود
    r = await client.get(
        f"/teacher/assessments/{by_kind['subject']}/questions", headers=auth(t2tok)
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert "correct_option" not in r.text
    assert payload["exam"]["kind"] == "subject"
    assert payload["exam"]["kind_fa"]
    assert payload["exam"]["due_at"]
    assert payload["items"]
    for item in payload["items"]:
        assert set(item) >= {"id", "order", "body", "options"}

    # معلم دیگر (صاحب آزمون نیست) → 403
    r = await client.get(
        f"/teacher/assessments/{by_kind['subject']}/questions", headers=auth(t1tok)
    )
    assert r.status_code == 403
    r = await client.post(
        f"/teacher/assessments/{by_kind['subject']}/start", headers=auth(t1tok)
    )
    assert r.status_code == 403
    # آزمون ناموجود → 404
    r = await client.get("/teacher/assessments/9999/questions", headers=auth(t2tok))
    assert r.status_code == 404

    # تخصیص برای درسی که معلم ارائه نمی‌دهد → 403
    r = await client.post(
        "/district/teacher-qualifications/assign",
        headers=auth(dtok),
        json={"teacher_user_id": teacher2, "subject": "physics"},
    )
    assert r.status_code == 403
    # معلم ناموجود → 404
    r = await client.post(
        "/district/teacher-qualifications/assign",
        headers=auth(dtok),
        json={"teacher_user_id": 99999, "subject": "math"},
    )
    assert r.status_code == 404

    # مدیر ناحیه دیگر (مجوزها را دارد ولی حوزه‌اش ناحیه دیگر است) → 403
    await make_other_district_admin()
    otok = await login(client, "districtadmin2")
    r = await client.post(
        "/district/teacher-qualifications/assign",
        headers=auth(otok),
        json={"teacher_user_id": teacher2, "subject": "math"},
    )
    assert r.status_code == 403
    r = await client.get("/district/teachers", headers=auth(otok))
    assert r.status_code == 200 and r.json()["total"] == 0

    # مدیر مدرسه حوزه ناحیه ندارد → 403
    stok = await login(client, "schooladmin")
    for path in ("/district/teachers", "/district/teacher-qualifications"):
        r = await client.get(path, headers=auth(stok))
        assert r.status_code == 403
    r = await client.post(
        "/district/teacher-qualifications/assign",
        headers=auth(stok),
        json={"teacher_user_id": teacher2, "subject": "math"},
    )
    assert r.status_code == 403


# ------------------------- تصحیح و ارزیابی صلاحیت -------------------------


@pytest.mark.anyio
async def test_submit_flow_grades_qualification(client, seeded):
    dtok = await login(client, "districtadmin")
    teacher2 = await user_id("teacher2")
    year = current_school_year()

    r = await client.post(
        "/district/teacher-qualifications/assign",
        headers=auth(dtok),
        json={"teacher_user_id": teacher2, "subject": "math"},
    )
    assert r.status_code == 200, r.text
    by_kind = split_by_kind(r.json()["exams"])
    t2tok = await login(client, "teacher2")

    async def take_exam(exam_id: int) -> dict:
        r = await client.post(f"/teacher/assessments/{exam_id}/start", headers=auth(t2tok))
        assert r.status_code == 200, r.text
        assert r.json()["attempt"]["status"] == "in_progress"
        # شروع دوباره همان تلاش → همان attempt (idempotent)
        r2 = await client.post(f"/teacher/assessments/{exam_id}/start", headers=auth(t2tok))
        assert r2.status_code == 200 and r2.json()["attempt"]["id"] == r.json()["attempt"]["id"]

        r = await client.get(f"/teacher/assessments/{exam_id}/questions", headers=auth(t2tok))
        assert r.status_code == 200 and r.json()["items"]
        answers = await wrong_answers(exam_id)
        r = await client.post(
            f"/teacher/assessments/{exam_id}/submit",
            headers=auth(t2tok),
            json={"answers": answers},
        )
        assert r.status_code == 200, r.text
        return r.json()

    # آزمون درس: نمره صفر — صلاحیت هنوز pending (آزمون مدیریت مانده)
    first = await take_exam(by_kind["subject"])
    assert first["percent"] == 0.0
    assert first["status"] == "graded"
    assert first["qualification_status"] == "pending"

    async with AsyncSessionLocal() as s:
        qual = (
            await s.execute(
                select(TeacherQualification).where(
                    TeacherQualification.teacher_user_id == teacher2,
                    TeacherQualification.school_year == year,
                )
            )
        ).scalar_one()
        assert qual.status == "pending"
        assert qual.subject_percent is None  # هنوز هر دو تصحیح نشده
        exam = await s.get(TeacherExam, by_kind["subject"])
        assert exam.status == "completed"

    # آزمون مدیریت کلاس: باز هم نمره صفر → زیر حد بحران → critical
    second = await take_exam(by_kind["classroom_management"])
    assert second["percent"] == 0.0
    assert second["qualification_status"] == "critical"

    async with AsyncSessionLocal() as s:
        qual = (
            await s.execute(
                select(TeacherQualification).where(
                    TeacherQualification.teacher_user_id == teacher2
                )
            )
        ).scalar_one()
        assert qual.status == "critical"
        assert qual.subject_percent == 0.0
        assert qual.management_percent == 0.0
        assert qual.evaluated_at is not None
        assert qual.status_note and "بحران" in qual.status_note
        # هر پاسخ ثبت شده و غلط علامت خورده
        attempts = (
            await s.execute(
                select(TeacherExamAttempt).where(
                    TeacherExamAttempt.teacher_user_id == teacher2
                )
            )
        ).scalars().all()
        assert {a.status for a in attempts} == {"graded"}
        answers = (await s.execute(select(TeacherAttemptAnswer))).scalars().all()
        assert answers and all(a.is_correct == 0 for a in answers)

    # رویدادهای ممیزی
    submitted = await audit_rows("teacher_exam_submitted")
    assert len(submitted) == 2
    changed = await audit_rows("qualification_status_changed", contains=f"teacher={teacher2}")
    assert len(changed) == 1
    assert "new=critical" in (changed[0][1] or "")

    # ارسال دوباره / شروع بعد از تکمیل → 409
    r = await client.post(
        f"/teacher/assessments/{by_kind['subject']}/start", headers=auth(t2tok)
    )
    assert r.status_code == 409
    r = await client.post(
        f"/teacher/assessments/{by_kind['subject']}/submit",
        headers=auth(t2tok),
        json={"answers": await wrong_answers(by_kind["subject"])},
    )
    assert r.status_code == 409

    # بدون start، submit → 409 (آزمونِ شروع‌نشده معلم دیگر)
    t1tok = await login(client, "teacher1")
    r = await client.get("/teacher/assessments", headers=auth(t1tok))
    seed_exam = next(
        e["id"] for e in r.json()["exams"] if e["kind"] == "classroom_management"
    )
    r = await client.post(
        f"/teacher/assessments/{seed_exam}/submit",
        headers=auth(t1tok),
        json={"answers": await wrong_answers(seed_exam)},
    )
    assert r.status_code == 409

    # شناسه سؤال متعلق به آزمون دیگر → 400
    r = await client.post(
        f"/teacher/assessments/{seed_exam}/start", headers=auth(t1tok)
    )
    assert r.status_code == 200
    foreign_item = (await wrong_answers(by_kind["subject"]))[0]["item_id"]
    r = await client.post(
        f"/teacher/assessments/{seed_exam}/submit",
        headers=auth(t1tok),
        json={"answers": [{"item_id": foreign_item, "option": "A"}]},
    )
    assert r.status_code == 400


# ------------------------- اقدام اصلاحی + idempotency -------------------------


@pytest.mark.anyio
async def test_intervention_and_idempotent_assign(client, seeded):
    dtok = await login(client, "districtadmin")
    teacher2 = await user_id("teacher2")
    teacher1 = await user_id("teacher1")
    year = current_school_year()

    r = await client.post(
        "/district/teacher-qualifications/assign",
        headers=auth(dtok),
        json={"teacher_user_id": teacher2, "subject": "math"},
    )
    assert r.status_code == 200 and r.json()["created"] is True
    first_ids = {e["id"] for e in r.json()["exams"]}

    # تخصیص تکراری → idempotent: همان آزمون‌ها، بدون رویداد جدید
    before = len(await audit_rows("teacher_exam_assigned"))
    r = await client.post(
        "/district/teacher-qualifications/assign",
        headers=auth(dtok),
        json={"teacher_user_id": teacher2, "subject": "math"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["created"] is False
    assert {e["id"] for e in r.json()["exams"]} == first_ids
    assert len(await audit_rows("teacher_exam_assigned")) == before

    # صلاحیتِ در انتظار (seed شده برای teacher1) → اقدام اصلاحی مجاز نیست
    r = await client.get("/district/teacher-qualifications", headers=auth(dtok))
    assert r.status_code == 200, r.text
    quals = r.json()["qualifications"]
    assert len(quals) == 2
    pending = next(q for q in quals if q["teacher_user_id"] == teacher1)
    r = await client.post(
        f"/district/teacher-qualifications/{pending['id']}/interventions",
        headers=auth(dtok),
        json={"type": "training", "notes": "دوره زودهنگام"},
    )
    assert r.status_code == 409

    # نوع نامعتبر → 400
    r = await client.post(
        f"/district/teacher-qualifications/{pending['id']}/interventions",
        headers=auth(dtok),
        json={"type": "magic"},
    )
    assert r.status_code == 400

    # صلاحیت بحرانی را بساز: teacher2 هر دو آزمون را با پاسخ غلط می‌گذارد
    t2tok = await login(client, "teacher2")
    r = await client.get("/teacher/assessments", headers=auth(t2tok))
    for exam in r.json()["exams"]:
        assert (
            await client.post(
                f"/teacher/assessments/{exam['id']}/start", headers=auth(t2tok)
            )
        ).status_code == 200
        r = await client.post(
            f"/teacher/assessments/{exam['id']}/submit",
            headers=auth(t2tok),
            json={"answers": await wrong_answers(exam["id"])},
        )
        assert r.status_code == 200, r.text

    r = await client.get(
        "/district/teacher-qualifications", headers=auth(dtok), params={"status": "critical"}
    )
    assert r.status_code == 200
    critical = next(q for q in r.json()["qualifications"] if q["teacher_user_id"] == teacher2)
    assert critical["subject_percent"] == 0.0
    assert critical["management_percent"] == 0.0
    assert critical["interventions_count"] == 0

    # ثبت اقدام اصلاحی → 200 + رویداد ممیزی
    r = await client.post(
        f"/district/teacher-qualifications/{critical['id']}/interventions",
        headers=auth(dtok),
        json={"type": "replacement", "notes": "جایگزینی موقت تا پایان ترم"},
    )
    assert r.status_code == 200, r.text
    intervention = r.json()["intervention"]
    assert intervention["type"] == "replacement"
    assert intervention["status"] == "proposed"
    assert intervention["closed_at"] is None
    created = await audit_rows("teacher_intervention_created", contains=f"teacher={teacher2}")
    assert len(created) == 1

    # وضعیت نامعتبر → 400؛ سپس بسته‌شدن نرم با closed_at
    iid = intervention["id"]
    r = await client.post(
        f"/district/teacher-qualifications/{critical['id']}/interventions/{iid}/status",
        headers=auth(dtok),
        json={"status": "archived"},
    )
    assert r.status_code == 400
    r = await client.post(
        f"/district/teacher-qualifications/{critical['id']}/interventions/{iid}/status",
        headers=auth(dtok),
        json={"status": "done"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["intervention"]["status"] == "done"
    assert r.json()["intervention"]["closed_at"] is not None

    # اقدامِ متعلق به رکورد دیگر → 404
    r = await client.post(
        f"/district/teacher-qualifications/{pending['id']}/interventions/{iid}/status",
        headers=auth(dtok),
        json={"status": "done"},
    )
    assert r.status_code == 404
    # رکورد ناحیه دیگر / ناموجود → 404
    await make_other_district_admin()
    otok = await login(client, "districtadmin2")
    r = await client.get(
        f"/district/teacher-qualifications/{critical['id']}", headers=auth(otok)
    )
    assert r.status_code == 404
    r = await client.get("/district/teacher-qualifications/99999", headers=auth(dtok))
    assert r.status_code == 404

    # جزئیات رکورد: آزمون‌ها + تلاش‌ها + اقدام‌ها
    r = await client.get(
        f"/district/teacher-qualifications/{critical['id']}", headers=auth(dtok)
    )
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["qualification"]["status"] == "critical"
    assert len(detail["exams"]) == 2
    assert all(e["percent"] == 0.0 for e in detail["exams"])
    assert len(detail["attempts"]) == 2
    assert all(a["status"] == "graded" for a in detail["attempts"])
    assert len(detail["interventions"]) == 1


# ------------------------- فهرست و فیلترهای ناحیه -------------------------


@pytest.mark.anyio
async def test_district_teachers_and_qualification_filters(client, seeded):
    dtok = await login(client, "districtadmin")
    teacher2 = await user_id("teacher2")
    year = current_school_year()

    # فهرست معلمان ناحیه (برای انتخاب‌گر پنل)
    r = await client.get("/district/teachers", headers=auth(dtok))
    assert r.status_code == 200, r.text
    teachers = r.json()["teachers"]
    rows = {(t["user_id"], t["subject"]): t for t in teachers}
    assert (await user_id("teacher1"), "math") in rows
    t1_row = rows[(await user_id("teacher1"), "math")]
    assert t1_row["school_name"] == "دبیرستان نمونه دانشیار"
    assert t1_row["qualification_status_current_year"] == "pending"  # از seed
    assert t1_row["full_name"] == "آقای احمدی"

    r = await client.post(
        "/district/teacher-qualifications/assign",
        headers=auth(dtok),
        json={"teacher_user_id": teacher2, "subject": "math"},
    )
    assert r.status_code == 200 and r.json()["created"] is True

    # فهرست رکوردها + فیلترها
    r = await client.get("/district/teacher-qualifications", headers=auth(dtok))
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 2

    r = await client.get(
        "/district/teacher-qualifications",
        headers=auth(dtok),
        params={"status": "pending", "subject": "math", "school_year": year, "school_id": 1},
    )
    assert r.json()["total"] == 2
    r = await client.get(
        "/district/teacher-qualifications", headers=auth(dtok), params={"status": "qualified"}
    )
    assert r.json()["total"] == 0
    r = await client.get(
        "/district/teacher-qualifications", headers=auth(dtok), params={"school_year": "1390-1391"}
    )
    assert r.json()["total"] == 0

    # نمای معلمِ تازه‌تخصیص‌یافته: درصدها هنوز null و وضعیت pending
    r = await client.get("/district/teacher-qualifications", headers=auth(dtok))
    mine = next(q for q in r.json()["qualifications"] if q["teacher_user_id"] == teacher2)
    assert mine["status"] == "pending"
    assert mine["subject_percent"] is None
    assert mine["management_percent"] is None
    assert mine["subject_fa"] == "ریاضی"
    assert mine["school_year"] == year
