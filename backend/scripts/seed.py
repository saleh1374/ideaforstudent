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
    ParentLink,
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

    # ---------- مدرسه دوم (برای بردها/تجمیع‌های استان — حداقل جمعیت ۱۰) ----------
    school2 = School(
        district_id=dist.id,
        province_id=prov.id,
        name="دبیرستان دانش‌سرای شهر",
        school_code="S-1002",
        school_type="high_school",
        ownership_type="non_profit",
    )
    db.add(school2)
    await db.flush()
    cls3 = ClassRoom(school_id=school2.id, grade="grade_10", track="math", name="۲۰۱", capacity=30)
    db.add(cls3)
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
    parent1 = mk_user("parent1", "پدر محمد رضایی", "parent")
    province_admin = mk_user("provinceadmin", "مدیر کل استان", "province_admin")
    ministry_user = mk_user("ministry", "کارشناس وزارت", "ministry")
    tutor_user = mk_user("tutor1", "معلم خصوصی ریاضی", "teacher")
    # ۱۰ دانش‌آموز مدرسه دوم — تا برد/تجمیع بالای حداقل جمعیت ۱۰ برود
    school2_students = [mk_user(f"s2student{i}", f"دانش‌آموز مدرسه ۲ — {i}", "student") for i in range(1, 11)]
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
    db.add_all(
        [
            StudentProfile(user_id=s.id, grade="grade_10", track="math", school_id=school2.id, class_id=cls3.id)
            for s in school2_students
        ]
    )

    # ---------- پیوند والد — فرزند (سند والدین §17) ----------
    db.add(ParentLink(parent_user_id=parent1.id, student_user_id=student.id, relation="father"))

    # ---------- RBAC ----------
    perm_defs = [
        ("view_students", "مشاهده دانش‌آموزان"),
        ("view_school_analytics", "مشاهده تحلیل مدرسه"),
        ("manage_employment", "مدیریت استخدام"),
        ("manage_permissions", "مدیریت دسترسی‌ها"),
        ("view_district_analytics", "مشاهده تحلیل ناحیه"),
        ("create_exam", "ایجاد آزمون"),
        ("manage_deputies", "مدیریت معاونان مدرسه"),  # RBAC spec §6
        # Feature B: پذیرش ثبت‌نام/افزودن مستقیم دانش‌آموز — فقط یک بار
        # ساخته می‌شود (کلید Permission یکتاست) و حلقه‌های نقش مدرسه/ناحیه
        # (و چک‌لیست معاون) خودشان آن را برمی‌دارند.
        ("manage_admissions", "مدیریت ثبت‌نام دانش‌آموزان"),
        # پنل کامل مدیر مدرسه: شیفت‌ها، برنامه هفتگی، کلاس‌ها، جابه‌جایی دانش‌آموز
        ("manage_school_ops", "مدیریت عملیات مدرسه"),
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

    # ---------- مجوزهای سطح ناحیه (پنل مدیر ناحیه — district spec §1, §34) ----------
    district_perm_defs = [
        ("manage_schools", "مدیریت مدارس ناحیه"),
        ("manage_principals", "انتصاب مدیر مدرسه"),
        ("manage_district_staff", "مدیریت کارکنان ناحیه"),
        ("manage_employment_policy", "ویرایش سیاست استخدام"),
        ("manage_teacher_qualifications", "مدیریت صلاحیت معلم"),
    ]
    district_perms = {}
    for key, title in district_perm_defs:
        p = Permission(key=key, title_fa=title)
        db.add(p)
        district_perms[key] = p
    await db.flush()
    for p in district_perms.values():
        db.add(RolePermission(role_id=role_district.id, permission_id=p.id))
    await db.flush()

    # ---------- مجوزهای استان/وزارت (جدا از سطح مدرسه/ناحیه) ----------
    perm_province = Permission(key="view_province_analytics", title_fa="مشاهده تحلیل استان")
    perm_national = Permission(key="view_national_analytics", title_fa="مشاهده تحلیل کشور")
    db.add_all([perm_province, perm_national])
    role_province = Role(key="province_admin", title_fa="مدیر کل استان")
    role_ministry = Role(key="ministry", title_fa="وزارت")
    db.add_all([role_province, role_ministry])
    await db.flush()
    # استان: تحلیل استان (حوزه استان) + تحلیل کشور (حوزه کشور — رقابت سالم بین
    # استان‌ها) + مجوزهای ناحیه‌ای برای تفویض در حوزه استان؛ وزارت: هر دو کشوری
    for p in (perm_province, perm_national):
        db.add(RolePermission(role_id=role_province.id, permission_id=p.id))
        db.add(RolePermission(role_id=role_ministry.id, permission_id=p.id))
    for p in district_perms.values():
        db.add(RolePermission(role_id=role_province.id, permission_id=p.id))
    # manage_admissions در perm_defs ساخته شد (کلید یکتا)؛ نقش استان
    # صراحتاً همان مجوز را می‌گیرد تا درخواست‌های بدون مدرسه را هم ببیند.
    db.add(RolePermission(role_id=role_province.id, permission_id=perm_objs["manage_admissions"].id))
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
            # مدیر ناحیه عضو هیئت علمی ناحیه است (district spec §12 — کارکنان ناحیه)
            Employment(employee_id=emp_district.id, employment_type="official", organization="district", district_id=dist.id, start_date=date.today()),
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

    # مدیر ناحیه: مجوزهای ناحیه‌ای در حوزه ناحیه خودش
    for p in district_perms.values():
        db.add(
            PermissionAssignment(
                user_id=district_admin.id,
                role_id=role_district.id,
                permission_id=p.id,
                scope_type="district",
                scope_id=dist.id,
                is_active=True,
            )
        )

    for user, role, perms, scope_type, scope_id in [
        # استان: تحلیل استان در حوزه استان، تحلیل کشور در حوزه کشور (کلید
        # view_national_analytics حوزه national می‌خواهد — /geo/national/*)
        (province_admin, role_province, (perm_province,), "province", prov.id),
        (province_admin, role_province, (perm_national,), "national", 0),
        (province_admin, role_province, tuple(district_perms.values()), "province", prov.id),
        # Feature B: پذیرش ثبت‌نام در حوزه استان (دیدن درخواست‌های بدون مدرسه)
        (province_admin, role_province, (perm_objs["manage_admissions"],), "province", prov.id),
        (ministry_user, role_ministry, (perm_province, perm_national), "national", 0),
    ]:
        for p in perms:
            db.add(
                PermissionAssignment(
                    user_id=user.id,
                    role_id=role.id,
                    permission_id=p.id,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    is_active=True,
                )
            )

    # ---------- نقش «معاون» برای تفویض چک‌لیست معاونان (RBAC spec §6) ----------
    role_deputy = Role(key="deputy", title_fa="معاون مدرسه")
    db.add(role_deputy)
    await db.flush()
    for p in [*perm_objs.values(), *district_perms.values(), perm_province, perm_national]:
        db.add(RolePermission(role_id=role_deputy.id, permission_id=p.id))
    await db.flush()

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

    # ---------- بانک سؤال آزمون صلاحیت معلم (سند صلاحیت) ----------
    # جدا از بانک دانش‌آموز: این سؤال‌ها مبحث کاتالوگ ندارند.
    from app.models.teacher_assessment import TeacherExamQuestion

    subject_bank = [
        ("دامنه تابع f(x) = ۱/(x−۲) کدام است؟", {"A": "x ≠ ۲", "B": "x > ۲", "C": "x ≠ ۰", "D": "x ≥ ۲"}, "A", "easy"),
        ("مقدار sin(۳۰°) چقدر است؟", {"A": "۱/۲", "B": "√۳/۲", "C": "۱", "D": "۰"}, "A", "easy"),
        ("مشتق تابع f(x) = x² در x = ۳ چقدر است؟", {"A": "۳", "B": "۶", "C": "۹", "D": "۲"}, "B", "medium"),
        ("اگر log₂(x) = ۵ باشد، x چقدر است؟", {"A": "۱۰", "B": "۲۵", "C": "۳۲", "D": "۵"}, "C", "medium"),
        ("تعداد زیرمجموعه‌های مجموعه‌ای با ۳ عضو چند است؟", {"A": "۶", "B": "۷", "C": "۸", "D": "۹"}, "C", "easy"),
        ("میانگین اعداد ۲، ۴، ۶، ۸ چقدر است؟", {"A": "۴", "B": "۵", "C": "۶", "D": "۷"}, "B", "easy"),
        ("شیب خط ۲x + ۳y = ۶ کدام است؟", {"A": "−۲/۳", "B": "۲/۳", "C": "−۳/۲", "D": "۳/۲"}, "A", "medium"),
        ("احتمال رخ دادن یک رویداد قطعی چقدر است؟", {"A": "۰", "B": "۱/۲", "C": "۱", "D": "۱/۴"}, "C", "easy"),
        ("مقدار |۳ − ۷| + ۲² کدام است؟", {"A": "۸", "B": "۱۰", "C": "۶", "D": "۱۲"}, "A", "easy"),
        ("ریشه‌های تابع f(x) = x² − ۴ کدام‌اند؟", {"A": "۲ و −۲", "B": "۴", "C": "۰", "D": "۲"}, "A", "medium"),
    ]
    for body, options, correct, diff in subject_bank:
        db.add(
            TeacherExamQuestion(
                kind="subject",
                subject="math",
                body=body,
                options=options,
                correct_option=correct,
                difficulty=diff,
            )
        )

    management_bank = [
        ("هنگام بی‌نظمی در کلاس، بهترین اقدام اولیه معلم کدام است؟", {"A": "فریاد زدن برای ساکت‌کردن", "B": "ایجاد ارتباط چشمی و مکث آرام", "C": "ترک کلاس", "D": "گزارش فوری به مدیر"}, "B", "easy"),
        ("برای مشارکت دانش‌آموزان کم‌رو چه باید کرد؟", {"A": "همیشه داوطلب‌ها را صدا زدن", "B": "پرسش تصادفی و وقت دادن برای فکر کردن", "C": "نمره منفی برای بی‌جوابی", "D": "بی‌توجهی"}, "B", "medium"),
        ("زمان‌بندی مناسب بازخورد به دانش‌آموز کدام است؟", {"A": "پایان ترم", "B": "بلافاصله پس از انجام کار", "C": "فقط در جلسه اولیا", "D": "بازخورد لازم نیست"}, "B", "easy"),
        ("اگر دانش‌آموزی مکرر تکلیف ارائه ندهد، مناسب‌ترین واکنش کدام است؟", {"A": "ثبت صفر بی‌قید", "B": "گفت‌وگوی خصوصی و برنامه‌ریزی با پیگیری", "C": "حذف از کلاس", "D": "تنبیه گروهی"}, "B", "medium"),
        ("تفاوت تدریس متمایز با تدریس یکسان چیست؟", {"A": "برای همه یک روش واحد", "B": "استراتژی و تکلیف متناسب با آمادگی دانش‌آموزان", "C": "کاهش انتظارات", "D": "حذف ارزشیابی"}, "B", "medium"),
        ("بهترین شیوه مدیریت زمان کلاس کدام است؟", {"A": "همه وقت حل تمرین", "B": "تقسیم زمان برای معرفی، تمرین و جمع‌بندی", "C": "سخنرانی تا آخر وقت", "D": "رها کردن برنامه"}, "B", "easy"),
        ("هنگام پاسخ اشتباه دانش‌آموز، واکنش مناسب کدام است؟", {"A": "تذکر شدید", "B": "اهمیت دادن به تلاش و هدایت با پرسش‌های راهنما", "C": "بی‌پاسخ گذاشتن", "D": "خنده جمعی"}, "B", "medium"),
        ("برای ارزشیابی تشخیصی در میانه تدریس کدام بهتر است؟", {"A": "فقط آزمون پایانی", "B": "پرسش کلاسی و کاربرگ کوتاه برای شناسایی سوءتفاهم‌ها", "C": "حذف امتحان", "D": "نمره‌دهی رقابتی"}, "B", "easy"),
    ]
    for body, options, correct, diff in management_bank:
        db.add(
            TeacherExamQuestion(
                kind="classroom_management",
                subject=None,
                body=body,
                options=options,
                correct_option=correct,
                difficulty=diff,
            )
        )
    await db.flush()  # autoflush خاموش است — پیش از نمونه‌برداری سرویس باید ثبت شوند

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

    # ---------- شیفت‌ها و برنامه هفتگی نمونه (پنل کامل مدیر مدرسه) ----------
    # مدرسه ۱ تک‌شیفت (۰۸:۰۰–۱۵:۰۰)؛ مدرسه ۲ دوشیفت (۰۸:۰۰–۱۲:۰۰ و ۱۲:۰۰–۱۸:۰۰)
    from app.models.school_ops import ClassScheduleEntry, SchoolShift

    shift_morning = SchoolShift(
        school_id=school.id, name="شیفت صبح", start_time="08:00", end_time="15:00", order=0
    )
    db.add_all(
        [
            shift_morning,
            SchoolShift(school_id=school2.id, name="شیفت اول", start_time="08:00", end_time="12:00", order=0),
            SchoolShift(school_id=school2.id, name="شیفت دوم", start_time="12:00", end_time="18:00", order=1),
        ]
    )
    await db.flush()

    # برنامه هفتگی نمونه کلاس ۱۰۱ (معلم ریاضی = teacher1) و ۱۰۲ (teacher2) و ۲۰۱
    # (بدون معلم — جلسه‌های آزاد) — بدون تداخل زمانی بین معلمان
    sample_schedule = [
        # کلاس ۱۰۱ — teacher1 ریاضی، روزهای ۰ (شنبه) تا ۴ (چهارشنبه)
        (cls.id, school.id, 0, "08:00", "09:30", "math", teacher.id),
        (cls.id, school.id, 1, "08:00", "09:30", "math", teacher.id),
        (cls.id, school.id, 2, "08:00", "09:30", "math", teacher.id),
        (cls.id, school.id, 3, "10:00", "11:30", "math", teacher.id),
        (cls.id, school.id, 4, "10:00", "11:30", "math", teacher.id),
        # کلاس ۱۰۲ — teacher2 ریاضی، بعدازظهر (داخل شیفت صبح)
        (cls2.id, school.id, 0, "11:00", "12:30", "math", teacher2.id),
        (cls2.id, school.id, 2, "11:00", "12:30", "math", teacher2.id),
        (cls2.id, school.id, 4, "13:00", "14:30", "math", teacher2.id),
        # کلاس ۲۰۱ مدرسه ۲ — شیفت اول، بدون معلم ثبت‌شده
        (cls3.id, school2.id, 0, "08:00", "09:30", "math", None),
        (cls3.id, school2.id, 2, "09:45", "11:15", "math", None),
    ]
    for class_id, school_id, day, start, end, subject, teacher_user_id in sample_schedule:
        db.add(
            ClassScheduleEntry(
                class_id=class_id,
                school_id=school_id,
                day=day,
                start_time=start,
                end_time=end,
                subject=subject,
                teacher_user_id=teacher_user_id,
            )
        )
    await db.flush()

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

    # ---------- مدرسه دوم: ۱۰ دانش‌آموز با شواهد کافی (برد/تجمیع بالای حداقل جمعیت) ----------
    for i, s in enumerate(school2_students):
        partial = 1.0 if i % 3 else 0.5  # ترکیب قوی/ضعیف برای تجمیع‌های معنادار
        for d in (6, 3, 1):
            db.add(practice(s.id, t_set.id, partial, d))

    await db.flush()
    for s in (student, student2, student3, student4, student5, *school2_students):
        await update_states_from_evidence(db, s.id)

    # ---------- بازار معلم خصوصی (فاز ۸) ----------
    from app.models.tutoring import TutorGroup, TutorProfile

    db.add(
        TutorProfile(
            user_id=tutor_user.id,
            headline="معلم ریاضی — حل تمرین و آماده‌سازی کنکور",
            subjects=["math"],
            bio="۱۰ سال تدریس خصوصی ریاضی دهم تا دوازدهم",
            session_price=400_000,
            availability="شنبه و چهارشنبه عصر",
        )
    )
    db.add(
        TutorGroup(
            tutor_user_id=teacher.id,
            title="گروه تقویتی ریاضی کلاس ۱۰۱",
            subject="math",
            is_open=True,
        )
    )

    # ---------- آزمون صلاحیت معلم: تخصیص نمونه برای معلم ریاضی ----------
    # فقط تخصیص واقعی (وضع assigned)؛ نمره‌ای جعل نمی‌شود تا رابط کاربری
    # آزمون‌ها را نشان دهد و معلم خودش آن‌ها را بگذروند.
    from app.services.teacher_qualification import assign_year_exams, current_school_year

    await assign_year_exams(
        db,
        teacher_user_id=teacher.id,
        subject="math",
        school_year=current_school_year(),
        assigned_by=district_admin.id,
        school_id=school.id,
        district_id=dist.id,
    )

    await db.commit()


async def main() -> None:
    await init_models()
    async with AsyncSessionLocal() as session:
        await seed(session)
    await engine.dispose()
    print("Seeded OK")


if __name__ == "__main__":
    asyncio.run(main())
