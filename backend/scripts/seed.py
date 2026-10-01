"""Demo seed: org tree, RBAC roles/permissions, catalog, students, an
official exam, and employment policy rules. Run: python -m scripts.seed"""
import asyncio
from datetime import date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal, engine, init_models
from app.core.passwords import hash_password
from app.models.assessment import Exam, ExamItem, QuestionItem
from app.models.catalog import Book, Chapter, Period, Prerequisite, Skill, Topic
from app.models.employment import EmploymentPolicyRule
from app.models.org import (
    ClassRoom,
    District,
    Province,
    School,
    StudentProfile,
    User,
)
from app.models.rbac import Permission, PermissionAssignment, Role, RolePermission


async def seed(db: AsyncSession) -> None:
    # ---------- org ----------
    prov = Province(name="استان تهران", code="THR")
    db.add(prov)
    await db.flush()
    dist = District(province_id=prov.id, name="ناحیه ۱ تهران")
    db.add(dist)
    await db.flush()
    school = School(
        district_id=dist.id,
        province_id=prov.id,
        name="دبیرستان نمونه دانشیار",
        school_code="S-1001",
        school_type="high_school",
        ownership_type="public",
    )
    db.add(school)
    await db.flush()
    cls = ClassRoom(school_id=school.id, grade="grade_10", track="experimental", name="۱۰۱", capacity=30)
    db.add(cls)
    cls2 = ClassRoom(school_id=school.id, grade="grade_10", track="experimental", name="۱۰۲", capacity=30)
    db.add(cls2)
    await db.flush()

    # ---------- users ----------
    def mk_user(u, name, role):
        usr = User(username=u, password_hash=hash_password("pass123"), full_name=name, system_role=role)
        db.add(usr)
        return usr

    school_admin = mk_user("schooladmin", "مدیر مدرسه", "school_admin")
    district_admin = mk_user("districtadmin", "مدیر ناحیه", "district_admin")
    teacher = mk_user("teacher1", "آقای احمدی", "teacher")
    teacher2 = mk_user("teacher2", "خانم کریمی", "teacher")
    student = mk_user("student1", "محمد رضایی", "student")
    student2 = mk_user("student2", "علی کاظمی", "student")
    student3 = mk_user("student3", "سارا موسوی", "student")
    student4 = mk_user("student4", "رضا نادری", "student")
    student5 = mk_user("student5", "مریم توکلی", "student")
    new_teacher = mk_user("newteacher", "خانم صادقی", "teacher")
    await db.flush()

    db.add_all(
        [
            StudentProfile(user_id=student.id, grade="grade_10", track="experimental", school_id=school.id, class_id=cls.id),
            StudentProfile(user_id=student2.id, grade="grade_10", track="experimental", school_id=school.id, class_id=cls.id),
            StudentProfile(user_id=student3.id, grade="grade_10", track="experimental", school_id=school.id, class_id=cls.id),
            StudentProfile(user_id=student4.id, grade="grade_10", track="experimental", school_id=school.id, class_id=cls2.id),
            StudentProfile(user_id=student5.id, grade="grade_10", track="experimental", school_id=school.id, class_id=cls2.id),
        ]
    )

    # ---------- RBAC ----------
    perm_defs = [
        ("view_students", "مشاهده دانش‌آموزان"),
        ("view_school_analytics", "مشاهده تحلیل مدرسه"),
        ("manage_employment", "مدیریت استخدام"),
        ("manage_permissions", "مدیریت دسترسی‌ها"),
        ("view_district_analytics", "مشاهده تحلیل ناحیه"),
        ("create_exam", "ایجاد آزمون"),
    ]
    perm_objs = {}
    for key, title in perm_defs:
        p = Permission(key=key, title_fa=title)
        db.add(p)
        perm_objs[key] = p
    await db.flush()

    role_admin = Role(key="school_admin", title_fa="مدیر مدرسه")
    role_district = Role(key="district_admin", title_fa="مدیر ناحیه")
    db.add_all([role_admin, role_district])
    await db.flush()

    for p in perm_objs.values():
        db.add(RolePermission(role_id=role_admin.id, permission_id=p.id))
    for p in perm_objs.values():
        db.add(RolePermission(role_id=role_district.id, permission_id=p.id))
    await db.flush()

    from app.models.org import Employee, Employment, SchoolAssignment

    emp_admin = Employee(user_id=school_admin.id, personnel_code="P-001")
    emp_district = Employee(user_id=district_admin.id, personnel_code="P-002")
    emp_teacher = Employee(user_id=teacher.id, personnel_code="P-003")
    emp_teacher2 = Employee(user_id=teacher2.id, personnel_code="P-004")
    db.add_all([emp_admin, emp_district, emp_teacher, emp_teacher2])
    await db.flush()

    db.add_all(
        [
            Employment(employee_id=emp_admin.id, employment_type="official", organization="government", start_date=date.today()),
            Employment(employee_id=emp_district.id, employment_type="official", organization="government", start_date=date.today()),
            Employment(employee_id=emp_teacher.id, employment_type="contractual", organization="school", start_date=date.today()),
            Employment(employee_id=emp_teacher2.id, employment_type="official", organization="government", start_date=date.today()),
        ]
    )
    db.add_all(
        [
            SchoolAssignment(employee_id=emp_admin.id, school_id=school.id, role="principal", start_date=date.today(), status="active"),
            SchoolAssignment(employee_id=emp_teacher.id, school_id=school.id, role="teacher", subject="math", start_date=date.today(), status="active"),
            SchoolAssignment(employee_id=emp_teacher2.id, school_id=school.id, role="teacher", subject="math", start_date=date.today(), status="active"),
        ]
    )

    for user, role in [(school_admin, role_admin), (district_admin, role_district)]:
        for p in perm_objs.values():
            db.add(
                PermissionAssignment(
                    user_id=user.id,
                    role_id=role.id,
                    permission_id=p.id,
                    scope_type="school" if user == school_admin else "district",
                    scope_id=school.id if user == school_admin else dist.id,
                    is_active=True,
                )
            )

    # ---------- employment policy ----------
    db.add_all(
        [
            EmploymentPolicyRule(school_ownership="public", employment_type="official", requires_district_approval=False),
            EmploymentPolicyRule(school_ownership="public", employment_type="contractual", requires_district_approval=True),
            EmploymentPolicyRule(school_ownership="private", employment_type="official", requires_district_approval=True),
        ]
    )

    # ---------- catalog ----------
    period1 = Period(academic_year="1405-1406", number=1, start_date=date.today(), end_date=date.today() + timedelta(days=14))
    period2 = Period(academic_year="1405-1406", number=2, start_date=date.today() + timedelta(days=15), end_date=date.today() + timedelta(days=28))
    db.add_all([period1, period2])
    await db.flush()

    book = Book(subject="math", grade="grade_10", title_fa="ریاضی ۱")
    db.add(book)
    await db.flush()

    ch1 = Chapter(book_id=book.id, title_fa="مجموعه", order=1)
    ch2 = Chapter(book_id=book.id, title_fa="مثلثات", order=2)
    db.add_all([ch1, ch2])
    await db.flush()

    t_set = Topic(chapter_id=ch1.id, title_fa="مجموعه‌ها و عملیات", order=1, period_id=period1.id, blueprint_weight=1.2)
    t_rel = Topic(chapter_id=ch1.id, title_fa="تعداد زیرمجموعه‌ها", order=2, period_id=period1.id, blueprint_weight=1.0, content_status="published")
    t_tri = Topic(chapter_id=ch2.id, title_fa="نسبت‌های مثلثاتی", order=3, period_id=period2.id, blueprint_weight=1.0)
    db.add_all([t_set, t_rel, t_tri])
    await db.flush()

    db.add(Prerequisite(topic_id=t_rel.id, prereq_topic_id=t_set.id))

    db.add_all(
        [
            Skill(topic_id=t_set.id, title_fa="تشخیص عضویت"),
            Skill(topic_id=t_rel.id, title_fa="محاسبه 2^n"),
            Skill(topic_id=t_tri.id, title_fa="تعریف سینوس و کسینوس"),
        ]
    )

    # ---------- question bank ----------
    items_data = [
        (t_set.id, "کدام گزینه مجموعه تهی را نشان می‌دهد؟", {"A": "{0}", "B": "{}", "C": "{ {} }", "D": "{∅}"}, "B", "easy", None, {"A": "conceptual", "C": "conceptual"}),
        (t_rel.id, "تعداد زیرمجموعه‌های مجموعه‌ای با ۳ عضو چند است؟", {"A": "6", "B": "7", "C": "8", "D": "9"}, "C", "easy", None, {"B": "calculation", "A": "conceptual"}),
        (t_rel.id, "اگر |A|=4 باشد، تعداد زیرمجموعه‌های A کدام است؟", {"A": "8", "B": "16", "C": "32", "D": "4"}, "B", "medium", "اشتباه 2^n با n", {"A": "calculation", "D": "conceptual"}),
        (t_set.id, "کدام گزینه درست است؟ A ∪ ∅ = ؟", {"A": "∅", "B": "A", "C": "{A}", "D": "تعریف‌نشده"}, "B", "easy", None, {"A": "conceptual"}),
    ]
    qobjs = []
    for topic_id, body, options, correct, diff, miscon, distr in items_data:
        q = QuestionItem(
            topic_id=topic_id,
            body=body,
            options=options,
            correct_option=correct,
            difficulty=diff,
            difficulty_weight={"easy": 1.0, "medium": 1.2, "hard": 1.5}[diff],
            misconception=miscon,
            distractor_causes=distr,
        )
        db.add(q)
        qobjs.append(q)
    await db.flush()

    exam = Exam(
        title_fa="آزمون دوره ۱ — ریاضی دهم",
        exam_type="period_exam",
        grade="grade_10",
        subject="math",
        scope="school",
        school_id=school.id,
        period_id=period1.id,
        blueprint=[{"topic_id": t_set.id, "count": 2}, {"topic_id": t_rel.id, "count": 2}],
        status="published",
        opens_at=datetime.utcnow() - timedelta(days=1),
        closes_at=datetime.utcnow() + timedelta(days=6),
        created_by=school_admin.id,
    )
    db.add(exam)
    await db.flush()
    for i, q in enumerate(qobjs, start=1):
        db.add(ExamItem(exam_id=exam.id, item_id=q.id, order=i, points=2.5))

    # ---------- تخصیص معلم به کلاس (سند معلم §18) ----------
    from app.models.org import ClassTeacherAssignment

    db.add(
        ClassTeacherAssignment(
            class_id=cls.id,
            teacher_user_id=teacher.id,
            subject="math",
            start_date=date.today(),
            status="active",
        )
    )
    db.add(
        ClassTeacherAssignment(
            class_id=cls2.id,
            teacher_user_id=teacher2.id,
            subject="math",
            start_date=date.today(),
            status="active",
        )
    )

    # ---------- شواهد نمونه برای رادار کلاس و گروه‌بندی نیاز ----------
    from app.models.slm import Evidence
    from app.services.slm_service import update_states_from_evidence

    now_utc = datetime.utcnow()

    def practice(user_id, topic_id, partial, days_ago):
        return Evidence(
            student_user_id=user_id,
            topic_id=topic_id,
            source="practice",
            weight=0.5,
            correct=1 if partial >= 0.75 else 0,
            partial_credit=partial,
            difficulty_weight=1.0,
            occurred_at=now_utc - timedelta(days=days_ago),
        )

    # student1: بدون شواهد اضافه — از آزمون دوره نمره می‌گیرد (تسلط پایین → مداخله)

    # student2: همه درست ولی آخرین شاهد ۲۰ روز قبل → افت ماندگاری
    for d in (40, 30, 20):
        db.add(practice(student2.id, t_set.id, 1.0, d))

    # student3: قوی و تازه → آماده پیشروی
    for d in (2, 1, 0):
        db.add(practice(student3.id, t_set.id, 1.0, d))

    # کلاس ۱۰۲ (خانم کریمی): هر دو دانش‌آموز قوی و تازه → مقایسه واقعی دو کلاس
    for uid in (student4.id, student5.id):
        for d in (3, 2, 1):
            db.add(practice(uid, t_set.id, 1.0, d))

    await db.flush()
    for s in (student, student2, student3, student4, student5):
        await update_states_from_evidence(db, s.id)

    await db.commit()


async def main() -> None:
    await init_models()
    async with AsyncSessionLocal() as session:
        await seed(session)
    await engine.dispose()
    print("Seeded OK")


if __name__ == "__main__":
    asyncio.run(main())
