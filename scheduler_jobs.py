"""Фоновые проверки дедлайнов: напоминания, запрос в момент дедлайна, эскалация.

Аналог Cron-workflow из n8n (F5/F6 ТЗ), встроенный в бота.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from ui import task_card, task_kb

log = logging.getLogger(__name__)


def _cfg(context): return context.bot_data["cfg"]
def _storage(context): return context.bot_data["storage"]


async def _notify_executor(context, task, text: str):
    if not task.assignee_id:
        return
    try:
        await context.bot.send_message(
            chat_id=task.assignee_id,
            text=f"{text}\n\n{task_card(task)}\nОтчитаться: кнопкой или /done {task.task_id}",
            reply_markup=task_kb(task.task_id),
        )
    except Exception as exc:
        log.warning("Не удалось уведомить исполнителя %s: %s", task.assignee_id, exc)


async def check_deadlines(context) -> None:
    cfg = _cfg(context)
    storage = _storage(context)
    now = datetime.now(cfg.tz)
    before_h = timedelta(hours=cfg.remind_hours_before)
    at_deadline_window = timedelta(minutes=15)

    for task in storage.list_tasks():
        if task.status in ("done", "cancelled", "in_progress"):
            continue
        delta = task.deadline - now

        if not task.reminded_before and at_deadline_window < delta <= before_h:
            hours = max(1, int(delta.total_seconds() // 3600) + 1)
            storage.update_task(task.task_id, reminded_before=True)
            storage.add_journal("reminder_before", task_id=task.task_id, hours=hours)
            await _notify_executor(context, task, f"⏰ Напоминание: до дедлайна ~{hours} ч.")

        if not task.reminded_at_deadline and timedelta(0) <= delta <= at_deadline_window:
            storage.update_task(task.task_id, reminded_at_deadline=True)
            storage.add_journal("reminder_at_deadline", task_id=task.task_id)
            await _notify_executor(context, task, "⛔ Дедлайн наступил. Отчитайся о статусе!")

        if delta < timedelta(0):
            overdue_min = (now - task.deadline).total_seconds() / 60
            if task.missed == 0:
                storage.update_task(task.task_id, missed=1)
                storage.add_journal("deadline_missed", task_id=task.task_id, minutes=int(overdue_min))
                await _notify_executor(context, task, "⛔ Задача просрочена. Жду отчёт!")
            elif (
                task.missed == 1
                and overdue_min >= cfg.escalate_after_minutes
                and not task.escalation_sent
            ):
                storage.update_task(task.task_id, escalation_sent=True, missed=2)
                storage.add_journal(
                    "escalation", task_id=task.task_id, minutes=int(overdue_min)
                )
                try:
                    await context.bot.send_message(
                        chat_id=task.created_by,
                        text=(
                            f"🚨 Эскалация: {task.task_id} «{task.title}» просрочена "
                            f"на {int(overdue_min)} мин.\n"
                            f"Исполнитель: {task.assignee}.\n"
                            f"/tasks — посмотреть задачи."
                        ),
                    )
                except Exception as exc:
                    log.warning("Не удалось отправить эскалацию заказчику: %s", exc)