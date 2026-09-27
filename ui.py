"""UI-хелперы: карточки задач и инлайн-клавиатуры."""
from __future__ import annotations

from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from models import Task

MSK = ZoneInfo("Europe/Moscow")


def fmt_dt(dt: datetime, tz: ZoneInfo = MSK) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz).strftime("%d.%m.%Y %H:%M")


def task_card(task: Task) -> str:
    parts = [
        f"📌 {task.task_id}: {task.title}",
        f"👤 Исполнитель: {task.assignee}",
        f"🗓 Дедлайн: {fmt_dt(task.deadline)}",
        f"Статус: {task.status}",
    ]
    if task.description:
        parts.append(f"🗒 {task.description[:300]}")
    return "\n".join(parts)


def task_kb(task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Готово", callback_data=f"task:done:{task_id}"),
        InlineKeyboardButton("🚧 В работе", callback_data=f"task:wip:{task_id}"),
    ]])