"""Import all model modules so Base.metadata knows every table
(required before init_models / create_all)."""
from app.models import (  # noqa: F401
    assistant,
    assessment,
    catalog,
    employment,
    org,
    rbac,
    slm,
    stats,
    teacher_assessment,
    tutoring,
)
