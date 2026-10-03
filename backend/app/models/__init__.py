"""Import all model modules so Base.metadata knows every table
(required before init_models / create_all)."""
from app.models import (  # noqa: F401
    assistant,
    assessment,
    catalog,
    content,
    district_reports,
    employment,
    gamification,
    org,
    parent_panel,
    parent_reports,
    plan_control,
    rbac,
    school_ops,
    slm,
    stats,
    teacher_assessment,
    tutoring,
)
