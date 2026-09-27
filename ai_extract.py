"""AI-слой: Llama 3.1 через Ollama + эвристический fallback без модели."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

import requests

log = logging.getLogger(__name__)

_WEEKDAYS = {
    "понедельник": 0, "вторник": 1, "сред": 2, "четверг": 3,
    "пятниц": 4, "суббот": 5, "воскресен": 6,
}


def parse_deadline(text: str, tz, now: datetime | None = None) -> datetime | None:
    """Парсит дедлайн из свободного текста (завтра в 6, завтра в 6 утра, завтра утром, 25.09 17:00...)."""
    raw = (re.sub(r"(?i)^\s*до\s+", "", text or "")).strip().lower()
    now = now or datetime.now(tz)

    # 1. Извлекаем календарную дату, чтобы не перепутать '23.09.2026' с временем '23.09'
    date_part = None
    text_without_date = raw

    m_iso = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", raw)
    if m_iso:
        yr, mo, da = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        try:
            date_part = datetime(yr, mo, da, tzinfo=tz)
            text_without_date = raw[:m_iso.start()] + " " + raw[m_iso.end():]
        except ValueError:
            pass

    if not date_part:
        for m_d in re.finditer(r"\b(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\b", raw):
            da, mo = int(m_d.group(1)), int(m_d.group(2))
            yr = int(m_d.group(3)) if m_d.group(3) else now.year
            if yr < 100:
                yr += 2000
            if 1 <= mo <= 12 and 1 <= da <= 31:
                if m_d.group(3) or da > 12 or "/" in m_d.group(0) or "-" in m_d.group(0):
                    try:
                        date_part = datetime(yr, mo, da, tzinfo=tz)
                        text_without_date = raw[:m_d.start()] + " " + raw[m_d.end():]
                        break
                    except ValueError:
                        pass
                elif m_d.group(3) is None:
                    rest = raw[:m_d.start()] + " " + raw[m_d.end():]
                    if re.search(r"\b\d{1,2}[:.]\d{2}\b", rest) or re.search(r"(?:в|к|до)\s+\d{1,2}", rest):
                        try:
                            date_part = datetime(yr, mo, da, tzinfo=tz)
                            text_without_date = rest
                            break
                        except ValueError:
                            pass

    # Сегодня, завтра, послезавтра
    if not date_part:
        m_rel_day = re.search(r"\b(сегодня|завтра|послезавтра)\b", text_without_date)
        if m_rel_day:
            w = m_rel_day.group(1)
            if w == "сегодня":
                date_part = now
            elif w == "завтра":
                date_part = now + timedelta(days=1)
            elif w == "послезавтра":
                date_part = now + timedelta(days=2)

    # Дни недели (в пятницу, во вторник и т.д.)
    if not date_part:
        for stem, wd in _WEEKDAYS.items():
            if re.search(rf"\b{stem}", text_without_date):
                days = (wd - now.weekday()) % 7 or 7
                date_part = now + timedelta(days=days)
                break

    # Через N дней
    if not date_part:
        m_days = re.search(r"(?:через\s+)?(\d{1,3})\s*(дней|дня|день|дн)", text_without_date)
        if m_days and ("через" in text_without_date or any(u in text_without_date for u in ("дней", "дня", "день", "дн"))):
            n = int(m_days.group(1))
            date_part = now + timedelta(days=n)

    # 2. Относительное время: через 5 минут, через 15 мин, через полчаса, через 1 час 20 минут и т.д.
    if re.search(r"\b(?:через\s+)?полтора\s+час\w*\b", raw):
        return (now + timedelta(minutes=90)).replace(second=0, microsecond=0)
    if re.search(r"\b(?:через\s+)?полчас\w*\b", raw):
        return (now + timedelta(minutes=30)).replace(second=0, microsecond=0)
    if re.search(r"\b(?:через\s+)?час\b", raw) and not re.search(r"\b\d+\s*час", raw):
        return (now + timedelta(hours=1)).replace(second=0, microsecond=0)
    if re.search(r"\b(?:через\s+)?минут[уеа]\b", raw) and not re.search(r"\b\d+\s*минут", raw):
        return (now + timedelta(minutes=1)).replace(second=0, microsecond=0)

    m_hours = re.search(r"(?:через\s+)?(\d{1,3})\s*(?:час(?:а|ов)?|ч)\b", raw)
    m_mins = re.search(r"(?:через\s+)?(\d{1,3})\s*(?:минут(?:ы|у|а|ам)?|мин)\b", raw)
    if (m_hours or m_mins) and ("через" in raw or any(u in raw for u in ("мин", "минут"))):
        if not re.search(r"\b(?:в|к|до)\s+\d{1,2}\s*(?:час|ч)", raw):
            add_h = int(m_hours.group(1)) if m_hours else 0
            add_m = int(m_mins.group(1)) if m_mins else 0
            if add_h > 0 or add_m > 0:
                return (now + timedelta(hours=add_h, minutes=add_m)).replace(second=0, microsecond=0)

    # 3. Извлекаем время суток и часы из оставшегося текста
    is_morning = bool(re.search(r"\b(утр[оаеы]|утром|с утра)\b", text_without_date))
    is_day = bool(re.search(r"\b(дн[её]м|в обед|к обеду|после обеда)\b", text_without_date) or re.search(r"\b\d{1,2}\s*(?:дня|часа дня)\b", text_without_date))
    is_evening = bool(re.search(r"\b(вечер[аом]|вечером|к вечеру)\b", text_without_date))
    is_night = bool(re.search(r"\b(ноч[ьиью]|ночью|к ночи)\b", text_without_date))

    m_time = re.search(r"\b(\d{1,2})[:.](\d{2})\b", text_without_date)
    m_hour = re.search(r"(?:(?:в|к|до)\s+)?(\d{1,2})\s*(?:ч|час(?:а|ов)?)\b", text_without_date)
    if not m_time and not m_hour:
        m_hour = re.search(r"(?:\b(?:в|к|до)\s+)(\d{1,2})\b", text_without_date)

    h, m = None, 0
    if m_time:
        h, m = int(m_time.group(1)), int(m_time.group(2))
    elif m_hour:
        h, m = int(m_hour.group(1)), 0

    if h is not None:
        if is_morning:
            if h == 12:
                h = 0
        elif is_evening:
            if 1 <= h <= 11:
                h += 12
        elif is_day:
            if 1 <= h <= 6:
                h += 12
        elif is_night:
            if 8 <= h <= 11:
                h += 12
            elif h == 12:
                h = 0
        else:
            # Правило по умолчанию: 'в 6' = 18:00 (часы 1..7 считаются после полудня)
            if 1 <= h <= 7:
                h += 12
    elif is_morning:
        h, m = 8, 0    # утро по умолчанию = 08:00
    elif is_day:
        h, m = 14, 0   # день по умолчанию = 14:00
    elif is_evening:
        h, m = 19, 0   # вечер по умолчанию = 19:00
    elif is_night:
        h, m = 21, 0   # ночь по умолчанию = 21:00

    if date_part:
        target_h = h if h is not None else 18
        target_m = m if (h is not None or is_morning or is_day or is_evening or is_night) else 0
        return date_part.replace(hour=target_h, minute=target_m, second=0, microsecond=0)

    # Только время без даты
    if h is not None or is_morning or is_day or is_evening or is_night:
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target

    return None


def _clean_llm_json(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError(f"Ожидался JSON-объект, получен {type(data)}")
    return data


class Extractor:
    def __init__(self, cfg, timeout: int = 60):
        self.cfg = cfg
        self.timeout = timeout

    def ollama_available(self) -> bool:
        try:
            r = requests.get(f"{self.cfg.ollama_url}/api/tags", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def extract(self, *args, **kwargs) -> dict:
        text = kwargs.get("text")
        employees = kwargs.get("employees")
        if args:
            if len(args) == 1:
                text = args[0]
            elif len(args) == 2:
                if isinstance(args[0], str):
                    text, employees = args[0], args[1]
                else:
                    text, employees = args[1], []
            elif len(args) >= 3:
                text, employees = args[1], args[2]
        text = (text or "")[:4000]
        employees = employees or []
        res = self._via_llm(text, employees)
        if res is None:
            res = self._fallback(text, employees)
        return res

    def _via_llm(self, text: str, employees: list[dict]) -> dict | None:
        if not self.ollama_available():
            log.info("Ollama недоступна, сразу перехожу на эвристический разбор")
            return None
        try:
            text = (text or "")[:4000]
            names = ", ".join(e["name"] for e in employees) or "нет списка"
            system = (
                "Ты профессиональный ассистент персонального трекера задач.\n"
                "Твоя задача — интерпретировать текст пользователя, устранить речевой шум и опечатки, извлечь суть задачи и вернуть структурированный JSON.\n\n"
                "ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА ИНТЕРПРЕТАЦИИ И ИСПРАВЛЕНИЯ:\n"
                "1. Исходный текст получен из аудио через Whisper и может содержать ошибки из-за постороннего шума, оговорки, фонетические искажения (например 'праверить ачот' вместо 'проверить отчет'), слова-паразиты ('ну', 'эээ', 'короче', 'типа') и отсутствие знаков препинания.\n"
                "2. ТЫ ОБЯЗАН ИНТЕРПРЕТИРОВАТЬ И ИСПРАВИТЬ СКАЗАННОЕ: восстанови исходный смысл слов, искаженных шумом, исправь орфографию, падежи, грамматику и расставь пунктуацию.\n"
                "3. 'title': сформируй четкое, емкое название задачи в инфинитиве (до 8 слов, с заглавной буквы, грамотно). Пример: 'Проверить отчет по продажам за сентябрь'.\n"
                "4. 'description': сформулируй полное, грамматически безупречное, связное описание задачи литературным деловым языком без слов-паразитов и без ошибок распознавания.\n"
                "5. 'smart': сформулируй задачу строго по критериям SMART (Конкретная цель, Измеримый результат, Критерий готовности).\n"
                "6. 'assignee': имя исполнителя из списка сотрудников (в именительном падеже, например 'Иван') или null, если не указан.\n"
                "7. 'deadline': дата и время в формате ДД.ММ.ГГГГ ЧЧ:ММ (например 23.09.2026 18:00) или null.\n"
                "8. 'deadline_iso': ISO 8601 строка даты/времени (например 2026-09-23T18:00:00+03:00) или null.\n\n"
                "Правила определения времени по умолчанию:\n"
                "- 'в 6' (без слова 'утра') = 18:00. Часы 1..7 без слова 'утра' считаются второй половиной дня (1->13:00, ..., 6->18:00).\n"
                "- 'в 6 утра' = 06:00.\n"
                "- утро по умолчанию = 08:00 ('завтра утром' -> 08:00).\n"
                "- день по умолчанию = 14:00 ('завтра днем' -> 14:00).\n"
                "- вечер по умолчанию = 19:00 ('завтра вечером' -> 19:00).\n"
                "- ночь по умолчанию = 21:00 ('завтра ночью' -> 21:00).\n"
                "- 'через N минут/часов' (например 'через 5 минут') отсчитывается от текущего времени.\n\n"
                f"Список доступных сотрудников: {names}\n"
                f"Текущая дата и время: {datetime.now(self.cfg.tz).strftime('%d.%m.%Y %H:%M')} ({datetime.now(self.cfg.tz).isoformat()})\n\n"
                "Верни ТОЛЬКО валидный JSON формата: {\"title\": \"...\", \"description\": \"...\", \"smart\": \"...\", \"assignee\": \"...\", \"deadline\": \"...\", \"deadline_iso\": \"...\"}"
            )
            payload = {
                "model": self.cfg.ollama_model,
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
            }
            r = requests.post(
                f"{self.cfg.ollama_url}/api/chat", json=payload, timeout=self.timeout
            )
            r.raise_for_status()
            parsed = _clean_llm_json(r.json()["message"]["content"])
            clean = {}
            for k in ("title", "description", "smart", "assignee", "deadline", "deadline_iso"):
                v = parsed.get(k)
                if isinstance(v, str) and v.strip().lower() in ("null", "none", ""):
                    v = None
                if isinstance(v, dict):
                    v = None
                clean[k] = v

            # Приоритет отдаем детерминированному парсеру правил времени в MSK
            dl_dt = parse_deadline(text, self.cfg.tz)
            if not dl_dt and clean.get("deadline"):
                dl_dt = parse_deadline(str(clean["deadline"]), self.cfg.tz)
            if not dl_dt and clean.get("deadline_iso"):
                try:
                    raw_dl = datetime.fromisoformat(clean["deadline_iso"])
                    if raw_dl.tzinfo is None:
                        dl_dt = raw_dl.replace(tzinfo=self.cfg.tz)
                    else:
                        dl_dt = raw_dl.astimezone(self.cfg.tz)
                except Exception:
                    dl_dt = None

            if dl_dt:
                if dl_dt.tzinfo is None:
                    dl_dt = dl_dt.replace(tzinfo=self.cfg.tz)
                else:
                    dl_dt = dl_dt.astimezone(self.cfg.tz)

            dl_str = dl_dt.strftime("%d.%m.%Y %H:%M") if dl_dt else clean.get("deadline")
            dl_iso = dl_dt.isoformat() if dl_dt else None

            return {
                "title": str(clean.get("title") or "")[:200],
                "description": str(clean.get("description") or ""),
                "smart": str(clean.get("smart") or ""),
                "assignee": clean.get("assignee"),
                "deadline": dl_str,
                "deadline_iso": dl_iso,
                "source": "llm",
            }
        except Exception as exc:
            log.warning("Ollama-разбор недоступен (%s), перехожу на эвристику", exc)
            return None

    def _fallback(self, text: str, employees: list[dict]) -> dict:
        now = datetime.now(self.cfg.tz)
        # Очистка речевого шума для эвристики
        cleaned = re.sub(r"\b(?:ну|ээ+|мм+|короче|типа|в\s+общем|как\s+бы|значит|слушай)\b", "", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = re.sub(r"^[,\s.:;-]+", "", cleaned)
        if cleaned and cleaned[0].islower():
            cleaned = cleaned[0].upper() + cleaned[1:]

        lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
        title = (lines[0] if lines else cleaned)[:120]
        deadline = parse_deadline(text, self.cfg.tz, now)
        dlstr = deadline.strftime("%d.%m.%Y %H:%M") if deadline else None
        smart = (
            f"Цель: {title}. "
            + (f"Дедлайн: {dlstr}. " if dlstr else "")
            + "Критерий готовности: выполнить и отчитаться в трекере."
        )
        return {
            "title": title,
            "description": cleaned or text,
            "smart": smart,
            "assignee": self._guess_assignee(text, employees),
            "deadline": dlstr,
            "deadline_iso": deadline.isoformat() if deadline else None,
            "source": "heuristic",
        }

    @staticmethod
    def _guess_assignee(text: str, employees: list[dict]) -> str | None:
        low = text.lower()
        aliases = {
            "ваня": "иван",
            "ване": "иван",
            "ваню": "иван",
            "саша": "александр",
            "саше": "александр",
            "сашу": "александр",
            "дима": "дмитрий",
            "диме": "дмитрий",
            "леша": "алексей",
            "лёша": "алексей",
            "сережа": "сергей",
            "серёжа": "сергей",
            "миша": "михаил",
            "мише": "михаил",
            "коля": "николай",
            "паша": "павел",
        }
        for e in employees:
            name_low = e["name"].lower()
            if name_low in low:
                return e["name"]
            for alias, canonical in aliases.items():
                if canonical == name_low and re.search(rf"\b{alias}\b", low):
                    return e["name"]
        return None