# Trecker Bot — MVP «Задачи и делегирование» (по ТЗ: AI-бот для Telegram)

Персональный AI-ассистент-трекер задач, минимально дешёвая версия по ТЗ из `info/ТЗ.txt`.
Все AI-модели локальные (Ollama + Llama 3.1, Whisper), хранилище — локальное или Google Sheets.

## Что реализовано (MVP, Этап 1)

| Функция ТЗ | Статус |
|---|---|
| F1.1–F1.2 Приём голосовых и текстовых сообщений | ✅ |
| F1.3 Транскрипция голоса локальным Whisper | ✅ (модель `base`/`small`, опционально) |
| F1.4 Распознавание задачи локальной Llama 3.1 (Ollama) | ✅ + fallback-эвристика без модели |
| F2.1–F2.3 SMART-переформулировка, подтверждение, редактирование | ✅ |
| F3.1–F3.4 Выбор исполнителя, дедлайн, создание, approval-step | ✅ |
| F4.1–F4.3 Журнал действий, `/log` | ✅ |
| F5.1–F5.4 Напоминание за N ч, запрос в момент дедлайна, обработка ответа, обновление статуса | ✅ |
| F6.1–F6.2 Просрочка → эскалация заказчику (двукратная) | ✅ |
| F7. Оркестрация | Заменена встроенным планировщиком (проверка раз в 60 сек) — n8n не нужен в MVP-боте |

Роли: **Заказчик** (создаёт задачи, видит журнал), **Исполнитель** (получает и закрывает задачи),
**Администратор** (настройка, список сотрудников).

## Структура

```
02/
├── main.py            # точка входа: python main.py [--check]
├── config.py          # загрузка секретов из secrets/.env
├── handlers.py        # все Telegram-команды и флоу задачи
├── scheduler_jobs.py  # дедлайны: напоминания и эскалации
├── ai_extract.py      # Ollama/Llama + эвристический парсер дедлайна
├── stt.py             # Whisper-транскрипция
├── storage.py         # LocalStorage (JSON) или Google Sheets
├── models.py          # модель задачи
├── ui.py              # карточки и кнопки
├── secrets/           # ← СЮДА кладём секреты (.env, service_account.json)
├── data/              # локальная база (бот-данные, временные аудио)
├── .env.example       # шаблон конфигурации
└── requirements*.txt
```

## Быстрый старт

```bash
# 1) Зависимости (базовые)
python -m venv .venv
.venv\Scripts\activate        # Windows; на Linux: source .venv/bin/activate
pip install -r requirements.txt
# AI-компоненты (тяжёлые, ставятся отдельно):
pip install -r requirements-ai.txt   # openai-whisper + torch; нужен ffmpeg

# 2) Секреты — см. ниже
# 3) Проверка конфигурации
python main.py --check
# 4) Запуск
python main.py
```

## Куда положить секреты

**Все секреты кладутся в папку `secrets/`** (она в `.gitignore`, в git не уходит):

```
secrets/
├── .env                 # копия .env.example, заполненная своими значениями
└── service_account.json # ключ Google (только если STORAGE_BACKEND=sheets)
```

Порядок заполнения `secrets/.env`:

| Параметр | Что вписать |
|---|---|
| `TG_BOT_TOKEN` | токен от @BotFather (см. ниже) |
| `ADMIN_IDS` | Telegram ID администраторов через запятую |
| `CUSTOMER_IDS` | Telegram ID заказчика(ов); пусто → заказчик = админы |
| `OLLAMA_URL`, `OLLAMA_MODEL` | локальная Llama (по умолч. `llama3.1:8b`) |
| `STORAGE_BACKEND` | `local` (сейчас) или `sheets` (Google) |
| `GOOGLE_SERVICE_ACCOUNT`, `GOOGLE_SHEET_ID` | для Google Sheets |

## Какие ключи/сервисы нужны и как их добыть (пошагово)

### Шаг 1. Токен Telegram-бота
1. В Telegram открой **@BotFather**, нажми Start.
2. Команда `/newbot` → название (например, `MyTaskBot`) → username (обязательно заканчивается на `bot`).
3. BotFather пришлёт токен вида `123456789:AAxxxx...` — вставь его в `secrets/.env` → `TG_BOT_TOKEN`.
4. Свой Telegram ID: напиши боту любое сообщение и выполни `/myid` (или узнай у **@userinfobot**). Впиши в `ADMIN_IDS`/`CUSTOMER_IDS`.

### Шаг 2. Ollama + Llama 3.1 (локальный LLM)
- Windows: скачай установщик с https://ollama.com/download, запусти.
- Linux: `curl -fsSL https://ollama.ai/install.sh | sh`.
- Скачай модель по ТЗ: `ollama pull llama3.1:8b`.
- Проверка: `curl http://localhost:11434/api/tags` должен вернуть JSON.
- Если Ollama нет — бот работает на эвристике (распознаёт дедлайны и имена, но без SMART-переформулировки).

### Шаг 3. Whisper (локальная транскрипция)
- `pip install -r requirements-ai.txt` (ставит `openai-whisper`, `torch` и `imageio-ffmpeg`).
- **ffmpeg** не нужно ставить отдельно: милт собирает готовый бинарь `/02/stt.py` из `imageio-ffmpeg`
  и сам кладёт его в PATH (копия `ffmpeg.exe` в `%TEMP%\bot_ffmpeg`).
- Модель выбирается в `.env`: `WHISPER_MODEL=base` (быстро) или `small` (качество, рекомендовано по ТЗ).
- **Важно для РФ:** модель Whisper скачивается с Azure CDN OpenAI, который в России блокируется.
  Если упадёт ошибка
  `URLError ... Cached response from openi HPC/azureedge` — скачай вручную из зеркала
  на Hugging Face и положи в кэш:
  ```powershell
  mkdir "$env:USERPROFILE\.cache\whisper" -Force
  Invoke-WebRequest "https://huggingface.co/TheScenery/whisper-models/resolve/main/base.pt" -OutFile "$env:USERPROFILE\.cache\whisper\base.pt"
  # для small: .../resolve/main/small.pt — и поменяй WHISPER_MODEL=small
  ```
  Кэш проверяется по sha256, файл взят из зеркала оригиналов.
- Запусти `python stt_check.py` для проверки (см. ниже).

### Шаг 4. Google Sheets (бэкенд по ТЗ, можно отложить)
1. Зайди на https://console.cloud.google.com → создай проект.
2. Меню «APIs & Services» → «Library» → включи **Google Sheets API** и **Google Drive API**.
3. «Credentials» → «Create credentials» → **Service account** → создай, запиши email.
4. У сервисного аккаунта: «Keys» → «Add key» → «JSON» → скачается `service_account.json` → положи в `secrets/`.
5. Создай таблицу в Google Таблицах. Кнопка «Доступ» → добавь **email сервисного аккаунта** с ролью «Редактор».
6. Из URL таблицы возьми её ID (часть после `/d/` и до `/edit`). Впиши в `.env`: `STORAGE_BACKEND=sheets`, `GOOGLE_SERVICE_ACCOUNT=secrets/service_account.json`, `GOOGLE_SHEET_ID=<id>`.
7. Листы «Задачи», «Журнал», «Сотрудники» бот создаст сам при первом запуске.

### Шаг 5. Сотрудники
После запуска админ выполняет `/staff` → «➕ Добавить сотрудника» → имя → Telegram ID исполнителя.
Или заполни лист «Сотрудники» / `employees` в JSON.

## Команды

- Заказчик/админ: пиши задачу текстом или голосом; `/tasks`, `/log [N]`, `/new`
- Исполнитель: кнопки на карточке, `/done <ID>`, `/status <ID> текст`
- Админ: `/staff`, `/myid`

## Развёртывание на VPS (из ТЗ)

Обязательно по ТЗ: **swap 4 GB** (`fallocate -l 4G /swapfile && chmod 600 && mkswap && swapon` + запись в `/etc/fstab`).
Запуск через systemd или Docker; файлы `.env`, `service_account.json`, `data/` — **не копировать** в общий контейнер-образ (монтировать как volume).

## Безопасность (результат проверки)

- Секреты только в `secrets/` (в `.gitignore`), в коде нет хардкода токенов.
- Токен/длины не логируются; в консоль выводится только длина токена.
- Доступ строго по ролям (админ/заказчик/исполнитель) — чужие действия отклоняются.
- Экран-подтверждение (`approval step`) — задача не создаётся без явного подтверждения.
- Промпт LLM содержит запрет на «инструкции из текста» (защита от prompt injection).
- HTML/разметка в сообщениях не используется → нет инъекций через разметку.
- Голосовые файлы скачиваются во временную папку и удаляются после распознавания.
- Валидация входных данных: длины строк, целочисленные ID, whitelist полей в БД.
- Очистка `context.user_data` после завершения флоу (нет «зависших» состояний).

Проверь перед продакшеном:
- [ ] `secrets/` и `data/` не попали в репозиторий (`git status` чистый по ним)
- [ ] файл `secrets/.env` не читается посторонними (на VPS: `chmod 600 secrets/.env`)
- [ ] `ADMIN_IDS` заполнен своими ID
- [ ] бот не добавлен в общие группы (или параметры приватности настроены)
- [ ] Google-таблица шарится только с email сервисника (роль «Редактор»)

## Траблшутинг

- `Ollama недоступна` — модель не локально или другой адрес: проверь `curl localhost:11434/api/tags`.
- Голос не распознаётся — нет `openai-whisper`/`ffmpeg`; убедись что `USE_WHISPER=true`.
- Нет дедлайна — текст без дат; бот спросит вручную.
- Рамка VPS — не хватает RAM: уменьши модель (Llama 3.1 8B → 3.2 3B/1B), проверь swap (4 GB), Whisper `base`.