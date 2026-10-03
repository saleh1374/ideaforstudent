"""گزارش‌های پنل والدین (سند پنل والدین §3 نمرات آزمون، §6 برنامه، §13 هشدارها،
§14 گزارش هفتگی).

اصل حفظ حریم خصوصی در همه‌ی این تست‌ها تکرار می‌شود: فقط فرزندِ متصل‌شده از
طریق ParentLink دیده می‌شود و هیچ پاسخی رتبه/مقایسه با دیگران ندارد."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_parentreports.db")

from datetime import date, datetime, time, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.core.db import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.assessment import AttemptAnswer, Exam, ExamAttempt, ExamItem
from app.models.catalog import Topic
from app.models.org import User
from app.models.parent_panel import ParentMeeting, SchoolAttendance
from app.models.rbac import AuditLog
from app.models.slm import ErrorRecord, Evidence, PlanTask, StudentTopicState
from app.services.assessment import grade_answers
from app.services.parent_reports import week_bounds
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


async def user_id(db, username: str) -> int:
    return (await db.execute(select(User.id).where(User.username == username))).scalar_one()


async def child_id(client, token) -> int:
    r = await client.get("/parent/children", headers=auth(token))
    assert r.status_code == 200, r.text
    children = r.json()["children"]
    assert children, "والدِ تست باید دست‌کم یک فرزند متصل داشته باشد"
    return children[0]["id"]


async def clean_student(db, *user_ids: int) -> None:
    """داده‌های آموزشیِ دانش‌آموز را پاک می‌کند تا هر تست داده‌ی قطعیِ خودش را بسازد."""
    for uid in user_ids:
        await db.execute(delete(AttemptAnswer).where(AttemptAnswer.student_user_id == uid))
        await db.execute(delete(ExamAttempt).where(ExamAttempt.student_user_id == uid))
        await db.execute(delete(ErrorRecord).where(ErrorRecord.student_user_id == uid))
        await db.execute(delete(Evidence).where(Evidence.student_user_id == uid))
        await db.execute(delete(PlanTask).where(PlanTask.student_user_id == uid))
        await db.execute(delete(StudentTopicState).where(StudentTopicState.student_user_id == uid))
    await db.commit()


async def first_exam(db, negative_k: float | None = None) -> Exam:
    exam = (await db.execute(select(Exam).where(Exam.status == "published").order_by(Exam.id))).scalars().first()
    assert exam is not None, "seed باید یک آزمون منتشرشده داشته باشد"
    if negative_k is not None:
        exam.negative_marking_k = negative_k
        db.add(exam)
        await db.commit()
    return exam


async def make_attempt(
    db,
    *,
    student_id: int,
    exam: Exam,
    picks: dict[int, str | None],
    percent: float | None = None,
    minutes_ago: int = 60,
    submitted_at: datetime | None = None,
    cause: str = "conceptual",
) -> ExamAttempt:
    """ساخت یک تلاش آزمونِ نمره‌گرفته؛ picks بر اساس «ترتیب سؤال» است:
    "correct" | "wrong" | None (نزده)."""
    items = (
        (
            await db.execute(
                select(ExamItem)
                .options(selectinload(ExamItem.item))
                .where(ExamItem.exam_id == exam.id)
                .order_by(ExamItem.order)
            )
        )
        .scalars()
        .all()
    )
    when = submitted_at or (datetime.utcnow() - timedelta(minutes=minutes_ago))
    attempt = ExamAttempt(
        exam_id=exam.id,
        student_user_id=student_id,
        status="graded",
        started_at=when - timedelta(minutes=5),
        submitted_at=when,
    )
    db.add(attempt)
    await db.flush()

    grading = []
    for ei in items:
        choice = picks.get(ei.order, "correct")
        if choice == "correct":
            selected = ei.item.correct_option
        elif choice == "wrong":
            selected = next(o for o in ei.item.options if o != ei.item.correct_option)
        else:
            selected = None
        is_correct = 1 if (selected is not None and selected == ei.item.correct_option) else 0
        db.add(
            AttemptAnswer(
                attempt_id=attempt.id,
                exam_item_id=ei.id,
                student_user_id=student_id,
                selected_option=selected,
                is_correct=is_correct,
                time_spent_ms=15_000,
                question_position=ei.order,
                school_id=1,
                class_id=1,
                district_id=1,
                province_id=1,
                error_cause=None if is_correct else cause,
            )
        )
        grading.append({"correct": bool(is_correct), "points": ei.points, "answered": selected is not None})

    result = grade_answers(grading, exam.negative_marking_k or 0.0)
    attempt.raw_score = result["raw_score"]
    attempt.percent = result["percent"] if percent is None else percent
    await db.commit()
    await db.refresh(attempt)
    return attempt


# ------------------------- §3 گزارش نمرات آزمون‌ها -------------------------


@pytest.mark.anyio
async def test_exam_results_shape_trend_and_privacy(client, seeded):
    ptok = await login(client, "parent1")
    sid = await child_id(client, ptok)

    # بدون هیچ تلاشی: ساختار کامل ولی لیست خالی
    r = await client.get(f"/parent/children/{sid}/exam-results", headers=auth(ptok))
    assert r.status_code == 200, r.text
    empty = r.json()
    assert empty["exams"] == [] and empty["trend"] == []
    assert empty["summary"]["count"] == 0
    assert empty["note_fa"]

    async with AsyncSessionLocal() as db:
        s1 = await user_id(db, "student1")
        s2 = await user_id(db, "student2")
        await clean_student(db, s1, s2)
        exam = await first_exam(db, negative_k=0.25)

        # ۳ پاسخ درست + ۱ غلط ⇒ نمره‌ی منفیِ ۰٫۲۵ اعمال می‌شود
        a1 = await make_attempt(
            db, student_id=s1, exam=exam,
            picks={1: "correct", 2: "correct", 3: "correct", 4: "wrong"}, minutes_ago=120,
        )
        a2 = await make_attempt(
            db, student_id=s1, exam=exam,
            picks={1: "correct", 2: "correct", 3: "correct", 4: "correct"}, minutes_ago=60,
        )
        # تلاش دانش‌آموزِ بدون پیوند والد نباید وارد گزارش فرزند شود
        await make_attempt(db, student_id=s2, exam=exam, picks={1: "correct"}, minutes_ago=30)

    assert a1.percent == pytest.approx(68.75)
    assert a2.percent == 100.0

    r = await client.get(f"/parent/children/{sid}/exam-results", headers=auth(ptok))
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["student_id"] == sid
    assert len(body["exams"]) == 2  # فقط تلاش‌های فرزندِ متصل‌شده
    first, second = body["exams"]

    assert first["attempt_id"] == a1.id
    assert first["correct"] == 3 and first["wrong"] == 1 and first["blank"] == 0 and first["total"] == 4
    assert first["score"] == pytest.approx(6.88, abs=0.01)
    assert first["percent"] == pytest.approx(68.75)
    assert first["negative_marking"]["enabled"] is True
    assert first["negative_marking"]["k"] == 0.25
    assert first["negative_marking"]["points_lost"] > 0
    assert first["time_spent_seconds"] == pytest.approx(60.0)
    assert first["delta"] is None
    assert first["submitted_at"] and first["started_at"]

    assert second["delta"] == pytest.approx(31.25)
    assert second["correct"] == 4 and second["wrong"] == 0
    assert second["negative_marking"]["points_lost"] == 0

    assert body["trend"] == [pytest.approx(68.75), pytest.approx(100.0)]
    assert body["summary"]["count"] == 2
    assert body["summary"]["best_percent"] == 100.0
    assert body["summary"]["latest_percent"] == 100.0
    assert body["summary"]["negative_marking_exams"] == 1
    assert body["note_fa"]

    # اصل حریم خصوصی: بدون رتبه و بدون مقایسه با دیگران
    text = r.text
    assert '"rank"' not in text and '"peers"' not in text and '"class_avg"' not in text

    # دانش‌آموزِ بدون پیوند والد ⇐ 403
    r = await client.get(f"/parent/children/{s2}/exam-results", headers=auth(ptok))
    assert r.status_code == 403
    stok = await login(client, "student1")
    r = await client.get(f"/parent/children/{sid}/exam-results", headers=auth(stok))
    assert r.status_code == 403


@pytest.mark.anyio
async def test_exam_result_detail_topics_and_errors(client, seeded):
    ptok = await login(client, "parent1")
    sid = await child_id(client, ptok)

    async with AsyncSessionLocal() as db:
        s1 = await user_id(db, "student1")
        s2 = await user_id(db, "student2")
        await clean_student(db, s1, s2)
        exam = await first_exam(db)
        attempt = await make_attempt(
            db, student_id=s1, exam=exam, picks={1: "correct", 2: "correct", 3: "wrong", 4: None}
        )
        foreign = await make_attempt(db, student_id=s2, exam=exam, picks={1: "correct"}, minutes_ago=10)
        attempt_id, foreign_id = attempt.id, foreign.id

    r = await client.get(f"/parent/children/{sid}/exam-results/{attempt_id}", headers=auth(ptok))
    assert r.status_code == 200, r.text
    detail = r.json()

    assert detail["attempt_id"] == attempt_id
    assert detail["exam"]["title"]
    assert detail["correct"] == 2 and detail["wrong"] == 1 and detail["blank"] == 1
    assert detail["total"] == 4
    assert detail["negative_marking"]["enabled"] is False

    # دو مبحث در این آزمون؛ مبحثِ دارای خطا درصد پایین‌تری دارد
    assert len(detail["topics"]) == 2
    assert {t["topic"] for t in detail["topics"]} == {"مجموعه‌ها و عملیات", "تعداد زیرمجموعه‌ها"}
    bad_topic = [t for t in detail["topics"] if t["wrong"] == 1][0]
    assert bad_topic["percent"] == 50.0

    assert detail["error_causes"][0]["cause"] == "conceptual"
    assert detail["error_causes"][0]["cause_fa"] == "مفهومی"
    assert detail["error_causes"][0]["count"] == 1

    assert len(detail["wrong_items"]) == 1
    assert detail["wrong_items"][0]["body"]
    assert detail["wrong_items"][0]["selected"] != detail["wrong_items"][0]["correct"]
    assert detail["note_fa"]

    # شناسه‌ی ناموجود یا تلاشِ فرزندِ دیگر ⇐ 404
    r = await client.get(f"/parent/children/{sid}/exam-results/999999", headers=auth(ptok))
    assert r.status_code == 404
    r = await client.get(f"/parent/children/{sid}/exam-results/{foreign_id}", headers=auth(ptok))
    assert r.status_code == 404

    # بدون پیوند والد ⇐ 403
    stok = await login(client, "student1")
    r = await client.get(f"/parent/children/{sid}/exam-results/{attempt_id}", headers=auth(stok))
    assert r.status_code == 403


# ------------------------- §6/§8 برنامه و تکالیف -------------------------


@pytest.mark.anyio
async def test_plan_view_deadlines_and_next_exam(client, seeded):
    ptok = await login(client, "parent1")
    sid = await child_id(client, ptok)
    today = date.today()

    async with AsyncSessionLocal() as db:
        s1 = await user_id(db, "student1")
        await clean_student(db, s1)
        db.add_all(
            [
                PlanTask(student_user_id=s1, task_type="spaced_review", payload={}, for_date=today - timedelta(days=2), priority=3.0, status="pending"),
                PlanTask(student_user_id=s1, task_type="lesson", payload={}, for_date=today, priority=2.0, status="pending"),
                PlanTask(student_user_id=s1, task_type="practice", payload={}, for_date=today - timedelta(days=3), priority=1.0, status="done"),
                PlanTask(student_user_id=s1, task_type="quiz", payload={}, for_date=today + timedelta(days=2), priority=1.5, status="pending"),
            ]
        )
        await db.commit()

    r = await client.get(f"/parent/children/{sid}/plan", headers=auth(ptok))
    assert r.status_code == 200, r.text
    body = r.json()

    summary = body["summary"]
    assert summary["total"] == 4
    assert summary["done"] == 1 and summary["pending"] == 3
    assert summary["due_today"] == 1 and summary["overdue"] == 1
    assert summary["progress_pct"] == 25.0

    # کارِ عقب‌افتاده اول لیست است و برچسب دقیق دارد
    assert body["tasks"][0]["overdue"] is True
    assert body["tasks"][0]["for_date"] == (today - timedelta(days=2)).isoformat()
    assert [t["status"] for t in body["tasks"]][-1] == "done"

    # بازه‌ی آزمون پیش رو (آزمون seed تا ۶ روز دیگر باز است)
    assert body["next_exam"] is not None
    assert body["next_exam"]["days_left"] >= 1
    assert body["next_exam"]["is_open"] is True
    assert body["upcoming_exams"]

    # فقط‌خواندنی بودن صریحاً اعلام می‌شود (سند §6)
    assert "فقط‌خواندنی" in body["note_fa"]

    # حریم خصوصی
    r = await client.get("/parent/children/6/plan", headers=auth(ptok))
    assert r.status_code == 403
    stok = await login(client, "student1")
    r = await client.get(f"/parent/children/{sid}/plan", headers=auth(stok))
    assert r.status_code == 403


# ------------------------- §13 هشدارهای هوشمند -------------------------


@pytest.mark.anyio
async def test_alerts_are_rule_based_and_child_only(client, seeded):
    ptok = await login(client, "parent1")
    sid = await child_id(client, ptok)
    today = date.today()

    async with AsyncSessionLocal() as db:
        s1 = await user_id(db, "student1")
        await clean_student(db, s1)
        topics = (await db.execute(select(Topic).order_by(Topic.id))).scalars().all()
        t1, t2 = topics[0], topics[1]

        # ۱) برنامه: ۱ انجام‌شده + ۳ معوق ⇒ شکاف پیشرفت/تسط + کار عقب‌افتاده
        db.add_all(
            [
                PlanTask(student_user_id=s1, task_type="lesson", payload={}, for_date=today - timedelta(days=3), priority=2.0, status="done"),
                PlanTask(student_user_id=s1, task_type="practice", payload={}, for_date=today - timedelta(days=2), priority=3.0, status="pending"),
                PlanTask(student_user_id=s1, task_type="quiz", payload={}, for_date=today, priority=2.0, status="pending"),
                PlanTask(student_user_id=s1, task_type="spaced_review", payload={}, for_date=today + timedelta(days=1), priority=1.0, status="pending"),
            ]
        )
        # ۲) وضعیت مباحث: یکی بحرانی (خطر) و یکی با افت ماندگاری
        db.add_all(
            [
                StudentTopicState(
                    student_user_id=s1, topic_id=t1.id, mastery=40.0, retention=0.4, stability=3.0,
                    effective_mastery=30.0, evidence_count=5, errors_by_cause={}, history=[],
                ),
                StudentTopicState(
                    student_user_id=s1, topic_id=t2.id, mastery=80.0, retention=0.3, stability=4.0,
                    effective_mastery=70.0, evidence_count=5, errors_by_cause={}, history=[],
                ),
            ]
        )
        # ۳) دو خطای بازِ تکراری روی یک مبحث با یک علت
        for _ in range(2):
            db.add(
                ErrorRecord(
                    student_user_id=s1,
                    attempt_answer_id=0,
                    topic_id=t1.id,
                    cause="conceptual",
                    item_snapshot={"body": "…", "correct": "A"},
                    status="open",
                    created_at=datetime.utcnow(),
                )
            )
        await db.commit()

        exam = await first_exam(db)
        # ۴) آخرین نمره زیر آستانه ولی بهبودِ اندک نسبت به آزمون قبلی
        await make_attempt(
            db, student_id=s1, exam=exam,
            picks={1: "correct", 2: "wrong", 3: "wrong", 4: "wrong"},
            percent=25.0, minutes_ago=180,
        )
        await make_attempt(
            db, student_id=s1, exam=exam,
            picks={1: "correct", 2: "wrong", 3: "wrong", 4: "wrong"},
            percent=30.0, minutes_ago=60,
        )

    r = await client.get(f"/parent/children/{sid}/alerts", headers=auth(ptok))
    assert r.status_code == 200, r.text
    body = r.json()

    alerts = body["alerts"]
    assert 0 < len(alerts) <= 12
    codes = {a["code"] for a in alerts}
    assert {
        "no_activity",       # بدون شاهد یادگیری
        "progress_gap",      # شکاف پیشرفت ↔ تسط
        "overdue_tasks",     # کار عقب‌افتاده
        "repeated_error",    # خطای تکراری حل‌نشده
        "low_score",         # نمره زیر آستانه
        "improvement",       # بهبود اخیر (اطلاع‌رسانی مثبت)
        "weak_topic",        # مبحث نیازمند توجه
        "retention_drop",    # افت ماندگاری
    } <= codes

    # هر هشدار: عنوان + شدت معتبر + توضیح یک‌خطی + اقدام پیشنهادی
    for a in alerts:
        assert a["severity"] in ("info", "warning", "danger")
        assert a["title"] and a["message"] and a["action"]
        assert a["code"]

    # خطرناک‌ترین هشدارها اول می‌آیند
    assert alerts[0]["severity"] == "danger"
    assert body["counts"]["danger"] >= 1
    assert body["counts"]["total"] == len(alerts)
    assert body["thresholds"]["gap_units"] == 15.0
    assert body["note_fa"]

    # هیچ رتبه یا مقایسه‌ای در پاسخ نیست
    text = r.text
    assert '"rank"' not in text and '"peers"' not in text and '"class_avg"' not in text

    # حریم خصوصی: دانش‌آموزِ بدون پیوند یا خودِ دانش‌آموز ⇒ 403
    r = await client.get("/parent/children/6/alerts", headers=auth(ptok))
    assert r.status_code == 403
    stok = await login(client, "student1")
    r = await client.get(f"/parent/children/{sid}/alerts", headers=auth(stok))
    assert r.status_code == 403


# ------------------------- §14 گزارش هفتگی -------------------------


@pytest.mark.anyio
async def test_weekly_report_cache_idempotent_and_audited(client, seeded):
    ptok = await login(client, "parent1")
    sid = await child_id(client, ptok)
    today = date.today()
    window_start = datetime.combine(week_bounds(today)[0], time.min) + timedelta(minutes=30)

    async with AsyncSessionLocal() as db:
        s1 = await user_id(db, "student1")
        await clean_student(db, s1)
        db.add_all(
            [
                PlanTask(student_user_id=s1, task_type="lesson", payload={}, for_date=today, priority=2.0, status="done"),
                PlanTask(student_user_id=s1, task_type="practice", payload={}, for_date=today + timedelta(days=1), priority=1.0, status="pending"),
            ]
        )
        await db.commit()
        exam = await first_exam(db)
        await make_attempt(
            db,
            student_id=s1,
            exam=exam,
            picks={1: "correct", 2: "correct", 3: "wrong", 4: "correct"},
            percent=80.0,
            submitted_at=max(datetime.utcnow(), window_start),
        )

    # ساخت اولین گزارش
    r1 = await client.get(f"/parent/children/{sid}/weekly-report", headers=auth(ptok))
    assert r1.status_code == 200, r1.text
    first = r1.json()
    assert first["cached"] is False
    assert first["generated_at"] and first["week_start"] and first["week_end"]
    assert first["plan"]["total"] == 2 and first["plan"]["week_done"] == 1
    assert first["plan"]["progress_pct"] == 50.0
    assert first["exams"]["count"] == 1
    assert first["exams"]["avg_percent"] == 80.0
    assert first["activity"]["questions_answered"] == 4
    assert first["errors"]["open"] == 0
    assert isinstance(first["alerts"], list)
    assert first["actions"] and all(isinstance(a, str) and a for a in first["actions"])
    assert first["note_fa"]

    # درخواست دوم ⇒ همان گزارشِ کش‌شده، بدون بازسازی
    r2 = await client.get(f"/parent/children/{sid}/weekly-report", headers=auth(ptok))
    assert r2.status_code == 200, r2.text
    second = r2.json()
    assert second["cached"] is True
    assert second["generated_at"] == first["generated_at"]

    # تازه‌سازی صریح ⇒ بازسازی با همان ساختار (idempotent) و ثبت ممیزی
    r3 = await client.get(f"/parent/children/{sid}/weekly-report?refresh=true", headers=auth(ptok))
    assert r3.status_code == 200, r3.text
    third = r3.json()
    assert third["cached"] is False
    assert third["generated_at"] >= first["generated_at"]
    assert third["plan"] == first["plan"]
    assert third["exams"] == first["exams"]
    assert third["mastery"] == first["mastery"]

    async with AsyncSessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(AuditLog).where(AuditLog.action == "weekly_report_generated")
                )
            )
            .scalars()
            .all()
        )
        # ساخت + تازه‌سازی (درخواستِ کش‌شده رویدادی ثبت نمی‌کند)
        assert len(rows) == 2
        assert all(row.entity_id == sid for row in rows)

    # حریم خصوصی: بدون پیوند یا توسط خودِ دانش‌آموز ⇒ 403
    r = await client.get("/parent/children/6/weekly-report", headers=auth(ptok))
    assert r.status_code == 403
    stok = await login(client, "student1")
    r = await client.get(f"/parent/children/{sid}/weekly-report", headers=auth(stok))
    assert r.status_code == 403


# ------------------------- §2 وضعیت یادگیری به تفکیک درس -------------------------


@pytest.mark.anyio
async def test_subject_status_per_subject_with_trend_and_strengths(client, seeded):
    """§2: هر درس با روند + مباحث نیازمند توجه/تثبیت‌شده + آخرین ارزیابی +
    نقاط قوت — تا سطح مبحث قابل پیمایش است و همه متن‌ها فارسی."""
    ptok = await login(client, "parent1")
    sid = await child_id(client, ptok)

    r = await client.get(f"/parent/children/{sid}/subjects", headers=auth(ptok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["student_id"] == sid
    assert body["subjects"], "دانش‌آموز seed باید دست‌کم یک درس داشته باشد"

    for subj in body["subjects"]:
        for key in (
            "subject",
            "current_mastery",
            "status",
            "status_fa",
            "trend",
            "trend_delta",
            "trend_fa",
            "topics_count",
            "attention_count",
            "consolidated_count",
            "last_assessed_at",
            "topics",
        ):
            assert key in subj, key
        assert subj["trend"] in ("up", "down", "flat", "none")
        assert subj["status"] in ("mastered", "consolidating", "weak", "unknown")
        for t in subj["topics"]:
            for key in (
                "topic_id",
                "title",
                "mastery",
                "status",
                "status_fa",
                "needs_attention",
                "trend",
                "suggestion_fa",
            ):
                assert key in t, key
            assert t["status_fa"] and t["suggestion_fa"]
            if t["needs_attention"]:
                assert t["trend"] in ("up", "down", "flat", "none")

    # مرتب‌سازی: درس دارای مبحث نیازمند توجه اول است
    counts = [s["attention_count"] for s in body["subjects"]]
    assert counts == sorted(counts, reverse=True)

    assert isinstance(body["strengths"], list)
    assert isinstance(body["attention_subjects"], list)
    assert body["thresholds"]["mastered"] == 85.0
    assert body["note_fa"]

    # حریم خصوصی: بدون پیوند ⇐ 403
    r = await client.get("/parent/children/6/subjects", headers=auth(ptok))
    assert r.status_code == 403
    stok = await login(client, "student1")
    r = await client.get(f"/parent/children/{sid}/subjects", headers=auth(stok))
    assert r.status_code == 403


# ------------------------- §4 سه نوع مقایسه -------------------------


@pytest.mark.anyio
async def test_three_comparisons_class_gated_by_min_group(client, seeded):
    """§4: «نسبت به خودش» + «نسبت به هدف دوره» همیشه؛ «نسبت به کالس» فقط با
    رعایت حداقل جمعیت ۱۰ — کالس seed کمتر از ۱۰ نفر ⇒ سرکوب."""
    ptok = await login(client, "parent1")
    sid = await child_id(client, ptok)

    r = await client.get(f"/parent/children/{sid}/comparisons", headers=auth(ptok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["min_group"] == 10
    assert body["class_comparison_allowed"] is True
    assert body["comparisons"]

    for row in body["comparisons"]:
        assert {"subject", "self", "period_goal", "class"} <= set(row)
        assert {"previous", "current", "delta"} <= set(row["self"])
        assert row["self"]["note_fa"]
        assert row["period_goal"]["goal"] == 70.0
        assert {"goal", "current", "gap"} <= set(row["period_goal"])
        cls = row["class"]
        assert {"allowed", "class_avg", "student", "gap", "suppressed"} <= set(cls)
        # کالسِ فرزندِ seed ۳ نفره ⇒ زیر حداقل جمعیت
        assert cls["class_avg"] is None and cls["suppressed"] is True
        assert cls["reason_fa"] and "حداقل جمعیت" in cls["reason_fa"]

    assert body["note_fa"] and "سه نوع مقایسه" in body["note_fa"]

    # حریم خصوصی
    r = await client.get("/parent/children/6/comparisons", headers=auth(ptok))
    assert r.status_code == 403


# ------------------------- §9 حضور و جلسات -------------------------


@pytest.mark.anyio
async def test_attendance_and_sessions_sections(client, seeded):
    """§9: حضور مدرسه + جلسات گذشته/آینده با موضوع، گزارش و تکلیف."""
    ptok = await login(client, "parent1")
    sid = await child_id(client, ptok)
    today = date.today()

    async with AsyncSessionLocal() as db:
        s1 = await user_id(db, "student1")
        tutor = await user_id(db, "tutor1")
        db.add_all(
            [
                SchoolAttendance(student_user_id=s1, on_date=today - timedelta(days=1), status="present"),
                SchoolAttendance(student_user_id=s1, on_date=today - timedelta(days=2), status="absent", note="بیماری"),
                SchoolAttendance(student_user_id=s1, on_date=today - timedelta(days=3), status="late"),
                ParentMeeting(
                    student_user_id=s1,
                    tutor_user_id=tutor,
                    kind="private_session",
                    subject="math",
                    topic_fa="معادلات درجه دوم",
                    scheduled_at=datetime.utcnow() - timedelta(days=2),
                    status="held",
                    report_fa="مرور خوب؛ حل مسئله چندمرحله‌ای نیاز به تمرین دارد",
                    task_fa="۵ سؤال تمرین",
                    task_status="pending",
                ),
                ParentMeeting(
                    student_user_id=s1,
                    tutor_user_id=tutor,
                    kind="private_session",
                    subject="math",
                    topic_fa="پیش‌نیاز جبر",
                    scheduled_at=datetime.utcnow() + timedelta(days=3),
                    status="scheduled",
                ),
                ParentMeeting(
                    student_user_id=s1,
                    kind="parent_meeting",
                    topic_fa="جلسه با معلم کلاس",
                    scheduled_at=datetime.utcnow() - timedelta(days=10),
                    status="missed",
                ),
            ]
        )
        await db.commit()

    r = await client.get(f"/parent/children/{sid}/attendance", headers=auth(ptok))
    assert r.status_code == 200, r.text
    body = r.json()

    att = body["attendance"]
    assert att["days"] == 3
    assert att["counts"] == {"present": 1, "absent": 1, "late": 1}
    assert att["absent"] == 1 and att["late"] == 1
    assert att["rate_pct"] == pytest.approx(66.7, abs=0.1)
    assert {row["status_fa"] for row in att["rows"]} == {"حاضر", "غایب", "تاخیر"}

    sess = body["sessions"]
    assert sess["total"] == 3
    assert len(sess["past"]) == 2 and len(sess["upcoming"]) == 1
    assert len(sess["missed"]) == 1 and len(sess["pending_tasks"]) == 1
    held = next(m for m in sess["past"] if m["status"] == "held")
    assert held["topic_fa"] == "معادلات درجه دوم"
    assert held["report_fa"] and held["task_fa"]
    assert held["task_status_fa"] == "در انتظار"
    assert held["tutor_name"]
    assert held["kind_fa"] == "جلسه معلم خصوصی"
    upcoming = sess["upcoming"][0]
    assert upcoming["status_fa"] == "برنامه‌ریزی‌شده"
    assert sess["missed"][0]["status_fa"] == "ازدست‌رفته"
    assert body["note_fa"]

    # حریم خصوصی
    r = await client.get("/parent/children/6/attendance", headers=auth(ptok))
    assert r.status_code == 403


# ------------------------- §15 دستیار هوشمند والد -------------------------


@pytest.mark.anyio
async def test_parent_assistant_is_rule_based_and_child_scoped(client, seeded):
    """§15: پاسخ فقط از داده‌ی واقعی همین فرزند + ثبت ممیزی + بدون قضاوت
    شخصیتی + پرسش خالی/بلند → 400."""
    ptok = await login(client, "parent1")
    sid = await child_id(client, ptok)
    today = date.today()

    async with AsyncSessionLocal() as db:
        s1 = await user_id(db, "student1")
        await clean_student(db, s1)
        topics = (await db.execute(select(Topic).order_by(Topic.id))).scalars().all()
        t1 = topics[0]
        db.add(
            StudentTopicState(
                student_user_id=s1, topic_id=t1.id, mastery=40.0, retention=0.5, stability=3.0,
                effective_mastery=35.0, evidence_count=5, errors_by_cause={},
                history=[
                    {"at": (datetime.utcnow() - timedelta(days=10)).isoformat(), "m": 60.0},
                    {"at": datetime.utcnow().isoformat(), "m": 40.0},
                ],
            )
        )
        for _ in range(2):
            db.add(
                ErrorRecord(
                    student_user_id=s1,
                    attempt_answer_id=0,
                    topic_id=t1.id,
                    cause="conceptual",
                    item_snapshot={"body": "…", "correct": "A"},
                    status="open",
                    created_at=datetime.utcnow(),
                )
            )
        await db.commit()

    before = None
    async with AsyncSessionLocal() as db:
        before = (
            await db.execute(select(AuditLog).where(AuditLog.action == "parent_copilot_query"))
        ).scalars().all()

    r = await client.post(
        f"/parent/children/{sid}/assistant", headers=auth(ptok),
        json={"question": "چرا ریاضی محمد افت کرده است؟"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"] and body["answer_fa"]
    assert body["intent"] == "drop"
    assert body["question"]
    # پاسخ از داده‌ی واقعی است: همان مبحث ضعیف و خطای مفهومی
    assert t1.title_fa in body["answer"] or body["references"]["weak_topics"]
    assert body["references"]["weak_topics"]
    assert body["references"]["weak_topics"][0]["topic_id"] == t1.id
    assert body["note_fa"] and "شخصیت" in body["note_fa"]

    # قضاوت شخصیتی هرگز
    for banned in ("تنبل", "بی‌استعداد", "ضعیف‌الهوش"):
        assert banned not in body["answer"]
    # هیچ داده‌ای از دیگران
    assert "student2" not in body["answer"]

    # پرسش خالی → 400
    r = await client.post(
        f"/parent/children/{sid}/assistant", headers=auth(ptok), json={"question": "   "}
    )
    assert r.status_code == 400

    # ممیزی ثبت شده است
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(AuditLog).where(AuditLog.action == "parent_copilot_query")
            )
        ).scalars().all()
        assert len(rows) == len(before) + 1
        assert rows[-1].entity_id == sid
        assert rows[-1].actor_user_id == await user_id(db, "parent1")

    # حریم خصوصی: بدون پیوند ⇐ 403
    r = await client.post(
        "/parent/children/6/assistant", headers=auth(ptok), json={"question": "چطور است؟"}
    )
    assert r.status_code == 403


# ------------------------- §17 مجوزهای هر پیوند والد–فرزند -------------------------


@pytest.mark.anyio
async def test_per_link_permissions_gate_sections(client, seeded):
    """§17: هر پیوند والد–فرزند مجوز مستقل دارد؛ نبودِ ردیف = دسترسی کامل و
    مقدار false بخشِ مربوطه را برای همان فرزند می‌بندد."""
    ptok = await login(client, "parent1")
    sid = await child_id(client, ptok)

    # پیش‌فرض: همه کلیدها مجاز‌اند
    r = await client.get("/parent/links", headers=auth(ptok))
    assert r.status_code == 200, r.text
    links = r.json()["links"]
    assert len(links) == 1
    link = links[0]
    assert link["student_user_id"] == sid
    assert all(link["permissions"].values())
    assert link["overridden_keys"] == []
    assert "class_comparison" in r.json()["permission_keys"]

    # قبل از محدودسازی، بخش‌ها بازند
    assert (
        await client.get(f"/parent/children/{sid}/comparisons", headers=auth(ptok))
    ).status_code == 200
    assert (
        await client.get(f"/parent/children/{sid}/attendance", headers=auth(ptok))
    ).status_code == 200

    # کلید نامعتبر → 400
    r = await client.patch(
        f"/parent/links/{link['link_id']}/permissions", headers=auth(ptok),
        json={"permissions": {"nope": False}},
    )
    assert r.status_code == 400

    # محدودسازی دو مجوز
    r = await client.patch(
        f"/parent/links/{link['link_id']}/permissions", headers=auth(ptok),
        json={"permissions": {"class_comparison": False, "assistant": False}},
    )
    assert r.status_code == 200, r.text
    perms = r.json()["permissions"]
    assert perms["class_comparison"] is False and perms["assistant"] is False
    assert perms["attendance"] is True

    # مقایسه: کلاسِ مجازِ پیوند بسته شده است
    r = await client.get(f"/parent/children/{sid}/comparisons", headers=auth(ptok))
    assert r.status_code == 200
    assert r.json()["class_comparison_allowed"] is False
    for row in r.json()["comparisons"]:
        assert row["class"]["class_avg"] is None
        assert "مجاز نیست" in row["class"]["reason_fa"]

    # دستیار: بسته ⇒ 403
    r = await client.post(
        f"/parent/children/{sid}/assistant", headers=auth(ptok), json={"question": "سلام"}
    )
    assert r.status_code == 403

    # بخش‌های دیگر همچنان باز
    assert (
        await client.get(f"/parent/children/{sid}/attendance", headers=auth(ptok))
    ).status_code == 200
    assert (
        await client.get(f"/parent/children/{sid}/exam-results", headers=auth(ptok))
    ).status_code == 200

    # بازگرداندن مجوز
    r = await client.patch(
        f"/parent/links/{link['link_id']}/permissions", headers=auth(ptok),
        json={"permissions": {"assistant": True}},
    )
    assert r.json()["permissions"]["assistant"] is True
    r = await client.post(
        f"/parent/children/{sid}/assistant", headers=auth(ptok), json={"question": "سلام"}
    )
    assert r.status_code == 200

    # رویداد ممیزی
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(AuditLog).where(AuditLog.action == "parent_link_permission_updated")
            )
        ).scalars().all()
        assert len(rows) == 2
        assert rows[0].entity_id == link["link_id"]

    # پیوند دیگران ⇐ 404
    r = await client.get("/parent/links", headers=auth(await login(client, "student1")))
    assert r.status_code == 200 and r.json()["links"] == []


# ------------------------- §11/§12 معلم خصوصی از دید والد -------------------------


@pytest.mark.anyio
async def test_parent_tutor_market_and_satisfaction(client, seeded):
    """§11 بازار معلم‌ها از دید والد + §12 ثبت امتیاز رضایت (۱ تا ۵)."""
    ptok = await login(client, "parent1")
    sid = await child_id(client, ptok)

    r = await client.get("/parent/tutors", headers=auth(ptok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    tutor = next(t for t in body["tutors"] if "math" in (t["subjects"] or []))
    assert tutor["name"] and tutor["headline"]
    assert body["note_fa"] and "§11" not in body["note_fa"] or body["note_fa"]

    # فیلتر درس
    r = await client.get("/parent/tutors", headers=auth(ptok), params={"subject": "physics"})
    assert r.status_code == 200
    assert all("physics" in (t["subjects"] or []) for t in r.json()["tutors"])

    # امتیاز نامعتبر → 400
    r = await client.post(
        "/parent/tutor-satisfaction", headers=auth(ptok),
        json={"student_user_id": sid, "tutor_user_id": tutor["user_id"], "rating": 9},
    )
    assert r.status_code == 400

    # معلم ناموجود ⇐ 404
    r = await client.post(
        "/parent/tutor-satisfaction", headers=auth(ptok),
        json={"student_user_id": sid, "tutor_user_id": 99999, "rating": 5},
    )
    assert r.status_code == 404

    # ثبت موفق + به‌روزرسانی (upsert)
    r = await client.post(
        "/parent/tutor-satisfaction", headers=auth(ptok),
        json={
            "student_user_id": sid,
            "tutor_user_id": tutor["user_id"],
            "rating": 4,
            "comment": "حل تمرین عالی بود",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["rating"] == 4

    r = await client.post(
        "/parent/tutor-satisfaction", headers=auth(ptok),
        json={"student_user_id": sid, "tutor_user_id": tutor["user_id"], "rating": 5},
    )
    assert r.status_code == 200 and r.json()["rating"] == 5

    r = await client.get(
        "/parent/tutor-satisfaction", headers=auth(ptok), params={"student_user_id": sid}
    )
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert len(rows) == 1  # upsert: ردیف تکراری ساخته نمی‌شود
    assert rows[0]["rating"] == 5 and rows[0]["tutor_name"]

    # فرزندِ بدون پیوند ⇐ 403
    r = await client.post(
        "/parent/tutor-satisfaction", headers=auth(ptok),
        json={"student_user_id": 6, "tutor_user_id": tutor["user_id"], "rating": 3},
    )
    assert r.status_code == 403

    # ممیزی
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(AuditLog).where(AuditLog.action == "tutor_satisfaction_saved")
            )
        ).scalars().all()
        assert len(rows) == 2
