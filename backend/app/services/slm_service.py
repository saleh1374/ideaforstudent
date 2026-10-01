"""SLM state updates: turn raw evidence rows into per-topic state."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.slm import Evidence, StudentTopicState
from app.services.slm import (
    EvidenceRecord,
    effective_mastery,
    mastery,
    next_stability,
    retention,
    status_of,
)


def _to_record(e: Evidence, now: datetime) -> EvidenceRecord:
    occ = e.occurred_at if e.occurred_at.tzinfo is None else e.occurred_at.astimezone(timezone.utc).replace(tzinfo=None)
    now_naive = now if now.tzinfo is None else now.astimezone(timezone.utc).replace(tzinfo=None)
    days_ago = max(0.0, (now_naive - occ).total_seconds() / 86400.0)
    return EvidenceRecord(
        weight=e.weight,
        difficulty=e.difficulty_weight,
        partial_credit=e.partial_credit,
        days_ago=days_ago,
    )


async def update_states_from_evidence(db: AsyncSession, student_user_id: int) -> None:
    """Recompute M, S, R, E for every topic that has evidence for this student.
    History keeps every update (student spec §2.2 «فقط با همین تاریخچه قابل
    تشخیص است»)."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    evidences = (
        (
            await db.execute(
                select(Evidence).where(Evidence.student_user_id == student_user_id).order_by(Evidence.occurred_at)
            )
        )
        .scalars()
        .all()
    )
    by_topic: dict[int, list[Evidence]] = {}
    for e in evidences:
        by_topic.setdefault(e.topic_id, []).append(e)

    states = {
        s.topic_id: s
        for s in (
            await db.execute(select(StudentTopicState).where(StudentTopicState.student_user_id == student_user_id))
        ).scalars()
    }

    for topic_id, evs in by_topic.items():
        state = states.get(topic_id)
        if state is None:
            state = StudentTopicState(student_user_id=student_user_id, topic_id=topic_id)
            db.add(state)
            states[topic_id] = state

        # chronological stability walk (S updates per evidence)
        s_val = float(settings.stability_initial_days)
        for e in evs:
            successful = e.partial_credit >= settings.success_threshold
            s_val = next_stability(s_val, successful)

        records = [_to_record(e, now) for e in evs]
        m = mastery(records)
        last = max(evs, key=lambda e: e.occurred_at.replace(tzinfo=None) if e.occurred_at.tzinfo else e.occurred_at)
        last_at = last.occurred_at if last.occurred_at.tzinfo is None else last.occurred_at.astimezone(timezone.utc).replace(tzinfo=None)
        now_naive = now if now.tzinfo is None else now.astimezone(timezone.utc).replace(tzinfo=None)
        days_since = max(0.0, (now_naive - last_at).total_seconds() / 86400.0)
        r = retention(days_since, s_val)
        eff = effective_mastery(m, r)
        prev_status = status_of(state.effective_mastery or 0.0, state.evidence_count or 0)

        state.mastery = m
        state.stability = round(s_val, 3)
        state.retention = round(r, 4)
        state.effective_mastery = eff
        state.evidence_count = len(evs)
        state.last_evidence_at = last.occurred_at
        state.last_state_change = now
        state.history = list(state.history or []) + [
            {
                "at": now.isoformat(),
                "m": m,
                "e": eff,
                "s": round(s_val, 3),
                "evidence_count": len(evs),
                "prev_status": prev_status,
                "status": status_of(eff, len(evs)),
            }
        ]
