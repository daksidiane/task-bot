"""Загрузка конфигурации и секретов из secrets/.env (или .env в корне)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
_SECRETS_PATH = BASE_DIR / "secrets" / ".env"


class ConfigError(RuntimeError):
    pass


def _load_env():
    loaded = []
    if _SECRETS_PATH.exists():
        load_dotenv(_SECRETS_PATH)
        loaded.append(str(_SECRETS_PATH))
    root_env = BASE_DIR / ".env"
    if root_env.exists():
        load_dotenv(root_env)
        loaded.append(str(root_env))
    return loaded


def _parse_ids(raw: str | None) -> tuple[int, ...]:
    if not raw:
        return ()
    out = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return tuple(out)


def _get_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Secrets:
    tg_bot_token: str
    admin_ids: tuple[int, ...]
    customer_ids: tuple[int, ...]
    ollama_url: str
    ollama_model: str
    whisper_enabled: bool
    whisper_model: str
    storage_backend: str
    storage_path: Path
    service_account_file: Path | None
    sheet_id: str | None
    remind_hours_before: int
    escalate_after_minutes: int
    tz: ZoneInfo


def load_config() -> Secrets:
    _load_env()
    token = os.getenv("TG_BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError(
            "TG_BOT_TOKEN не задан. Скопируй .env.example в secrets/.env, "
            "вставь токен от @BotFather. Затем: python main.py --check"
        )

    def _path(val: str | None) -> Path | None:
        if not val:
            return None
        p = Path(val)
        if not p.is_absolute():
            p = BASE_DIR / p
        return p

    tz_name = os.getenv("TZ", "Europe/Moscow")
    try:
        tz = ZoneInfo(tz_name or "Europe/Moscow")
    except Exception:
        tz = ZoneInfo("Europe/Moscow")

    backend = os.getenv("STORAGE_BACKEND", "local").strip().lower()
    if backend not in ("local", "sheets"):
        backend = "local"

    return Secrets(
        tg_bot_token=token,
        admin_ids=_parse_ids(os.getenv("ADMIN_IDS")),
        customer_ids=_parse_ids(os.getenv("CUSTOMER_IDS")),
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1:8b"),
        whisper_enabled=_get_bool("USE_WHISPER", True),
        whisper_model=os.getenv("WHISPER_MODEL", "base").strip().lower(),
        storage_backend=backend,
        storage_path=_path(os.getenv("STORAGE_PATH")) or (BASE_DIR / "data" / "bot_data.json"),
        service_account_file=_path(os.getenv("GOOGLE_SERVICE_ACCOUNT")),
        sheet_id=os.getenv("GOOGLE_SHEET_ID") or None,
        remind_hours_before=max(0, int(os.getenv("REMINDER_HOURS_BEFORE", "6"))),
        escalate_after_minutes=max(0, int(os.getenv("ESCALATE_AFTER_MINUTES", "5"))),
        tz=tz,
    )