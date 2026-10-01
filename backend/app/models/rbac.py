"""RBAC core: Role + Permission + Scope + Assignment + Delegation
(RBAC spec §7, §8). Golden rule enforced in service layer:
Delegated Permission ≤ Owner Permission."""
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(50), unique=True)  # e.g. school_admin, deputy
    title_fa: Mapped[str] = mapped_column(String(100))

    permissions = relationship("RolePermission", back_populates="role")


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    # e.g. view_students, analyze_assessments, view_ai_conversations, manage_employment
    title_fa: Mapped[str] = mapped_column(String(150))


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    permission_id: Mapped[int] = mapped_column(ForeignKey("permissions.id"))

    role = relationship("Role", back_populates="permissions")
    permission = relationship("Permission")


class PermissionAssignment(Base):
    """Binds a user to role+permission in a concrete scope, with delegation
    info and optional time validity (RBAC spec §7, §9)."""

    __tablename__ = "permission_assignments"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "permission_id", "scope_type", "scope_id", name="uq_perm_assignment"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    permission_id: Mapped[int] = mapped_column(ForeignKey("permissions.id"))
    scope_type: Mapped[str] = mapped_column(String(20))
    # province | district | school | class | student | national
    scope_id: Mapped[int] = mapped_column(Integer)
    delegated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    valid_from: Mapped[Date | None] = mapped_column(Date)
    valid_until: Mapped[Date | None] = mapped_column(Date)  # auto-expiring grants (spec §9)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class AuditLog(Base):
    """Every access/permission change is recorded (RBAC spec §8, §17)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60))
    # permission_granted, permission_revoked, delegation_denied_insufficient_owner_permission,
    # employment_request_approved, student_viewed, ...
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
