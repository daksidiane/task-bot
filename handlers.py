"""Telegram-обработчики: роли, создание задач, отчёты, журнал, сотрудники."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

from ai_extract import parse_deadline
from models import Task
from stt import transcribe
from ui import fmt_dt, task_card, task_kb

log = logging.getLogger(__name__)

ROLE_NAMES = {
    "admin": "🛡 Администратор",
    "customer": "🧑‍💼 Заказчик",
    "employee": "👷 Исполнитель",
    "none": "гость",
}

MENU_LABELS = {
    "new": "➕ Создать задачу",
    "tasks": "📋 Мои задачи",
    "log": "🗒 Журнал действий",
    "help": "❓ Как пользоваться",
    "myid": "🆔 Мой ID",
    "reset": "🚫 Сбросить",
    "staff": "👥 Управление сотрудниками",
}
_MENU_BY_LABEL = {label: key for key, label in MENU_LABELS.items()}


def menu_kb(role: str) -> ReplyKeyboardMarkup:
    L = MENU_LABELS
    if role == "employee":
        rows = [
            [L["tasks"], L["myid"]],
            [L["help"], L["reset"]],
        ]
    else:
        rows = [
            [L["new"], L["tasks"]],
            [L["log"], L["help"]],
            [L["myid"], L["reset"]],
        ]
        if role == "admin":
            rows.append([L["staff"]])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def _cfg(context): return context.bot_data["cfg"]
def _storage(context): return context.bot_data["storage"]
def _extractor(context): return context.bot_data["extractor"]


def _role_of(user_id: int, cfg, storage) -> str:
    if user_id in cfg.admin_ids:
        return "admin"
    if user_id in cfg.customer_ids:
        return "customer"
    if any(e["tg_id"] == user_id for e in storage.get_employees()):
        return "employee"
    return "none"


def _can_create(role: str) -> bool:
    return role in ("admin", "customer")


def _same_id(a, b) -> bool:
    try:
        return int(a) == int(b)
    except (TypeError, ValueError):
        return False


def _journal_meta(entry: dict) -> dict:
    meta = entry.get("meta") or {}
    if isinstance(meta, dict):
        return meta
    if isinstance(meta, str) and meta:
        try:
            parsed = json.loads(meta)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _next_task_id(storage) -> str:
    max_n = 0
    for t in storage.list_tasks():
        tid = t.task_id
        if tid.startswith("T-"):
            try:
                max_n = max(max_n, int(tid[2:]))
            except ValueError:
                pass
    return f"T-{max_n + 1:06d}"


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Подтвердить", callback_data="flow:confirm"),
        InlineKeyboardButton("✏️ Редактировать", callback_data="flow:edit"),
        InlineKeyboardButton("❌ Отмена", callback_data="flow:cancel"),
    ]])


def _employees_kb(names: list[str], suggested: str | None) -> InlineKeyboardMarkup:
    rows = []
    for idx, name in enumerate(names):
        label = name
        if suggested and suggested.strip().lower() == name.strip().lower():
            label = f"⭐ {name}"
        rows.append([InlineKeyboardButton(label, callback_data=f"emp:{idx}")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="flow:cancel")])
    return InlineKeyboardMarkup(rows)


def _confirm_text(parsed: dict) -> str:
    smart = (parsed.get("smart") or "").strip()
    title = (parsed.get("title") or "").strip() or "без названия"
    desc = (parsed.get("description") or "").strip()
    assignee = parsed.get("assignee") or "не определён"
    dl = parsed.get("deadline") or parsed.get("deadline_iso") or "не определён"
    source = "🧠 LLM (Ollama)" if parsed.get("source") == "llm" else "⚙️ локальный разбор"

    parts = [
        f"📝 Название: {title}",
    ]
    if desc and desc.lower() != title.lower():
        parts.append(f"🗒 Описание: {desc}")
    if smart:
        parts.append(f"🎯 SMART-цель:\n{smart}")
    parts.append(f"👤 Исполнитель: {assignee}")
    parts.append(f"🗓 Дедлайн: {dl}")
    parts.append(f"\n({source}) Подтверди создание:")

    return "\n\n".join(parts)


# --- Создание задачи ---------------------------------------------------------

async def _start_task(update, context, raw_text: str):
    ud = context.user_data
    cfg, storage, extractor = _cfg(context), _storage(context), _extractor(context)
    if not _can_create(_role_of(update.effective_user.id, cfg, storage)):
        await update.effective_message.reply_text("⛔ Создавать задачи может только заказчик или администратор.")
        return
    raw_text = (raw_text or "").strip()[:4000]
    employees = storage.get_employees()
    waiting = await update.effective_message.reply_text("⏳ Распознаю задачу…")
    try:
        parsed = await asyncio.to_thread(extractor.extract, raw_text, employees)
    except Exception:
        log.exception("Не удалось разобрать задачу")
        parsed = None
    if not parsed:
        await waiting.edit_text("Не удалось разобрать задачу. Попробуй сформулировать иначе.")
        return
    ud["pending_raw"] = raw_text
    ud["pending_parsed"] = parsed
    ud["flow"] = "confirm"
    await waiting.edit_text(_confirm_text(parsed), reply_markup=_confirm_kb())


async def _create_task(update, context, deadline: datetime):
    ud = context.user_data
    cfg, storage = _cfg(context), _storage(context)
    parsed = ud.get("pending_parsed") or {}
    assignee_name = ud.get("assignee_name", "")
    assignee_id = ud.get("assignee_id")
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=cfg.tz)
    else:
        deadline = deadline.astimezone(cfg.tz)

    task = Task(
        task_id=_next_task_id(storage),
        title=(parsed.get("title") or "Задача")[:300],
        description=(parsed.get("description") or parsed.get("smart") or "")[:2000],
        assignee=assignee_name,
        assignee_id=assignee_id,
        created_by=update.effective_user.id,
        deadline=deadline,
        status="new",
        created_at=datetime.now(cfg.tz),
    )
    storage.add_task(task)
    storage.add_journal(
        "task_created", task_id=task.task_id, title=task.title,
        assignee=task.assignee, deadline=task.deadline.isoformat(),
        created_by=task.created_by,
    )
    if task.assignee_id:
        try:
            await context.bot.send_message(
                chat_id=task.assignee_id,
                text=f"📥 Новая задача!\n\n{task_card(task)}\n\nОтчитаться: кнопкой или /done {task.task_id}",
                reply_markup=task_kb(task.task_id),
            )
            storage.add_journal("notified_executor", task_id=task.task_id)
        except Exception as exc:
            err_msg = re.sub(r"bot\d+:[A-Za-z0-9_-]+|\b\d{8,10}:[A-Za-z0-9_-]{30,}\b", "<REDACTED_TOKEN>", str(exc))
            log.warning("Не удалось уведомить исполнителя %s: %s", task.assignee_id, err_msg)
            storage.add_journal("notify_error", task_id=task.task_id, error=err_msg[:200])
    await update.effective_message.reply_text(
        f"✅ Задача {task.task_id} создана и назначена на «{assignee_name}».\nДедлайн: {fmt_dt(deadline)}."
    )
    ud.clear()


async def _flow_confirm(query, update, context):
    ud = context.user_data
    storage = _storage(context)
    employees = storage.get_employees()
    if not employees:
        await query.message.reply_text("Список сотрудников пуст. Админ может добавить: /staff")
        ud.clear()
        return
    names = [e["name"] for e in employees]
    suggested = (ud.get("pending_parsed") or {}).get("assignee")
    ud["flow"] = "assignee"
    await query.message.reply_text("👤 Кому назначить задачу?", reply_markup=_employees_kb(names, suggested))


async def _flow_assign(idx: int, query, update, context):
    ud = context.user_data
    cfg, storage = _cfg(context), _storage(context)
    employees = storage.get_employees()
    if idx < 0 or idx >= len(employees):
        await query.message.reply_text("Ошибка выбора. Начни заново: /new")
        ud.clear()
        return
    ud["assignee_name"] = employees[idx]["name"]
    ud["assignee_id"] = employees[idx]["tg_id"]

    parsed = ud.get("pending_parsed") or {}
    dl = None
    # Приоритет 1: разбираем строку дедлайна с явной привязкой к MSK
    if parsed.get("deadline"):
        dl = parse_deadline(str(parsed["deadline"]), cfg.tz)
    # Приоритет 2: если строки нет, берем ISO-строку и переводим в MSK
    if not dl and parsed.get("deadline_iso"):
        try:
            raw_dl = datetime.fromisoformat(parsed["deadline_iso"])
            if raw_dl.tzinfo is None:
                dl = raw_dl.replace(tzinfo=cfg.tz)
            else:
                dl = raw_dl.astimezone(cfg.tz)
        except Exception:
            dl = None

    if dl:
        await _create_task(update, context, dl)
        return

    ud["flow"] = "deadline"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📆 Без дедлайна (+3 дня)", callback_data="flow:skip_deadline"),
        InlineKeyboardButton("❌ Отмена", callback_data="flow:cancel"),
    ]])
    await query.message.reply_text(
        f"⏰ Дедлайн для «{employees[idx]['name']}»? Напиши текстом, например:\n"
        "«завтра 18:00», «25.09 17:00», «через 3 дня».",
        reply_markup=kb,
    )


async def _flow_deadline_text(update, context):
    ud = context.user_data
    cfg = _cfg(context)
    text = update.effective_message.text or ""
    deadline = parse_deadline(text, cfg.tz)
    if not deadline:
        await update.effective_message.reply_text(
            "Не понял дату 🤔. Попробуй ещё раз: «завтра 18:00», «25.09 17:00», «через 3 дня»."
        )
        return
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=cfg.tz)
    else:
        deadline = deadline.astimezone(cfg.tz)
    await _create_task(update, context, deadline)


async def _flow_edit_text(update, context):
    ud = context.user_data
    raw = ud.get("pending_raw") or ""
    new_text = (update.effective_message.text or "")[:2000]
    combined = new_text if not raw else f"{new_text}\n{raw}"
    if len(combined) > 4000:
        combined = combined[:4000]
    ud["flow"] = "edit_parsing"
    await _start_task(update, context, combined)


# --- Служебные действия -----------------------------------------------------

async def _executor_action(context, task_id: str, action: str, user_id: int) -> str:
    storage = _storage(context)
    cfg = _cfg(context)
    task = storage.get_task(task_id)
    if not task:
        return "❌ Задача не найдена."
    if task.assignee_id != user_id and user_id not in cfg.admin_ids and task.created_by != user_id:
        return "⛔ Нет доступа к этой задаче."
    status = "done" if action == "done" else "in_progress"
    storage.update_task(task_id, status=status)
    storage.add_journal("status_update", task_id=task_id, status=status, user=user_id)
    if task.created_by and task.created_by != user_id:
        try:
            await context.bot.send_message(
                chat_id=task.created_by,
                text=f"📬 Исполнитель «{task.assignee}» отчитался: «{status}» — {task.title} ({task_id}).",
            )
        except Exception as exc:
            log.warning("Не удалось уведомить заказчика: %s", exc)
    return f"✅ Отмечено: «{status}»."


# --- Команды ----------------------------------------------------------------

async def cmd_start(update, context):
    cfg, storage = _cfg(context), _storage(context)
    role = _role_of(update.effective_user.id, cfg, storage)
    text = (
        f"👋 Привет! Я — личный трекер задач (MVP по ТЗ).\n"
        f"Твоя роль: {ROLE_NAMES[role]}\n\n"
        "Управляй кнопками меню внизу 👇\n"
        "• «Создать задачу» — текстом или голосом\n"
        "• «Мои задачи» — список задач\n"
        "• «Журнал» — журнал действий\n\n"
        "Также работают команды: /new, /tasks, /done <ID>, /status <ID> текст, /log, /staff, /myid."
    )
    await update.effective_message.reply_text(text, reply_markup=menu_kb(role))


async def cmd_help(update, context):
    cfg, storage = _cfg(context), _storage(context)
    role = _role_of(update.effective_user.id, cfg, storage)
    text = (
        "📖 Как пользоваться\n\n"
        "1️⃣ Нажми «Создать задачу» и напиши задачу текстом или голосом.\n"
        "2️⃣ Бот распознает её (Ollama/Whisper), переформулирует в SMART и спросит подтверждение.\n"
        "3️⃣ Выбери исполнителя и напиши дедлайн (например, «завтра 18:00»).\n"
        "4️⃣ Исполнитель получает уведомление, отчитывается кнопками.\n\n"
        "Контроль дедлайнов: напоминание за N часов, запрос в момент дедлайна,\n"
        "эскалация заказчику при просрочке.\n\n"
        "Роли:\n"
        "• Заказчик — создаёт задачи, видит журнал\n"
        "• Исполнитель — получает задачи, отчитывается\n"
        "• Администратор — настраивает бота и список сотрудников"
    )
    await update.effective_message.reply_text(text, reply_markup=menu_kb(role))


async def cmd_new(update, context):
    cfg, storage = _cfg(context), _storage(context)
    if not _can_create(_role_of(update.effective_user.id, cfg, storage)):
        await update.effective_message.reply_text("⛔ Создавать задачи может только заказчик или администратор.")
        return
    context.user_data.clear()
    await update.effective_message.reply_text("Опиши задачу текстом или голосом. Например: «Проверить отчёт по продажам за сентябрь, Иван, завтра к 18:00».")


async def cmd_tasks(update, context):
    cfg, storage = _cfg(context), _storage(context)
    user_id = update.effective_user.id
    role = _role_of(user_id, cfg, storage)
    if role == "none":
        await update.effective_message.reply_text("⛔ Доступа нет. Обратись к администратору.")
        return
    if role == "employee":
        tasks = storage.list_tasks(assignee_id=user_id)
        title = "📋 Мои задачи:"
    elif role == "admin":
        tasks = storage.list_tasks()
        title = "📋 Все задачи:"
    else:
        tasks = [t for t in storage.list_tasks() if _same_id(t.created_by, user_id)]
        title = "📋 Мои задачи:"
    if not tasks:
        await update.effective_message.reply_text(title + "\n(пусто)")
        return
    lines = [f"• {t.task_id} · {t.title} — {fmt_dt(t.deadline)} [{t.status}]" for t in tasks]
    await update.effective_message.reply_text(title + "\n" + "\n".join(lines[:60]))


async def cmd_done(update, context):
    cfg, storage = _cfg(context), _storage(context)
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("Использование: /done T-000001")
        return
    task_id = args[0].strip()
    if not re.match(r"^T-\d+$", task_id):
        await update.effective_message.reply_text("Неверный формат ID задачи. Пример: /done T-000001")
        return
    result = await _executor_action(context, task_id, "done", update.effective_user.id)
    await update.effective_message.reply_text(result)


async def cmd_status(update, context):
    cfg, storage = _cfg(context), _storage(context)
    args = context.args or []
    if len(args) < 1:
        await update.effective_message.reply_text("Использование: /status T-000001 текст отчёта")
        return
    task_id = args[0].strip()
    if not re.match(r"^T-\d+$", task_id):
        await update.effective_message.reply_text("Неверный формат ID задачи. Пример: /status T-000001 текст отчёта")
        return
    note = " ".join(args[1:])[:500]
    task = storage.get_task(task_id)
    if not task:
        await update.effective_message.reply_text("❌ Задача не найдена.")
        return
    user_id = update.effective_user.id
    if task.assignee_id != user_id and user_id not in cfg.admin_ids and task.created_by != user_id:
        await update.effective_message.reply_text("⛔ Нет доступа к этой задаче.")
        return
    storage.update_task(task_id, status="in_progress")
    storage.add_journal("status_report", task_id=task_id, note=note, user=user_id)
    if task.created_by and task.created_by != user_id:
        try:
            await context.bot.send_message(
                chat_id=task.created_by,
                text=f"📬 Отчёт по {task_id}: «{note or 'в работе'}» — от {task.assignee}.",
            )
        except Exception as exc:
            log.warning("Не удалось уведомить заказчика: %s", exc)
    await update.effective_message.reply_text("✅ Отчёт принят.")


async def cmd_log(update, context):
    cfg, storage = _cfg(context), _storage(context)
    role = _role_of(update.effective_user.id, cfg, storage)
    if not _can_create(role):
        await update.effective_message.reply_text("⛔ Журнал доступен заказчику и администратору.")
        return
    try:
        n = max(1, min(int((context.args or ["20"])[0]), 200))
    except ValueError:
        n = 20
    user_id = update.effective_user.id
    entries = storage.get_journal(500 if role != "admin" else n)
    if role != "admin":
        own_ids = {t.task_id for t in storage.list_tasks() if _same_id(t.created_by, user_id)}
        visible = []
        for entry in entries:
            meta = _journal_meta(entry)
            task_id = meta.get("task_id")
            if (
                _same_id(meta.get("created_by"), user_id)
                or _same_id(meta.get("user"), user_id)
                or _same_id(meta.get("by"), user_id)
                or (task_id and task_id in own_ids)
            ):
                visible.append(entry)
        entries = visible[:n]
    if not entries:
        await update.effective_message.reply_text("🗒 Журнал пуст.")
        return
    lines = []
    for e in entries:
        try:
            ts = fmt_dt(datetime.fromisoformat(e["ts"]))
        except Exception:
            ts = e.get("ts", "")
        meta = e.get("meta") or ""
        if isinstance(meta, dict):
            if meta:
                meta = " · " + json.dumps(meta, ensure_ascii=False)[:300]
            else:
                meta = ""
        lines.append(f"• {ts} — {e.get('event', '')}{meta}")
    text = "🗒 Журнал действий:\n" + "\n".join(lines)
    for i in range(0, len(text), 3800):
        await update.effective_message.reply_text(text[i:i + 3800])


async def cmd_myid(update, context):
    await update.effective_message.reply_text(f"Твой Telegram ID: {update.effective_user.id}")


async def _cmd_reset(update, context):
    context.user_data.clear()
    await update.effective_message.reply_text("Ок, сброшено.")


async def cmd_staff(update, context):
    cfg, storage = _cfg(context), _storage(context)
    if _role_of(update.effective_user.id, cfg, storage) != "admin":
        await update.effective_message.reply_text("⛔ Только для администратора.")
        return
    employees = storage.get_employees()
    rows = []
    for e in employees:
        rows.append([InlineKeyboardButton(f"❌ {e['name']} ({e['tg_id']})", callback_data=f"staff:del:{e['tg_id']}")])
    rows.append([InlineKeyboardButton("➕ Добавить сотрудника", callback_data="staff:add")])
    header = "👥 Сотрудники:\n" if employees else "👥 Сотрудников пока нет.\n"
    text = header + "\n".join(f"{i}. {e['name']} — {e['tg_id']}" for i, e in enumerate(employees, 1))
    if not employees:
        text += "\nДобавь первого через кнопку ниже."
    await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows))


# --- Обработчики сообщений --------------------------------------------------

async def _run_menu_action(key: str, update, context):
    if key == "new":
        await cmd_new(update, context)
    elif key == "tasks":
        await cmd_tasks(update, context)
    elif key == "log":
        await cmd_log(update, context)
    elif key == "staff":
        await cmd_staff(update, context)
    elif key == "myid":
        await cmd_myid(update, context)
    elif key == "help":
        await cmd_help(update, context)
    elif key == "reset":
        await _cmd_reset(update, context)


async def on_text(update, context):
    if not update.effective_user or not update.effective_message:
        return
    text = (update.effective_message.text or "").strip()
    menu_key = _MENU_BY_LABEL.get(text)
    if menu_key:
        await _run_menu_action(menu_key, update, context)
        return
    ud = context.user_data
    state = ud.get("flow")
    if state in ("edit", "edit_parsing"):
        await _flow_edit_text(update, context)
    elif state == "deadline":
        await _flow_deadline_text(update, context)
    elif state == "staff_add_name":
        await _flow_staff_name(update, context)
    elif state == "staff_add_id":
        await _flow_staff_id(update, context)
    else:
        await _handle_free_text(update, context)


async def _handle_free_text(update, context):
    if not update.effective_user or not update.effective_message:
        return
    user_id = update.effective_user.id
    text = (update.effective_message.text or "").strip()
    cfg, storage = _cfg(context), _storage(context)
    if text.lower() in ("отмена", "отмен", "cancel", "стоп"):
        context.user_data.clear()
        await update.effective_message.reply_text("Ок, текущее действие отменено.")
        return
    role = _role_of(user_id, cfg, storage)
    if _can_create(role):
        await _start_task(update, context, text)
    elif role == "employee":
        await update.effective_message.reply_text(
            "Ты исполнитель. Отчитаться можно кнопками на карточке задачи, /done <ID> или /status <ID> текст."
        )
    else:
        await update.effective_message.reply_text(
            "⛔ Доступа нет. Обратись к администратору, чтобы тебя добавили (или — если ты заказчик — добавь свой ID в ADMIN_IDS/CUSTOMER_IDS)."
        )


async def _flow_staff_name(update, context):
    cfg, storage = _cfg(context), _storage(context)
    if _role_of(update.effective_user.id, cfg, storage) != "admin":
        context.user_data.clear()
        await update.effective_message.reply_text("⛔ Доступно только администратору.")
        return
    name = (update.effective_message.text or "").strip()
    name = re.sub(r"[\r\n\t]+", " ", name).strip()[:60]
    if not name:
        await update.effective_message.reply_text("Напиши имя сотрудника.")
        return
    context.user_data["staff_new_name"] = name
    context.user_data["flow"] = "staff_add_id"
    await update.effective_message.reply_text(f"Принято: «{name}». Теперь Telegram ID сотрудника (узнать можно у @userinfobot):")


async def _flow_staff_id(update, context):
    cfg, storage = _cfg(context), _storage(context)
    if _role_of(update.effective_user.id, cfg, storage) != "admin":
        context.user_data.clear()
        await update.effective_message.reply_text("⛔ Доступно только администратору.")
        return
    raw = (update.effective_message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0 or int(raw) > 10**15:
        await update.effective_message.reply_text("ID должен быть положительным числом (до 15 знаков). Попробуй ещё раз.")
        return
    tg_id = int(raw)
    name = context.user_data.get("staff_new_name", "Сотрудник")
    ok = storage.add_employee(name, tg_id)
    storage.add_journal("employee_added", name=name, tg_id=tg_id, by=update.effective_user.id)
    context.user_data.clear()
    if ok:
        await update.effective_message.reply_text(f"✅ Сотрудник «{name}» добавлен (ID {tg_id}).")
    else:
        await update.effective_message.reply_text("⚠️ Сотрудник с таким Telegram ID уже есть.")


async def on_voice(update, context):
    if not update.effective_user or not update.effective_message:
        return
    cfg, storage = _cfg(context), _storage(context)
    role = _role_of(update.effective_user.id, cfg, storage)
    if not _can_create(role):
        await update.effective_message.reply_text("⛔ Голос принимается только от заказчика/администратора.")
        return
    if not cfg.whisper_enabled:
        await update.effective_message.reply_text("Распознавание голоса отключено (USE_WHISPER=false). Пришли текст.")
        return
    voice_dir = cfg.storage_path.parent / "voice"
    voice_dir.mkdir(parents=True, exist_ok=True)
    audio_path = voice_dir / f"voice_{update.effective_user.id}_{int(datetime.now().timestamp())}.oga"
    waiting = await update.effective_message.reply_text("🎙 Распознаю голос (Whisper)…")
    try:
        file = await update.effective_message.voice.get_file()
        await file.download_to_drive(audio_path)
        text = await asyncio.to_thread(transcribe, cfg, str(audio_path))
    except Exception as exc:
        log.warning("Ошибка транскрипции: %s", exc)
        await waiting.edit_text("Не удалось распознать голос. Попробуй текст.")
        return
    finally:
        try:
            audio_path.unlink(missing_ok=True)
        except OSError:
            pass
    if not text:
        await waiting.edit_text("Пустая запись. Попробуй ещё раз или отправь текст.")
        return
    await waiting.edit_text(f"🎙 Распознано: «{text[:300]}»")
    await _start_task(update, context, text)


async def on_callback(update, context):
    q = update.callback_query
    if not q or not q.data:
        return
    await q.answer()
    ud = context.user_data
    cfg, storage = _cfg(context), _storage(context)
    data = q.data
    user_id = q.from_user.id
    msg = q.message
    role = _role_of(user_id, cfg, storage)

    # 1. Действия по карточке задачи (исполнитель, создатель или администратор)
    if data.startswith("task:"):
        parts = data.split(":", 2)
        if len(parts) == 3 and parts[1] in ("done", "wip"):
            result = await _executor_action(context, parts[2], parts[1], user_id)
            await msg.reply_text(result)
        return

    # 2. Управление сотрудниками (строго администратор)
    if data == "staff:add" or data.startswith("staff:del:"):
        if role != "admin":
            await msg.reply_text("⛔ Управление сотрудниками доступно только администратору.")
            return
        if data == "staff:add":
            ud["flow"] = "staff_add_name"
            await msg.reply_text("Имя сотрудника (например «Иван»):")
        elif data.startswith("staff:del:"):
            tg_raw = data.rsplit(":", 1)[1]
            if tg_raw.isdigit():
                ok = storage.remove_employee(int(tg_raw))
                storage.add_journal("employee_removed", tg_id=int(tg_raw), by=user_id)
                await msg.reply_text("✅ Удалён." if ok else "⚠️ Не найден.")
        return

    # 3. Отмена
    if data == "flow:cancel":
        ud.clear()
        await msg.reply_text("Отменено.")
        return

    # 4. Процесс создания задачи (только заказчик или администратор)
    if not _can_create(role):
        await msg.reply_text("⛔ Нет доступа. Это действие выполняет заказчик/администратор.")
        return

    # Защита от кликов по устаревшим сессиям / чужим сообщениям
    if data in ("flow:confirm", "flow:edit", "flow:skip_deadline") or data.startswith("emp:"):
        if not ud.get("pending_parsed"):
            ud.clear()
            await msg.reply_text("⚠️ Сессия создания задачи устарела. Начни заново: /new")
            return

    if data == "flow:confirm":
        await _flow_confirm(q, update, context)
    elif data == "flow:edit":
        ud["flow"] = "edit"
        await msg.reply_text("✏️ Опиши задачу другими словами (можно скорректировать дедлайн/исполнителя):")
    elif data == "flow:skip_deadline":
        deadline = datetime.now(cfg.tz) + timedelta(days=3)
        await _create_task(update, context, deadline)
    elif data.startswith("emp:"):
        try:
            idx = int(data.split(":", 1)[1])
        except ValueError:
            await msg.reply_text("Ошибка. Начни заново: /new")
            return
        await _flow_assign(idx, q, update, context)


def register(application) -> None:
    from telegram.ext import (
        CallbackQueryHandler,
        CommandHandler,
        MessageHandler,
        filters,
    )
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("new", cmd_new))
    application.add_handler(CommandHandler("tasks", cmd_tasks))
    application.add_handler(CommandHandler("done", cmd_done))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("log", cmd_log))
    application.add_handler(CommandHandler("staff", cmd_staff))
    application.add_handler(CommandHandler("myid", cmd_myid))
    application.add_handler(CommandHandler("reset", _cmd_reset))
    application.add_handler(MessageHandler(filters.VOICE, on_voice))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_handler(CallbackQueryHandler(on_callback))