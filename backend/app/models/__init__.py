"""Import all model modules so Base.metadata knows every table
(required before init_models / create_all)."""
from app.models import assessment, catalog, employment, org, rbac, slm  # noqa: F401
