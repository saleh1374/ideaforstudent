"""آزمون‌های اعمال RBAC (RBAC spec §5–§10): انقضای مجوز، حوزه‌مندیِ
منابع، قاعده طلایی (رد با HTTP 403 + لاگ ممیزی)، جدول سیاست استخدامِ
قابل‌نویس، معاونان (§6) و انتقال کارکنان (§10)."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_daneshyar.db")

from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.db import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.assessment import AttemptAnswer, ExamAttempt, ExamItem
from app.models.employment import EmploymentRequest
from app.models.org import Employee, SchoolAssignment, User
from app.models.rbac import AuditLog, Permission, PermissionAssignment, Role
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


async def one(db, model, **filters):
    return (await db.execute(select(model).filter_by(**filters))).scalar_one()


async def audit_rows(action: str) -> list[tuple[int | None, str | None]]:
    """رویدادهای یکسان در لاگ ممیزی (actor, detail)."""
    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id))
        ).scalars().all()
        return [(r.actor_user_id, r.detail) for r in rows]


async def user_id(username: str) -> int:
    async with AsyncSessionLocal() as s:
        return (await one(s, User, username=username)).id


# ------------------------- §9 دسترسی موقت / انقضا -------------------------


@pytest.mark.anyio
async def test_expired_grant_is_denied_and_logged(client, seeded):
    """تخصیص خارج از بازه اعتبار نه فقط نادیده گرفته می‌شود، بلکه غیرفعال و
    با رویداد permission_expired در لاگ ممیزی ثبت می‌گردد (§9)."""
    async with AsyncSessionLocal() as s:
        teacher = await one(s, User, username="teacher1")
        role = await one(s, Role, key="school_admin")
        view_school = await one(s, Permission, key="view_school_analytics")
        manage_emp = await one(s, Permission, key="manage_employment")

        past = PermissionAssignment(
            user_id=teacher.id,
            role_id=role.id,
            permission_id=view_school.id,
            scope_type="school",
            scope_id=1,
            valid_from=date.today() - timedelta(days=30),
            valid_until=date.today() - timedelta(days=1),
            is_active=True,
        )
        future = PermissionAssignment(
            user_id=teacher.id,
            role_id=role.id,
            permission_id=manage_emp.id,
            scope_type="school",
            scope_id=1,
            valid_from=date.today() + timedelta(days=1),
            is_active=True,
        )
        s.add_all([past, future])
        await s.commit()
        past_id, future_id = past.id, future.id

    ttok = await login(client, "teacher1")

    # مجوز منقضی‌شده → رد دسترسی، نه عبور بی‌صدا
    r = await client.get("/admin/school/1/overview", headers=auth(ttok))
    assert r.status_code == 403, r.text

    # مجوزی که هنوز شروع نشده → همان رفتار
    r = await client.get("/admin/employment-requests", headers=auth(ttok))
    assert r.status_code == 403, r.text

    # هر دو تخصیص غیرفعال شده و رویداد انقضا ثبت گردیده
    logs = await audit_rows("permission_expired")
    assert len(logs) == 2, logs
    details = " ".join(d or "" for _, d in logs)
    assert f"user={teacher.id}" in details

    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                select(PermissionAssignment).where(
                    PermissionAssignment.id.in_([past_id, future_id])
                )
            )
        ).scalars().all()
        assert len(rows) == 2
        assert all(row.is_active is False for row in rows)

    # فهرست مجوزهای مؤثر خالی است
    r = await client.get("/admin/permissions/mine", headers=auth(ttok))
    assert r.status_code == 200
    assert r.json()["permissions"] == []


# ------------------------- §7 حوزه‌مندیِ منابع -------------------------


@pytest.mark.anyio
async def test_scope_isolation_between_schools(client, seeded):
    """مدیر مدرسه ۱ فقط مدرسه/کلاس‌های خودش را می‌بیند؛ مدیر ناحیه هر دو
    مدرسه ناحیه را (زنجیره حوزه: national ⊃ province ⊃ district ⊃ school)."""
    atok = await login(client, "schooladmin")
    dtok = await login(client, "districtadmin")

    r = await client.get("/admin/school/1/overview", headers=auth(atok))
    assert r.status_code == 200, r.text

    # مدرسه دیگر → 403 (حوزه مجوز نمی‌پوشاند)
    r = await client.get("/admin/school/2/overview", headers=auth(atok))
    assert r.status_code == 403
    r = await client.get("/admin/school/2/teachers", headers=auth(atok))
    assert r.status_code == 403

    # کلاس مدرسه دیگر → 403
    r = await client.get("/admin/classes/3/diagnosis", headers=auth(atok))
    assert r.status_code == 403
    r = await client.get("/admin/classes/1/diagnosis", headers=auth(atok))
    assert r.status_code == 200, r.text

    # مدیر ناحیه: مدرسه ۲ در حوزه اوست
    r = await client.get("/admin/school/2/overview", headers=auth(dtok))
    assert r.status_code == 200, r.text

    # حوزه‌های ثبت‌شده تماس‌گیرنده
    r = await client.get("/admin/permissions/mine", headers=auth(atok))
    assert r.status_code == 200
    scopes = {tuple(row) for row in r.json()["scopes"]}
    assert ("school", 1) in scopes
    assert ("district", 1) not in scopes


# ------------------------- §8 قاعده طلایی -------------------------


@pytest.mark.anyio
async def test_golden_rule_denied_with_audit_log(client, seeded):
    """قاعده طلایی در بک‌اند اعمال می‌شود: هر ردی = لاگ ممیزی + HTTP 403."""
    atok = await login(client, "schooladmin")
    async with AsyncSessionLocal() as s:
        grantee = await one(s, User, username="teacher1")
        target = await one(s, User, username="districtadmin")
        perm_manage_schools = await one(s, Permission, key="manage_schools")
        perm_view_school = await one(s, Permission, key="view_school_analytics")
        role_district = await one(s, Role, key="district_admin")
        role_school = await one(s, Role, key="school_admin")

    # (۱) مجوزی که تفویض‌کننده خودش ندارد → 403
    r = await client.post(
        "/admin/permissions/grant",
        headers=auth(atok),
        json={
            "grantee_user_id": grantee.id,
            "role_id": role_district.id,
            "permission_id": perm_manage_schools.id,
            "scope_type": "school",
            "scope_id": 1,
        },
    )
    assert r.status_code == 403, r.text

    # (۲) حوزه‌ای که تفویض‌کننده نمی‌پوشاند → 403 (مدیر مدرسه، ناحیه)
    r = await client.post(
        "/admin/permissions/grant",
        headers=auth(atok),
        json={
            "grantee_user_id": grantee.id,
            "role_id": role_school.id,
            "permission_id": perm_view_school.id,
            "scope_type": "district",
            "scope_id": 1,
        },
    )
    assert r.status_code == 403, r.text

    denied = await audit_rows("delegation_denied_insufficient_owner_permission")
    assert len(denied) == 2, denied
    schooladmin_id = await user_id("schooladmin")
    assert all(actor == schooladmin_id for actor, _ in denied)
    assert "manage_schools" in (denied[0][1] or "")
    # رد دوم از چکِ حوزه endpoint است: تفویض‌کننده در ناحیه manage_permissions ندارد
    assert "permission=manage_permissions scope=district:1" in (denied[1][1] or "")
    # هیچ مجوزی واقعاً واگذار نشده است
    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                select(PermissionAssignment).where(PermissionAssignment.user_id == grantee.id)
            )
        ).scalars().all()
        assert rows == []

    # (۳) تفویض مشروع در همان حوزه → 200 و اثر فوری
    r = await client.post(
        "/admin/permissions/grant",
        headers=auth(atok),
        json={
            "grantee_user_id": grantee.id,
            "role_id": role_school.id,
            "permission_id": perm_view_school.id,
            "scope_type": "school",
            "scope_id": 1,
        },
    )
    assert r.status_code == 200, r.text
    granted = await audit_rows("permission_granted")
    assert any(d and "view_school_analytics" in d for _, d in granted)

    ttok = await login(client, "teacher1")
    r = await client.get("/admin/school/1/overview", headers=auth(ttok))
    assert r.status_code == 200, r.text
    async with AsyncSessionLocal() as s:
        new_pa = (
            await s.execute(
                select(PermissionAssignment).where(
                    PermissionAssignment.user_id == grantee.id,
                    PermissionAssignment.is_active.is_(True),
                )
            )
        ).scalars().one()
        assignment_id = new_pa.id

    # (۴) لغو در حوزه دیگر → 403 (same-scope admin)
    async with AsyncSessionLocal() as s:
        district_pa = (
            await s.execute(
                select(PermissionAssignment).where(
                    PermissionAssignment.user_id == target.id,
                    PermissionAssignment.scope_type == "district",
                )
            )
        ).scalars().first()
        assert district_pa is not None
        district_pa_id = district_pa.id

    r = await client.post(f"/admin/permissions/{district_pa_id}/revoke", headers=auth(atok))
    assert r.status_code == 403, r.text

    # (۵) لغو در همان حوزه → 200
    r = await client.post(f"/admin/permissions/{assignment_id}/revoke", headers=auth(atok))
    assert r.status_code == 200, r.text
    r = await client.get("/admin/school/1/overview", headers=auth(ttok))
    assert r.status_code == 403

    revoked = await audit_rows("permission_revoked")
    assert any(d and f"assignment={assignment_id}" in d for _, d in revoked)


# ------------------------- §5 گردش کار استخدام (حوزه‌مند) -------------------------


@pytest.mark.anyio
async def test_employment_submit_and_decide_are_scope_checked(client, seeded):
    """ثبت فقط توسط مدیر همان مدرسه یا مسئول ناحیه؛ تصمیم فقط در سطح ناحیه
    و بالاتر — مدیر مدرسه نمی‌تواند درخواست خودش را تأیید کند."""
    async with AsyncSessionLocal() as s:
        schooladmin = await one(s, User, username="schooladmin")
        newteacher = await one(s, User, username="newteacher")
        # درخواستِ بازِ مدرسه ۲ — برای بررسی فیلتر صندوق ورودی
        s.add(
            EmploymentRequest(
                school_id=2,
                requested_by=schooladmin.id,
                employee_user_id=newteacher.id,
                full_name="معلم مدرسه ۲",
                employment_type="official",
                organization="government",
                subject="math",
                status="pending",
            )
        )
        await s.commit()

    stok = await login(client, "schooladmin")
    dtok = await login(client, "districtadmin")
    ttok = await login(client, "teacher1")

    # صندوق ورودی حوزه‌مند است: تنها درخواست موجود (مدرسه ۲) فقط برای
    # دارنده حوزه ناحیه دیده می‌شود
    r = await client.get("/admin/employment-requests", headers=auth(stok))
    assert r.status_code == 200, r.text
    assert r.json()["requests"] == []

    r = await client.get("/admin/employment-requests", headers=auth(dtok))
    assert r.status_code == 200, r.text
    assert {row["school_id"] for row in r.json()["requests"]} == {2}

    payload = {
        "employee_user_id": newteacher.id,
        "full_name": "معلم جدید",
        "employment_type": "contractual",
        "organization": "government",
        "subject": "math",
    }

    # معلمِ بدون مجوز → 403
    r = await client.post(
        "/admin/employment-requests", headers=auth(ttok), json={**payload, "school_id": 1}
    )
    assert r.status_code == 403

    # مدیر مدرسه ۱ برای مدرسه ۲ → خارج از حوزه → 403
    r = await client.post(
        "/admin/employment-requests", headers=auth(stok), json={**payload, "school_id": 2}
    )
    assert r.status_code == 403, r.text

    # مدیر ناحیه برای مدرسه ۲ → حوزه ناحیه می‌پوشاند → 200
    r = await client.post(
        "/admin/employment-requests", headers=auth(dtok), json={**payload, "school_id": 2}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"

    # مدیر همان مدرسه → 200 (درخواست pending، چون سیاست public/contractual
    # تأیید ناحیه می‌خواهد)
    r = await client.post(
        "/admin/employment-requests", headers=auth(stok), json={**payload, "school_id": 1}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"
    request_id = r.json()["request_id"]

    # پس از ثبت: مدیر مدرسه فقط مدرسه خودش را می‌بیند، مدیر ناحیه هر دو را
    r = await client.get("/admin/employment-requests", headers=auth(stok))
    assert {row["school_id"] for row in r.json()["requests"]} == {1}
    r = await client.get("/admin/employment-requests", headers=auth(dtok))
    assert {row["school_id"] for row in r.json()["requests"]} == {1, 2}

    # خودِ مدیر مدرسه نمی‌تواند تأیید کند → 403
    r = await client.post(
        f"/admin/employment-requests/{request_id}/decide",
        headers=auth(stok),
        json={"approve": True},
    )
    assert r.status_code == 403, r.text

    # مدیر ناحیه تأیید می‌کند → 200
    r = await client.post(
        f"/admin/employment-requests/{request_id}/decide",
        headers=auth(dtok),
        json={"approve": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"


# ------------------------- §5 جدول سیاست استخدام قابل نوشتن -------------------------


@pytest.mark.anyio
async def test_policy_table_is_writable(client, seeded):
    """«جدول سیاست، نه منطق سخت‌کدشده»: قانون (مالکیت × نوع استخدام) در زمان
    اجرا قابل ایجاد/ویرایش است و بلافاصله بر جریان تصمیم اثر می‌گذارد."""
    stok = await login(client, "schooladmin")
    dtok = await login(client, "districtadmin")
    async with AsyncSessionLocal() as s:
        newteacher = await one(s, User, username="newteacher")
        newteacher_id = newteacher.id

    # مدیر مدرسه مجوز manage_employment_policy ندارد → 403
    r = await client.post(
        "/admin/employment-policy",
        headers=auth(stok),
        json={
            "school_ownership": "public",
            "employment_type": "official",
            "requires_district_approval": True,
        },
    )
    assert r.status_code == 403

    # نامعتبر → 400
    r = await client.post(
        "/admin/employment-policy",
        headers=auth(dtok),
        json={
            "school_ownership": "cooperative",
            "employment_type": "official",
            "requires_district_approval": True,
        },
    )
    assert r.status_code == 400

    payload = {
        "school_ownership": "public",
        "employment_type": "official",
        "requires_district_approval": True,
        "note": "تأیید ناحیه برای استخدام رسمی الزامی شد",
    }
    r = await client.post("/admin/employment-policy", headers=auth(dtok), json=payload)
    assert r.status_code == 200, r.text
    rule_id = r.json()["rule"]["id"]
    assert r.json()["rule"]["requires_district_approval"] is True

    # اثر فوری: دیگر خودکار تأیید نمی‌شود
    r = await client.post(
        "/admin/employment-requests",
        headers=auth(stok),
        json={
            "school_id": 1,
            "employee_user_id": newteacher_id,
            "full_name": "معلم رسمی",
            "employment_type": "official",
            "organization": "government",
            "subject": "math",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending", r.text

    # همان قانون upsert می‌شود، ردیف جدید ساخته نمی‌شود
    payload = {**payload, "requires_district_approval": False, "note": "بازنگری شد"}
    r = await client.post("/admin/employment-policy", headers=auth(dtok), json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["rule"]["id"] == rule_id
    assert r.json()["rule"]["requires_district_approval"] is False

    r = await client.get("/admin/employment-policy", headers=auth(dtok))
    assert r.status_code == 200
    rows = r.json()["rules"]
    matched = [
        row
        for row in rows
        if row["school_ownership"] == "public" and row["employment_type"] == "official"
    ]
    assert len(matched) == 1
    assert matched[0]["requires_district_approval"] is False


# ------------------------- §6 معاونان -------------------------


@pytest.mark.anyio
async def test_deputies_lifecycle_and_golden_rule(client, seeded):
    """چک‌لیست مجوز پویای معاون: ساخت/ویرایش/حذف نرم + اتصال کاربر با
    پیش‌بررسی قاعده طلایی پیش از ایجاد هر رکوردی."""
    atok = await login(client, "schooladmin")
    dtok = await login(client, "districtadmin")
    async with AsyncSessionLocal() as s:
        teacher1 = await one(s, User, username="teacher1")
        teacher2 = await one(s, User, username="teacher2")

    r = await client.get("/admin/schools/1/deputies", headers=auth(atok))
    assert r.status_code == 200, r.text
    assert r.json()["deputies"] == []

    # کلید نامعتبر → 400
    r = await client.post(
        "/admin/schools/1/deputies",
        headers=auth(atok),
        json={"title_fa": "معاون آموزشی", "permission_keys": ["unknown_permission"]},
    )
    assert r.status_code == 400

    r = await client.post(
        "/admin/schools/1/deputies",
        headers=auth(atok),
        json={
            "title_fa": "معاون آموزشی",
            "permission_keys": ["view_school_analytics", "manage_employment"],
        },
    )
    assert r.status_code == 200, r.text
    deputy_id = r.json()["deputy"]["id"]
    created = await audit_rows("deputy_role_created")
    assert len(created) == 1, created
    assert "school=1" in (created[0][1] or "")

    # اتصال کاربر → همه کلیدها با حوزه مدرسه واگذار می‌شوند
    r = await client.post(
        f"/admin/schools/1/deputies/{deputy_id}/assign-user",
        headers=auth(atok),
        json={"user_id": teacher1.id},
    )
    assert r.status_code == 200, r.text
    assert sorted(r.json()["granted"]) == ["manage_employment", "view_school_analytics"]

    ttok = await login(client, "teacher1")
    r = await client.get("/admin/school/1/overview", headers=auth(ttok))
    assert r.status_code == 200, r.text

    # مدیر ناحیه معاونان را می‌بیند (ولی چک‌لیست را عوض نمی‌کند)
    r = await client.get("/admin/schools/1/deputies", headers=auth(dtok))
    assert r.status_code == 200, r.text
    rows = r.json()["deputies"]
    assert len(rows) == 1
    assert rows[0]["assigned_users"][0]["user_id"] == teacher1.id

    r = await client.patch(
        f"/admin/schools/1/deputies/{deputy_id}",
        headers=auth(dtok),
        json={"permission_keys": ["view_school_analytics"]},
    )
    assert r.status_code == 403, r.text

    # ویرایش چک‌لیست توسط مدیر مدرسه
    r = await client.patch(
        f"/admin/schools/1/deputies/{deputy_id}",
        headers=auth(atok),
        json={"permission_keys": ["view_school_analytics"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["deputy"]["permission_keys"] == ["view_school_analytics"]

    # قاعده طلایی: معاونی با مجوزی که مدیر مدرسه خودش ندارد
    r = await client.post(
        "/admin/schools/1/deputies",
        headers=auth(atok),
        json={"title_fa": "معاون اجرایی", "permission_keys": ["manage_schools"]},
    )
    assert r.status_code == 200, r.text
    deputy2_id = r.json()["deputy"]["id"]

    r = await client.post(
        f"/admin/schools/1/deputies/{deputy2_id}/assign-user",
        headers=auth(atok),
        json={"user_id": teacher2.id},
    )
    assert r.status_code == 403, r.text

    denied = await audit_rows("delegation_denied_insufficient_owner_permission")
    assert any(d and "manage_schools" in d for _, d in denied)

    # هیچ مجوز و هیچ تخصیصی برای کاربر دوم ساخته نشده
    async with AsyncSessionLocal() as s:
        pa = (
            await s.execute(
                select(PermissionAssignment).where(PermissionAssignment.user_id == teacher2.id)
            )
        ).scalars().all()
        assert pa == []
        deputy_assign = (
            await s.execute(
                select(SchoolAssignment).where(
                    SchoolAssignment.role == "deputy",
                    SchoolAssignment.employee_id.in_(
                        select(Employee.id).where(Employee.user_id == teacher2.id)
                    ),
                )
            )
        ).scalars().all()
        assert deputy_assign == []

    t2tok = await login(client, "teacher2")
    r = await client.get("/admin/school/1/overview", headers=auth(t2tok))
    assert r.status_code == 403

    # حذف نرم
    r = await client.delete(f"/admin/schools/1/deputies/{deputy_id}", headers=auth(atok))
    assert r.status_code == 200, r.text
    assert r.json()["deputy"]["is_active"] is False

    # معاون غیرفعال قابل اتصال نیست
    r = await client.post(
        f"/admin/schools/1/deputies/{deputy_id}/assign-user",
        headers=auth(atok),
        json={"user_id": teacher2.id},
    )
    assert r.status_code == 400


# ------------------------- §10 انتقال کارکنان -------------------------


@pytest.mark.anyio
async def test_teacher_transfer_closes_old_assignment(client, seeded):
    """انتقال بین مدرسه‌ها: تخصیص قدیمی بسته، تخصیص جدید ساخته می‌شود و
    اسناد تاریخی (snapshot پاسخ‌ها) هرگز تغییر نمی‌کنند."""
    atok = await login(client, "schooladmin")
    dtok = await login(client, "districtadmin")

    async with AsyncSessionLocal() as s:
        teacher1 = await one(s, User, username="teacher1")
        student1 = await one(s, User, username="student1")
        assignment = (
            await s.execute(
                select(SchoolAssignment)
                .join(Employee, Employee.id == SchoolAssignment.employee_id)
                .where(
                    Employee.user_id == teacher1.id,
                    SchoolAssignment.role == "teacher",
                    SchoolAssignment.school_id == 1,
                )
            )
        ).scalars().one()
        assignment_id = assignment.id

        exam_item = (await s.execute(select(ExamItem).limit(1))).scalars().one()
        attempt = ExamAttempt(exam_id=exam_item.exam_id, student_user_id=student1.id, status="graded")
        s.add(attempt)
        await s.flush()
        answer = AttemptAnswer(
            attempt_id=attempt.id,
            exam_item_id=exam_item.id,
            student_user_id=student1.id,
            selected_option="A",
            is_correct=1,
            school_id=1,
            class_id=1,
            district_id=1,
            province_id=1,
        )
        s.add(answer)
        await s.commit()
        answer_id = answer.id

    # مدیر مدرسه فقط حوزه مدرسه ۱ را دارد → 403
    r = await client.post(
        f"/admin/school-assignments/{assignment_id}/transfer",
        headers=auth(atok),
        json={"new_school_id": 2},
    )
    assert r.status_code == 403, r.text

    # مدیر ناحیه هر دو مدرسه را می‌پوشاند → 200
    r = await client.post(
        f"/admin/school-assignments/{assignment_id}/transfer",
        headers=auth(dtok),
        json={"new_school_id": 2, "subject": "physics"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["old_assignment_id"] == assignment_id
    assert body["status"] == "ended"

    async with AsyncSessionLocal() as s:
        old = await s.get(SchoolAssignment, assignment_id)
        assert old.status == "ended"
        assert old.end_date is not None
        new = await s.get(SchoolAssignment, body["new_assignment_id"])
        assert new.school_id == 2
        assert new.status == "active"
        assert new.subject == "physics"
        assert new.employee_id == old.employee_id

        # snapshot سند تاریخی دست‌نخورده ماند
        frozen = await s.get(AttemptAnswer, answer_id)
        assert frozen.school_id == 1
        assert frozen.class_id == 1
        assert frozen.district_id == 1
        assert frozen.province_id == 1

    transferred = await audit_rows("school_assignment_transferred")
    assert any(d and "from=1 to=2" in d for _, d in transferred)

    # تخصیص بسته دیگر قابل انتقال نیست
    r = await client.post(
        f"/admin/school-assignments/{assignment_id}/transfer",
        headers=auth(dtok),
        json={"new_school_id": 2},
    )
    assert r.status_code == 400

    # مدرسه مقصد ناموجود → 404
    r = await client.post(
        f"/admin/school-assignments/{body['new_assignment_id']}/transfer",
        headers=auth(dtok),
        json={"new_school_id": 999},
    )
    assert r.status_code == 404
