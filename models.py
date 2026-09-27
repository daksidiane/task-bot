"""Модели данных: задача и журнал."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")


def _to_msk(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=MSK)
    return dt.astimezone(MSK)


def _now() -> datetime:
    return datetime.now(MSK)


@dataclass
class Task:
    task_id: str
    title: str
    description: str
    assignee: str
    assignee_id: int | None
    created_by: int
    deadline: datetime
    status: str = "new"               # new | in_progress | done | overdue | cancelled
    reminded_before: bool = False
    reminded_at_deadline: bool = False
    escalation_sent: bool = False
    missed: int = 0
    created_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "assignee": self.assignee,
            "assignee_id": self.assignee_id,
            "created_by": self.created_by,
            "deadline": _to_msk(self.deadline).isoformat(),
            "status": self.status,
            "reminded_before": self.reminded_before,
            "reminded_at_deadline": self.reminded_at_deadline,
            "escalation_sent": self.escalation_sent,
            "missed": self.missed,
            "created_at": _to_msk(self.created_at).isoformat(),
        }

    @staticmethod
    def from_dict(d: dict) -> "Task":
        dl_raw = d["deadline"]
        dl = datetime.fromisoformat(dl_raw) if isinstance(dl_raw, str) else dl_raw
        cr_raw = d.get("created_at")
        cr = datetime.fromisoformat(cr_raw) if isinstance(cr_raw, str) else (cr_raw or _now())
        return Task(
            task_id=d["task_id"],
            title=d.get("title", ""),
            description=d.get("description", ""),
            assignee=d.get("assignee", ""),
            assignee_id=d.get("assignee_id"),
            created_by=d["created_by"],
            deadline=_to_msk(dl),
            status=d.get("status", "new"),
            reminded_before=d.get("reminded_before", False),
            reminded_at_deadline=d.get("reminded_at_deadline", False),
            escalation_sent=d.get("escalation_sent", False),
            missed=d.get("missed", 0),
            created_at=_to_msk(cr),
        )