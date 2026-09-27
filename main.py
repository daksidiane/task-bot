"""Точка входа: python main.py (или python main.py --check)."""
from __future__ import annotations

import logging
import sys

from telegram import Update
from telegram.ext import Application

from ai_extract import Extractor
from config import ConfigError, load_config
from storage import StorageError, create_storage

log = logging.getLogger(__name__)


def _setup_logging():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )


async def _check_deadlines_dispatch(context):
    from scheduler_jobs import check_deadlines
    await check_deadlines(context)


def run_selfcheck(cfg) -> int:
    print("=" * 60)
    print("Самопроверка конфигурации бота (MVP по ТЗ)")
    print("=" * 60)
    issues = []

    print(f"[1/5] Конфигурация: токен задан (длина {len(cfg.tg_bot_token)} символов)")
    if not cfg.admin_ids:
        issues.append("ADMIN_IDS пуст — никто не сможет управлять ботом")
        print("      !!! ADMIN_IDS не задан (обязательно)")
    else:
        print(f"      Администраторы: {cfg.admin_ids}")

    print("[2/5] Хранилище:", cfg.storage_backend)
    try:
        create_storage(cfg)
        print("      OK: хранилище открывается")
    except StorageError as exc:
        issues.append(f"хранилище: {exc}")
        print("      ERROR:", exc)

    print(f"[3/5] LLM: {cfg.ollama_url} / {cfg.ollama_model}")
    try:
        ext = Extractor(cfg)
        ok = ext.ollama_available()
        print("      OK: Ollama доступна" if ok else "      ? Ollama недоступна — будет эвристика (без LLM-разбора)")
    except Exception as exc:
        print("      ERROR:", exc)
        issues.append(str(exc))

    print(f"[4/5] Whisper: USE_WHISPER={cfg.whisper_enabled}, модель={cfg.whisper_model}")
    if cfg.whisper_enabled:
        from stt import whisper_available
        print("      OK: openai-whisper установлена" if whisper_available()
              else "      ? openai-whisper не установлена — голос недоступен, поставь requirements-ai.txt")

    print(f"[5/5] Логика дедлайнов: напоминание за {cfg.remind_hours_before} ч, эскалация после {cfg.escalate_after_minutes} мин просрочки")

    employees = create_storage(cfg).get_employees()
    print(f"      Сотрудников в базе: {len(employees)}")

    print("-" * 60)
    if issues:
        print("Есть замечания:")
        for it in issues:
            print("  •", it)
        print("Исправь и повтори. После этого: python main.py")
        return 1
    print("Всё готово. Запуск: python main.py")
    return 0


def build_app(cfg):
    storage = create_storage(cfg)
    extractor = Extractor(cfg)
    app = Application.builder().token(cfg.tg_bot_token).build()
    app.bot_data["cfg"] = cfg
    app.bot_data["storage"] = storage
    app.bot_data["extractor"] = extractor

    from handlers import register
    register(app)

    app.job_queue.run_repeating(_check_deadlines_dispatch, interval=60, first=10)
    return app


def main(argv: list[str]) -> int:
    _setup_logging()
    try:
        cfg = load_config()
    except ConfigError as exc:
        print("[ОШИБКА]", exc)
        return 2

    if "--check" in argv:
        return run_selfcheck(cfg)

    app = build_app(cfg)
    log.info("Бот запущен (polling). Остановка: Ctrl+C")
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))