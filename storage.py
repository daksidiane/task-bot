"""Хранилища: локальный JSON и Google Sheets (бэкенд по ТЗ)."""
from __future__ import annotations

import json
import re
import threading
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from models import MSK, Task

_TOKEN_PATTERN = re.compile(r"bot\d+:[A-Za-z0-9_-]+|\b\d{8,10}:[A-Za-z0-9_-]{30,}\b")


def redact_secrets(val):
    """Рекурсивно маскирует токены Telegram и секреты в строках, словарях и списках."""
    if isinstance(val, str):
        return _TOKEN_PATTERN.sub("<REDACTED_TOKEN>", val)
    if isinstance(val, dict):
        return {k: redact_secrets(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [redact_secrets(v) for v in val]
    return val


def sanitize_sheet_value(v):
    """Предотвращает Formula Injection в Google Sheets / Excel при выводе ячеек."""
    if isinstance(v, str):
        if v.startswith(("=", "+", "-", "@", "\t", "\r")):
            return "'" + v
        return v
    return v


TASKS_HEADERS = [
    "ID", "Название", "Описание", "Исполнитель", "TG ID", "Создал",
    "Дедлайн", "Статус", "Создано", "Напомнено", "Эскалировано", "Пропуски",
]
JOURNAL_HEADERS = ["Время", "Событие", "Данные"]
EMPLOYEES_HEADERS = ["Имя", "Telegram ID"]

_TASK_FIELDS = [
    "task_id", "title", "description", "assignee", "assignee_id",
    "created_by", "deadline", "status", "created_at",
    "reminded_before", "reminded_at_deadline", "escalation_sent", "missed",
]


class StorageError(RuntimeError):
    pass


class Storage(ABC):
    @abstractmethod
    def add_task(self, task: Task) -> Task: ...

    @abstractmethod
    def get_task(self, task_id: str) -> Task | None: ...

    @abstractmethod
    def update_task(self, task_id: str, **fields) -> Task | None: ...

    @abstractmethod
    def list_tasks(self, status: str | None = None, assignee_id: int | None = None) -> list[Task]: ...

    @abstractmethod
    def add_journal(self, event: str, **meta) -> None: ...

    @abstractmethod
    def get_journal(self, limit: int = 50) -> list[dict]: ...

    @abstractmethod
    def get_employees(self) -> list[dict]: ...

    @abstractmethod
    def add_employee(self, name: str, tg_id: int) -> bool: ...

    @abstractmethod
    def remove_employee(self, tg_id: int) -> bool: ...


class LocalStorage(Storage):
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.data: dict = {"tasks": {}, "journal": [], "employees": []}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise StorageError(f"Не удалось прочитать {self.path}: {exc}") from exc
            self.data.setdefault("tasks", {})
            self.data.setdefault("journal", [])
            self.data.setdefault("employees", [])

    def _save(self):
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self.path)

    def add_task(self, task: Task) -> Task:
        with self._lock:
            self.data["tasks"][task.task_id] = task.to_dict()
            self._save()
        return task

    def get_task(self, task_id: str) -> Task | None:
        with self._lock:
            raw = self.data["tasks"].get(task_id)
        return Task.from_dict(raw) if raw else None

    def update_task(self, task_id: str, **fields) -> Task | None:
        allowed = {f: v for f, v in fields.items() if f in _TASK_FIELDS}
        with self._lock:
            raw = self.data["tasks"].get(task_id)
            if raw is None:
                return None
            raw.update(allowed)
            self._save()
        return Task.from_dict(raw)

    def list_tasks(self, status: str | None = None, assignee_id: int | None = None) -> list[Task]:
        with self._lock:
            raws = list(self.data["tasks"].values())
        out = []
        for r in raws:
            if status and r.get("status") != status:
                continue
            if assignee_id is not None and r.get("assignee_id") != assignee_id:
                continue
            out.append(Task.from_dict(r))
        out.sort(key=lambda t: t.created_at)
        return out

    def add_journal(self, event: str, **meta) -> None:
        from datetime import datetime
        entry = {
            "ts": datetime.now().astimezone().isoformat(),
            "event": event,
            "meta": redact_secrets(meta),
        }
        with self._lock:
            self.data["journal"].append(entry)
            if len(self.data["journal"]) > 5000:
                self.data["journal"] = self.data["journal"][-5000:]
            self._save()

    def get_journal(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return list(reversed(self.data["journal"][-limit:]))

    def get_employees(self) -> list[dict]:
        with self._lock:
            return [dict(e) for e in self.data["employees"]]

    def add_employee(self, name: str, tg_id: int) -> bool:
        name = name.strip()
        with self._lock:
            for e in self.data["employees"]:
                if e["tg_id"] == tg_id:
                    return False
            self.data["employees"].append({"name": name, "tg_id": tg_id})
            self._save()
        return True

    def remove_employee(self, tg_id: int) -> bool:
        with self._lock:
            before = len(self.data["employees"])
            self.data["employees"] = [e for e in self.data["employees"] if e["tg_id"] != tg_id]
            changed = len(self.data["employees"]) != before
            if changed:
                self._save()
        return changed


class SheetsStorage(Storage):
    def __init__(self, service_account_file: Path, sheet_id: str):
        import gspread
        self._lock = threading.RLock()
        with self._lock:
            self._gc = gspread.service_account(filename=str(service_account_file))
            self._spread = self._gc.open_by_key(sheet_id)
            self._ensure_sheets()

    def _ensure_sheets(self):
        for title, headers in (
            ("Задачи", TASKS_HEADERS),
            ("Журнал", JOURNAL_HEADERS),
            ("Сотрудники", EMPLOYEES_HEADERS),
        ):
            try:
                self._spread.worksheet(title)
            except Exception:
                ws = self._spread.add_worksheet(title, rows=1000, cols=len(headers))
                ws.append_row(headers, value_input_option="RAW")

        # Удаляем дефолтные пустые листы Google Таблицы (Sheet1 / Лист1),
        # чтобы таблица всегда открывалась сразу на вкладке «Задачи»
        for default_title in ("Sheet1", "Лист1", "Лист 1"):
            try:
                ws_def = self._spread.worksheet(default_title)
                vals = ws_def.get_all_values()
                if not any(any(row) for row in vals) and len(self._spread.worksheets()) > 1:
                    self._spread.del_worksheet(ws_def)
            except Exception:
                pass

    @staticmethod
    def _task_row(task: Task) -> list:
        dl = task.deadline.astimezone(MSK) if task.deadline.tzinfo else task.deadline.replace(tzinfo=MSK)
        cr = task.created_at.astimezone(MSK) if task.created_at.tzinfo else task.created_at.replace(tzinfo=MSK)
        return [
            task.task_id,
            sanitize_sheet_value(task.title),
            sanitize_sheet_value(task.description),
            sanitize_sheet_value(task.assignee),
            task.assignee_id or "",
            task.created_by,
            dl.isoformat(),
            task.status,
            cr.isoformat(),
            task.reminded_before,
            task.escalation_sent,
            task.missed,
        ]

    @staticmethod
    def _task_from_row(r: list) -> Task:
        def val(i, default=""):
            return r[i] if i < len(r) and r[i] not in (None, "") else default

        created_by = val(5, "0")
        try:
            created_by = int(float(created_by))
        except (TypeError, ValueError):
            created_by = 0
        assignee_id = val(4, "")
        assignee_id = int(float(assignee_id)) if assignee_id else None

        dl_val = val(6)
        try:
            dl = datetime.fromisoformat(dl_val) if dl_val else datetime.now(MSK)
            dl = dl.astimezone(MSK) if dl.tzinfo else dl.replace(tzinfo=MSK)
        except Exception:
            dl = datetime.now(MSK)

        cr_val = val(8)
        try:
            cr = datetime.fromisoformat(cr_val) if cr_val else datetime.now(MSK)
            cr = cr.astimezone(MSK) if cr.tzinfo else cr.replace(tzinfo=MSK)
        except Exception:
            cr = datetime.now(MSK)

        return Task(
            task_id=val(0),
            title=val(1),
            description=val(2),
            assignee=val(3),
            assignee_id=assignee_id,
            created_by=created_by,
            deadline=dl,
            status=val(7, "new"),
            reminded_before=str(val(9, "false")) == "True",
            escalation_sent=str(val(10, "false")) == "True",
            missed=int(val(11, "0") or 0),
            created_at=cr,
        )

    def add_task(self, task: Task) -> Task:
        with self._lock:
            ws = self._spread.worksheet("Задачи")
            ws.append_row(self._task_row(task), value_input_option="RAW")
            return task

    def get_task(self, task_id: str) -> Task | None:
        with self._lock:
            ws = self._spread.worksheet("Задачи")
            for r in ws.get_all_values()[1:]:
                if r and r[0] == task_id:
                    return self._task_from_row(r)
            return None

    def update_task(self, task_id: str, **fields) -> Task | None:
        allowed = {f: v for f, v in fields.items() if f in _TASK_FIELDS}
        with self._lock:
            ws = self._spread.worksheet("Задачи")
            rows = ws.get_all_values()
            col_map = {h: i for i, h in enumerate(rows[0])}
            task_raw = None
            for i, r in enumerate(rows[1:], start=2):
                if r and r[0] == task_id:
                    task_raw = r
                    for k, v in allowed.items():
                        if k in ("deadline",) and isinstance(v, str):
                            pass
                        col = col_map.get(_SHEET_COL.get(k, k))
                        if col is not None:
                            ws.update_cell(i, col + 1, self._cell_value(v))
                    break
            return self.get_task(task_id) if task_raw else None

    @staticmethod
    def _cell_value(v):
        if isinstance(v, bool):
            return "True" if v else "False"
        if isinstance(v, datetime):
            return v.isoformat()
        if isinstance(v, str):
            return sanitize_sheet_value(v)
        return v

    def list_tasks(self, status: str | None = None, assignee_id: int | None = None) -> list[Task]:
        with self._lock:
            ws = self._spread.worksheet("Задачи")
            out = []
            for r in ws.get_all_values()[1:]:
                if not r or not r[0]:
                    continue
                try:
                    task = self._task_from_row(r)
                except Exception:
                    continue
                if status and task.status != status:
                    continue
                if assignee_id is not None and task.assignee_id != assignee_id:
                    continue
                out.append(task)
            out.sort(key=lambda t: t.created_at)
            return out

    def add_journal(self, event: str, **meta) -> None:
        from datetime import datetime
        with self._lock:
            ws = self._spread.worksheet("Журнал")
            sanitized_meta = redact_secrets(meta)
            ws.append_row([
                datetime.now().astimezone().isoformat(),
                event,
                json.dumps(sanitized_meta, ensure_ascii=False),
            ], value_input_option="RAW")

    def get_journal(self, limit: int = 50) -> list[dict]:
        with self._lock:
            ws = self._spread.worksheet("Журнал")
            entries = []
            for r in ws.get_all_values()[1:][::-1]:
                if not r or not r[0]:
                    continue
                meta_raw = r[2] if len(r) > 2 else ""
                try:
                    meta = json.loads(meta_raw) if meta_raw else {}
                except Exception:
                    meta = meta_raw
                entries.append({"ts": r[0], "event": r[1] if len(r) > 1 else "", "meta": meta})
                if len(entries) >= limit:
                    break
            return entries

    def get_employees(self) -> list[dict]:
        with self._lock:
            ws = self._spread.worksheet("Сотрудники")
            out = []
            for r in ws.get_all_values()[1:]:
                if not r or not r[0]:
                    continue
                tid_raw = r[1] if len(r) > 1 else ""
                tid_raw = str(tid_raw).split(".")[0] if "." in str(tid_raw) else tid_raw
                try:
                    tid = int(float(tid_raw))
                except (TypeError, ValueError):
                    tid = 0
                out.append({"name": r[0], "tg_id": tid})
            return out

    def add_employee(self, name: str, tg_id: int) -> bool:
        name = name.strip()
        with self._lock:
            if any(e["tg_id"] == tg_id for e in self.get_employees()):
                return False
            ws = self._spread.worksheet("Сотрудники")
            ws.append_row([sanitize_sheet_value(name), tg_id], value_input_option="RAW")
            return True

    def remove_employee(self, tg_id: int) -> bool:
        with self._lock:
            ws = self._spread.worksheet("Сотрудники")
            rows = ws.get_all_values()
            for i, r in enumerate(rows[1:], start=2):
                if not r:
                    break
                tid_raw = str(r[1]).split(".")[0] if "." in str(r[1]) else str(r[1])
                if tid_raw.isdigit() and int(tid_raw) == tg_id:
                    ws.delete_rows(i)
                    return True
            return False


_SHEET_COL = {
    "task_id": "ID", "title": "Название", "description": "Описание",
    "assignee": "Исполнитель", "assignee_id": "TG ID", "created_by": "Создал",
    "deadline": "Дедлайн", "status": "Статус", "created_at": "Создано",
    "reminded_before": "Напомнено", "escalation_sent": "Эскалировано",
    "missed": "Пропуски",
}


def create_storage(cfg) -> Storage:
    if cfg.storage_backend == "sheets":
        if not cfg.service_account_file or not cfg.sheet_id:
            raise StorageError(
                "STORAGE_BACKEND=sheets требует GOOGLE_SERVICE_ACCOUNT и GOOGLE_SHEET_ID"
            )
        if not cfg.service_account_file.exists():
            raise StorageError(
                f"Файл сервисного аккаунта не найден: {cfg.service_account_file}"
            )
        return SheetsStorage(cfg.service_account_file, cfg.sheet_id)
    return LocalStorage(cfg.storage_path)