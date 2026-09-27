"""Проверка Whisper вручную.

Использование:
    python stt_check.py                  # проверит на тестовом WAV (тишина)
    python stt_check.py путь\аудио.ogg   # распознает реальный файл
"""
from __future__ import annotations

import os
import sys
import time
import wave


def _utf8_console():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass


def _make_silence(path: str) -> str:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * (16000 * 2))
    return path


def main() -> int:
    _utf8_console()
    model = os.getenv("WHISPER_MODEL", "base").strip().lower()
    audio = sys.argv[1] if len(sys.argv) > 1 else _make_silence(os.path.join(os.environ.get("TEMP", "."), "stt_check_test.wav"))

    from stt import transcribe

    cfg = type("Cfg", (), {"whisper_model": model})()
    print(f"Модель: {model}. Файл: {audio}")
    t = time.time()
    try:
        text = transcribe(cfg, audio)
    except Exception as exc:
        print("ОШИБКА:", exc)
        return 1
    print(f"Распознано ({time.time() - t:.1f} сек):\n{text!r}")
    print("Whisper работает." if text else "Whisper работает (пустой результат — возможно, это тишина).")
    return 0


if __name__ == "__main__":
    sys.exit(main())