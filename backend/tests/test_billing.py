"""تست‌های بخش مالی (سند پنل والدین §18 + تصمیم باز §10.۲ سند دانش‌آموز):
ثبت پرداخت خارج از سیستم، فاکتور، بسته جلسات، بازپرداخت و گاردهای نقش/دامنه."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_billing.db")

import re
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.db import AsyncSessionLocal, Base, engine
from app.main import app
from app.models.billing import PaymentTransaction, RefundRequest, SessionPack
from app.models.org import User
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
        return (await s.execute(select(User.id).where(User.username == username))).scalar_one()


async def raw_payment(student_id: int, tutor_id: int, *, amount=500_000, status="paid", payer_id=None):
    """ثبت مستقیم ردیف پرداخت (مثل داده‌ی موجود) — برای تست دامنه/وضعیت‌ها."""
    async with AsyncSessionLocal() as s:
        row = PaymentTransaction(
            payer_user_id=payer_id if payer_id is not None else student_id,
            student_user_id=student_id,
            tutor_user_id=tutor_id,
            amount=amount,
            status=status,
            paid_at=datetime.now(timezone.utc).replace(tzinfo=None) if status == "paid" else None,
        )
        s.add(row)
        await s.flush()
        row.invoice_no = f"INV-{row.id:06d}"
        await s.commit()
        return row.id


async def raw_pack(student_id: int, tutor_id: int, *, total=3, subject="math"):
    async with AsyncSessionLocal() as s:
        row = SessionPack(
            student_user_id=student_id,
            tutor_user_id=tutor_id,
            subject=subject,
            total_sessions=total,
            used_sessions=0,
            price_per_session=400_000,
            status="active",
        )
        s.add(row)
        await s.commit()
        return row.id


# ------------------------- (۱) نمای مالی والد فقط فرزندان متصل -------------------------


@pytest.mark.anyio
async def test_parent_overview_scoped_to_linked_children(client, seeded):
    tok = await login(client, "parent1")
    student1 = await user_id("student1")  # متصل به parent1
    student2 = await user_id("student2")  # بدون پیوند با parent1
    tutor1 = await user_id("tutor1")

    # داده‌هایی که نباید دیده شوند: بسته و پرداخت فرزندِ غیرمتصل
    await raw_pack(student2, tutor1, total=5)
    await raw_payment(student2, tutor1, amount=900_000)

    # یک پرداخت معتبر برای فرزند متصل
    r = await client.post(
        "/billing/payments",
        headers=auth(tok),
        json={
            "student_user_id": student1,
            "tutor_user_id": tutor1,
            "amount": 1_600_000,
            "session_count": 4,
            "subject": "math",
        },
    )
    assert r.status_code == 200, r.text

    r = await client.get("/billing/parent/overview", headers=auth(tok))
    assert r.status_code == 200, r.text
    data = r.json()

    # فقط فرزند متصل
    assert [c["id"] for c in data["children"]] == [student1]
    assert data["packs"], "بسته‌ی ساخته‌شده برای student1 باید دیده شود"
    for p in data["packs"]:
        assert p["student_user_id"] == student1
        assert p["remaining"] == p["purchased"] - p["used"]
    assert data["payments"], "پرداخت ثبت‌شده باید در تاریخچه باشد"
    for pay in data["payments"]:
        assert pay["student_user_id"] != student2
        assert pay["payer_user_id"] != student2

    # یادداشت حالت پرداخت §10.۲ + برچسب فارسی وضعیت
    assert data["payment_mode"] == "external"
    assert "گزینه الف" in data["mode_note_fa"] and "۱۰.۲" in data["mode_note_fa"]
    assert "۱۰.۲" in data["note_fa"]
    assert any(p["status_fa"] == "پرداخت‌شده" for p in data["payments"])
    assert data["stats"]["sessions_remaining"] == sum(p["remaining"] for p in data["packs"])

    # پرداخت فرزندِ غیرمتصل اصلاً وارد تاریخچه نمی‌شود
    assert all(p["invoice_no"] for p in data["payments"])


# ------------------------- (۲) ثبت پرداخت خارج از سیستم + فاکتور -------------------------


@pytest.mark.anyio
async def test_record_external_payment_creates_invoice(client, seeded):
    tok = await login(client, "parent1")
    student1 = await user_id("student1")
    tutor1 = await user_id("tutor1")

    r = await client.post(
        "/billing/payments",
        headers=auth(tok),
        json={
            "student_user_id": student1,
            "tutor_user_id": tutor1,
            "amount": 1_600_000,
            "session_count": 4,
            "subject": "math",
            "description": "۴ جلسه ریاضی — پرداخت حضوری",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert re.fullmatch(r"INV-\d{6}", body["invoice_no"]), body["invoice_no"]
    assert body["status"] == "paid"
    assert body["status_fa"] == "پرداخت‌شده"
    assert body["method"] == "external"
    assert body["session_pack_id"]

    # ردیف دیتابیس: روش external (§10.۲) و فاکتور پایدار
    async with AsyncSessionLocal() as s:
        pay = await s.get(PaymentTransaction, body["payment_id"])
        assert pay is not None
        assert pay.method == "external" and pay.status == "paid"
        assert pay.invoice_no == body["invoice_no"]
        assert pay.paid_at is not None

    # نمای فاکتور برای خودِ والد
    r = await client.get(f"/billing/payments/{body['payment_id']}", headers=auth(tok))
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["payment"]["invoice_no"] == body["invoice_no"]
    assert detail["payment"]["method_fa"] == "خارج از سیستم"
    assert detail["pack"] and detail["pack"]["purchased"] == 4

    # بسته‌ی خریداری‌شده در فهرست بسته‌ها
    r = await client.get("/billing/packs", headers=auth(tok))
    assert r.status_code == 200, r.text
    packs = r.json()["packs"]
    match = [p for p in packs if p["id"] == body["session_pack_id"]]
    assert match and match[0]["tutor_user_id"] == tutor1
    assert match[0]["purchased"] == 4 and match[0]["used"] == 0 and match[0]["remaining"] == 4


# ------------------------- (۳) والدِ بدون پیوند ⇒ 403 در همه‌جا -------------------------


@pytest.mark.anyio
async def test_unlinked_parent_gets_403(client, seeded):
    tok = await login(client, "parent1")
    student2 = await user_id("student2")
    tutor1 = await user_id("tutor1")
    pay_id = await raw_payment(student2, tutor1, amount=700_000)

    # ثبت پرداخت برای دانش‌آموز غیرمتصل
    r = await client.post(
        "/billing/payments",
        headers=auth(tok),
        json={"student_user_id": student2, "tutor_user_id": tutor1, "amount": 700_000},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "این دانش‌آموز به شما متصل نیست"

    # دیدن فاکتور فرزندِ غیرمتصل
    r = await client.get(f"/billing/payments/{pay_id}", headers=auth(tok))
    assert r.status_code == 403

    # درخواست بازپرداخت روی همان پرداخت
    r = await client.post(
        f"/billing/payments/{pay_id}/refund", headers=auth(tok), json={"reason": "جلسه برگزار نشد"}
    )
    assert r.status_code == 403

    # و در نمای کلان هم دیده نمی‌شود
    r = await client.get("/billing/parent/overview", headers=auth(tok))
    assert r.status_code == 200
    assert all(p["id"] != pay_id for p in r.json()["payments"])

    # شناسه ناشناس هم طبق قرارداد پلتفرم 403 می‌دهد (نه 404)
    r = await client.get("/billing/payments/999999", headers=auth(tok))
    assert r.status_code == 403


# ------------------------- (۴) بازپرداخت + جلوگیری از تکرار (409) -------------------------


@pytest.mark.anyio
async def test_refund_request_and_duplicate(client, seeded):
    tok = await login(client, "parent1")
    student1 = await user_id("student1")
    tutor1 = await user_id("tutor1")

    r = await client.post(
        "/billing/payments",
        headers=auth(tok),
        json={"student_user_id": student1, "tutor_user_id": tutor1, "amount": 400_000},
    )
    assert r.status_code == 200, r.text
    pay_id = r.json()["payment_id"]

    r = await client.post(
        f"/billing/payments/{pay_id}/refund",
        headers=auth(tok),
        json={"reason": "جلسه لغو شد و برگزار نشد"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["status"] == "requested"
    assert body["status_fa"] == "درخواست‌شده"

    # تکراری ⇒ 409 (قرارداد مخزن: پذیرش/سؤال تکراری هم 409 است)
    r = await client.post(
        f"/billing/payments/{pay_id}/refund", headers=auth(tok), json={"reason": "دوباره"}
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "درخواست بازپرداخت تکراری است"

    # بازپرداخت روی پرداختِ غیرپرداخت‌شده مجاز نیست
    pending_id = await raw_payment(student1, tutor1, amount=100_000, status="pending")
    r = await client.post(
        f"/billing/payments/{pending_id}/refund", headers=auth(tok), json={"reason": "آزمایشی"}
    )
    assert r.status_code == 400

    # درخواست در نمای کلان والد دیده می‌شود
    r = await client.get("/billing/parent/overview", headers=auth(tok))
    assert r.status_code == 200
    refunds = r.json()["refunds"]
    assert len(refunds) == 1
    assert refunds[0]["payment_id"] == pay_id
    assert refunds[0]["status_fa"] == "درخواست‌شده"
    assert refunds[0]["invoice_no"]

    async with AsyncSessionLocal() as s:
        assert (await s.execute(select(RefundRequest))).scalars().first() is not None


# ------------------------- (۵) مصرف جلسه از بسته + سقف بسته -------------------------


@pytest.mark.anyio
async def test_tutor_uses_pack_and_limit(client, seeded):
    tok = await login(client, "parent1")
    student1 = await user_id("student1")
    tutor1 = await user_id("tutor1")
    teacher2 = await user_id("teacher2")

    r = await client.post(
        "/billing/payments",
        headers=auth(tok),
        json={
            "student_user_id": student1,
            "tutor_user_id": tutor1,
            "amount": 800_000,
            "session_count": 2,
            "subject": "math",
        },
    )
    assert r.status_code == 200, r.text
    pack_id = r.json()["session_pack_id"]
    assert pack_id

    # معلمِ غیرمالک بسته ⇒ 403 (گارد پیش از چک وجود)
    t2 = await login(client, "teacher2")
    r = await client.post(f"/billing/packs/{pack_id}/use", headers=auth(t2))
    assert r.status_code == 403

    # والد اجازه مصرف ندارد
    r = await client.post(f"/billing/packs/{pack_id}/use", headers=auth(tok))
    assert r.status_code == 403

    t1 = await login(client, "tutor1")
    r = await client.post(f"/billing/packs/{pack_id}/use", headers=auth(t1))
    assert r.status_code == 200, r.text
    assert r.json()["used"] == 1 and r.json()["remaining"] == 1

    r = await client.post(f"/billing/packs/{pack_id}/use", headers=auth(t1))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["used"] == 2 and body["remaining"] == 0
    assert body["status"] == "exhausted" and body["status_fa"] == "تمام‌شده"

    # فراتر از تعداد خریداری‌شده ممنوع
    r = await client.post(f"/billing/packs/{pack_id}/use", headers=auth(t1))
    assert r.status_code == 400
    assert "همه جلسات" in r.json()["detail"]

    # دیتابیس: used_sessions هرگز بیشتر از total_sessions نیست
    async with AsyncSessionLocal() as s:
        pack = await s.get(SessionPack, pack_id)
        assert pack.used_sessions == pack.total_sessions == 2


# ------------------------- (۶) گاردهای نقش -------------------------


@pytest.mark.anyio
async def test_role_guards(client, seeded):
    student_tok = await login(client, "student1")
    parent_tok = await login(client, "parent1")
    admin_tok = await login(client, "schooladmin")

    # دانش‌آموز به نمای مالی والد دسترسی ندارد
    r = await client.get("/billing/parent/overview", headers=auth(student_tok))
    assert r.status_code == 403

    # والد به دریافتی‌های معلم دسترسی ندارد
    r = await client.get("/billing/tutor/earnings", headers=auth(parent_tok))
    assert r.status_code == 403

    # مدیر مدرسه هم نقش معلم نیست
    r = await client.get("/billing/tutor/earnings", headers=auth(admin_tok))
    assert r.status_code == 403

    # دانش‌آموز اجازه ثبت پرداخت/دیدن بسته را ندارد
    r = await client.post(
        "/billing/payments",
        headers=auth(student_tok),
        json={"student_user_id": 1, "tutor_user_id": 1, "amount": 1000},
    )
    assert r.status_code == 403
    r = await client.get("/billing/packs", headers=auth(student_tok))
    assert r.status_code == 403

    # بدون توکن ⇒ 401
    r = await client.get("/billing/parent/overview")
    assert r.status_code == 401


# ------------------------- (۷) دریافتی‌های معلم -------------------------


@pytest.mark.anyio
async def test_tutor_earnings(client, seeded):
    tok = await login(client, "parent1")
    student1 = await user_id("student1")
    tutor1 = await user_id("tutor1")

    r = await client.post(
        "/billing/payments",
        headers=auth(tok),
        json={
            "student_user_id": student1,
            "tutor_user_id": tutor1,
            "amount": 1_200_000,
            "session_count": 3,
            "subject": "math",
        },
    )
    assert r.status_code == 200, r.text

    t1 = await login(client, "tutor1")
    r = await client.get("/billing/tutor/earnings", headers=auth(t1))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_earned"] == 1_200_000
    assert data["payments_count"] >= 1
    paid = [b for b in data["by_status"] if b["status"] == "paid"]
    assert paid and paid[0]["total"] == 1_200_000
    assert paid[0]["status_fa"] == "پرداخت‌شده"
    assert "خارج از سیستم" in data["note_fa"]

    # معلمِ بدون تراکنش ⇒ اعداد صفر، نه خطا
    t2 = await login(client, "teacher2")
    r = await client.get("/billing/tutor/earnings", headers=auth(t2))
    assert r.status_code == 200, r.text
    empty = r.json()
    assert empty["total_earned"] == 0 and empty["payments_count"] == 0
