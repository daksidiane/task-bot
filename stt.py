"""Транскрипция голосовых локальным Whisper (модель base/small по ТЗ)."""
from __future__ import annotations

import logging
import os
import shutil
import tempfile

from pathlib import Path

log = logging.getLogger(__name__)

_model = None
_model_name = None


def _ensure_ffmpeg() -> None:
    """Whisper декодирует аудио через ffmpeg. Берём системный или из imageio-ffmpeg."""
    if shutil.which("ffmpeg"):
        return
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError(
            "ffmpeg не найден. Посади: pip install imageio-ffmpeg "
            "(или установи ffmpeg отдельно и добавь в PATH)."
        ) from exc
    # imageio-файл называется ffmpeg-win*-v*.exe, а Whisper ищет именно ffmpeg.exe —
    # кладём копию под нужным именем в изолированную проектную папку data/bin (не в общий /tmp).
    if os.path.basename(exe).lower() != "ffmpeg.exe":
        bin_dir = Path(__file__).resolve().parent / "data" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        target = bin_dir / "ffmpeg.exe"
        if not target.exists() or target.stat().st_size != os.path.getsize(exe):
            shutil.copy2(exe, target)
        bin_str = str(bin_dir)
        target_str = str(target)
    else:
        bin_str = os.path.dirname(exe)
        target_str = exe
    os.environ["PATH"] = bin_str + os.pathsep + os.environ.get("PATH", "")
    log.info("ffmpeg задействован: %s", target_str)


def whisper_available() -> bool:
    try:
        import whisper  # noqa: F401
        return True
    except ImportError:
        return False


def transcribe(cfg, audio_path: str) -> str:
    global _model, _model_name
    _ensure_ffmpeg()
    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError(
            "openai-whisper не установлена. Ставь отдельно: "
            "pip install -r requirements-ai.txt (понадобятся ffmpeg и torch)."
        ) from exc

    if _model is None or _model_name != cfg.whisper_model:
        log.info("Загрузка модели whisper (%s)...", cfg.whisper_model)
        _model = whisper.load_model(cfg.whisper_model)
        _model_name = cfg.whisper_model

    result = _model.transcribe(audio_path, language="ru")
    return (result.get("text") or "").strip()