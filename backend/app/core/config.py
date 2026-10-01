from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration — every pedagogical constant is a tunable parameter
    (spec: «مقدارهای عددی فقط فرض هستند و باید قابل تنظیم باشند»)."""

    app_name: str = "Daneshyar API"
    debug: bool = True

    database_url: str = "sqlite+aiosqlite:///./daneshyar.db"
    secret_key: str = "dev-secret-change-me"

    # SLM parameters (spec §2.3 + Appendix A)
    lambda_decay: float = 0.85          # evidence decay over 30 days
    stability_initial_days: float = 4.0  # S0
    stability_success_factor: float = 1.8
    stability_fail_factor: float = 0.5
    stability_fail_floor: float = 2.0
    retention_floor_factor: float = 0.6  # E = M * (floor + (1-floor) * R)
    evidence_min_for_status: int = 3     # fewer evidences => "unknown"
    success_threshold: float = 0.75      # c_i >= this counts as successful retrieval

    # Status thresholds on effective mastery E (spec fig.1 / appendix A)
    threshold_mastered: float = 85.0
    threshold_consolidating: float = 65.0
    threshold_weak: float = 40.0

    # Root-cause prerequisite threshold (teacher spec §4)
    prerequisite_mastery_threshold: float = 65.0

    # Spaced review ladder in days (spec §2.4)
    review_ladder_days: str = "1,3,7,14,30,60,120"

    # Grading / errors
    slow_answer_ms: int = 150_000        # => "time" cause
    low_confidence: int = 2              # confidence 1..5 below this => careless hint

    # Privacy
    min_group_size: int = 10             # stats suppressed below this (spec §8.2)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
