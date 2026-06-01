"""
PDS-Ultimate Speech Engine (Part 14)
======================================
Движок распознавания речи на базе Vosk (offline, бесплатно).

Замена Faster-Whisper на Vosk:
- ✅ Полностью offline (без GPU, без API)
- ✅ Поддержка русского, английского, туркменского
- ✅ Низкие требования к ресурсам (~300MB RAM)
- ✅ Распознавание из WAV, OGG, MP3, MP4
- ✅ Генерация субтитров (SRT)
- ✅ Пословная разметка с таймингами

Использование:
    from pds_ultimate.core.speech_engine import speech_engine

    text = speech_engine.transcribe("/path/to/audio.wav")
    result = speech_engine.transcribe_detailed("/path/to/audio.wav")
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from pds_ultimate.config import config, logger

# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class WordTiming:
    """Слово с таймингом."""
    word: str
    start: float     # секунды
    end: float       # секунды
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "word": self.word,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "confidence": round(self.confidence, 3),
        }


@dataclass
class TranscriptionResult:
    """Результат распознавания речи."""
    text: str = ""
    words: list[WordTiming] = field(default_factory=list)
    language: str = ""
    duration_seconds: float = 0.0
    engine: str = "vosk"
    success: bool = True
    error: str = ""

    @property
    def word_count(self) -> int:
        return len(self.text.split()) if self.text else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "word_count": self.word_count,
            "words_with_timing": len(self.words),
            "language": self.language,
            "duration_seconds": round(self.duration_seconds, 2),
            "engine": self.engine,
            "success": self.success,
            "error": self.error,
        }

    def generate_srt(self, words_per_line: int = 10) -> str:
        """Сгенерировать SRT субтитры."""
        if not self.words:
            return ""

        lines: list[str] = []
        idx = 1
        for i in range(0, len(self.words), words_per_line):
            chunk = self.words[i:i + words_per_line]
            if not chunk:
                continue
            start = chunk[0].start
            end = chunk[-1].end
            text = " ".join(w.word for w in chunk)

            start_ts = _format_srt_time(start)
            end_ts = _format_srt_time(end)

            lines.append(str(idx))
            lines.append(f"{start_ts} --> {end_ts}")
            lines.append(text)
            lines.append("")
            idx += 1

        return "\n".join(lines)


def _format_srt_time(seconds: float) -> str:
    """Конвертировать секунды в SRT формат: HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ═══════════════════════════════════════════════════════════════════════════════
# SPEECH ENGINE
# ═══════════════════════════════════════════════════════════════════════════════


# Поддерживаемые модели Vosk
VOSK_MODELS = {
    "ru": {
        "name": "vosk-model-small-ru-0.22",
        "url": "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip",
        "size_mb": 45,
    },
    "en": {
        "name": "vosk-model-small-en-us-0.15",
        "url": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
        "size_mb": 40,
    },
    "ru-large": {
        "name": "vosk-model-ru-0.42",
        "url": "https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip",
        "size_mb": 1800,
    },
    "en-large": {
        "name": "vosk-model-en-us-0.42-gigaspeech",
        "url": "https://alphacephei.com/vosk/models/vosk-model-en-us-0.42-gigaspeech.zip",
        "size_mb": 2300,
    },
}

# Аудио-форматы, поддерживаемые через ffmpeg конвертацию
SUPPORTED_AUDIO_FORMATS = {
    ".wav", ".ogg", ".oga", ".mp3", ".m4a", ".flac",
    ".wma", ".aac", ".opus", ".mp4", ".mov", ".webm",
}


class SpeechEngine:
    """
    Движок распознавания речи на базе Vosk.

    Поддерживает:
    - Русский, английский
    - Offline распознавание (без API)
    - Пословная разметка с таймингами
    - Генерация SRT субтитров
    - Авто-конвертация из любого формата через ffmpeg
    """

    def __init__(self) -> None:
        self._models: dict[str, Any] = {}  # lang → Model
        self._models_dir: Path = config.whisper.model_dir
        self._default_language: str = config.whisper.language
        self._initialized = False
        self._total_transcriptions = 0
        self._total_seconds = 0.0
        self._lazy = config.whisper.lazy_load
        self._unload_after = config.whisper.unload_after
        self._max_seconds = config.whisper.max_voice_seconds

    def unload(self) -> None:
        """Free RAM after transcription."""
        self._models.clear()
        self._initialized = False
        logger.debug("Vosk model unloaded from RAM")

    def _ensure_models_dir(self) -> None:
        """Создать директорию для моделей."""
        self._models_dir.mkdir(parents=True, exist_ok=True)

    def _download_model(self, lang: str) -> bool:
        """Скачать Vosk-модель если её нет (~45MB для ru small)."""
        import urllib.request
        import zipfile

        model_info = VOSK_MODELS.get(lang, VOSK_MODELS["ru"])
        model_name = model_info["name"]
        model_path = self._models_dir / model_name
        if model_path.exists():
            return True

        self._ensure_models_dir()
        zip_path = self._models_dir / f"{model_name}.zip"
        url = model_info["url"]
        logger.info(
            f"Скачиваю Vosk модель {model_name} (~{model_info['size_mb']} MB)...")
        try:
            urllib.request.urlretrieve(url, zip_path)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(self._models_dir)
            zip_path.unlink(missing_ok=True)
            if model_path.exists():
                logger.info(f"Vosk модель готова: {model_path}")
                return True
        except Exception as exc:
            logger.error(f"Не удалось скачать Vosk модель: {exc}")
            zip_path.unlink(missing_ok=True)
        return False

    def _get_model(self, language: str = "") -> Any:
        """Получить или загрузить модель Vosk."""
        lang = language or self._default_language

        if lang in self._models:
            return self._models[lang]

        try:
            from vosk import Model, SetLogLevel
            SetLogLevel(-1)  # Подавить логи Vosk

            self._ensure_models_dir()

            # Ищем модель
            model_info = VOSK_MODELS.get(lang, VOSK_MODELS.get("ru"))
            model_name = model_info["name"]
            model_path = self._models_dir / model_name

            if not model_path.exists():
                # Пробуем альтернативные пути
                alt_paths = [
                    Path(model_name),
                    Path.home() / ".vosk" / model_name,
                    Path("/opt/vosk") / model_name,
                ]
                for alt in alt_paths:
                    if alt.exists():
                        model_path = alt
                        break

            if not model_path.exists():
                if not self._download_model(lang):
                    logger.warning(
                        f"Модель Vosk для '{lang}' не найдена. "
                        f"Скачайте: {model_info.get('url', '')}"
                    )
                    return None

            if model_path.exists():
                model = Model(str(model_path))
            else:
                return None

            self._models[lang] = model
            self._initialized = True
            logger.info(f"Vosk модель загружена: {lang}")
            return model

        except ImportError:
            logger.warning(
                "Vosk не установлен. Установите: pip install vosk"
            )
            return None
        except Exception as e:
            logger.error(f"Ошибка загрузки Vosk модели: {e}")
            return None

    def _convert_to_wav(self, audio_path: str) -> Optional[str]:
        """Конвертировать аудио в WAV 16kHz mono через ffmpeg."""
        ext = Path(audio_path).suffix.lower()

        if ext == ".wav":
            # Проверяем формат WAV
            try:
                with wave.open(audio_path, "rb") as wf:
                    if (wf.getnchannels() == 1 and
                            wf.getsampwidth() == 2 and
                            wf.getframerate() == 16000):
                        return audio_path
            except Exception:
                pass

        # Конвертируем через ffmpeg
        tmp = tempfile.NamedTemporaryFile(
            suffix=".wav", delete=False, prefix="vosk_")
        tmp.close()

        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-i", audio_path,
                    "-ar", "16000", "-ac", "1",
                    "-sample_fmt", "s16",
                    tmp.name,
                ],
                capture_output=True,
                timeout=60,
            )
            if result.returncode == 0:
                return tmp.name
            else:
                logger.error(
                    f"ffmpeg ошибка: {result.stderr.decode()[:200]}")
                os.unlink(tmp.name)
                return None
        except FileNotFoundError:
            logger.error("ffmpeg не найден. Установите: apt install ffmpeg")
            os.unlink(tmp.name)
            return None
        except Exception as e:
            logger.error(f"Ошибка конвертации аудио: {e}")
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            return None

    def transcribe(self, audio_path: str, language: str = "") -> str:
        """
        Транскрибировать аудио в текст.

        Args:
            audio_path: Путь к аудио-файлу (любой формат)
            language: Язык (ru, en). По умолчанию из config.

        Returns:
            Распознанный текст (строка).
        """
        result = self.transcribe_detailed(audio_path, language)
        return result.text

    def transcribe_detailed(self, audio_path: str,
                            language: str = "") -> TranscriptionResult:
        """
        Транскрибировать с полной информацией.

        Returns:
            TranscriptionResult с текстом, таймингами, метаданными.
        """
        lang = language or self._default_language
        result = TranscriptionResult(language=lang)

        if getattr(getattr(config, "whisper", None), "engine", "vosk") == "off":
            result.success = False
            result.error = "STT disabled (STT_ENGINE=off)"
            return result

        # Проверяем файл
        if not os.path.exists(audio_path):
            result.success = False
            result.error = f"Файл не найден: {audio_path}"
            return result

        # Получаем модель
        model = self._get_model(lang)
        if model is None:
            # Fallback: пробуем faster-whisper
            return self._fallback_whisper(audio_path, lang)

        # Конвертируем в WAV
        wav_path = self._convert_to_wav(audio_path)
        if wav_path is None:
            result.success = False
            result.error = "Не удалось конвертировать аудио в WAV"
            return result

        tmp_created = wav_path != audio_path

        try:
            from vosk import KaldiRecognizer

            wf = wave.open(wav_path, "rb")

            if (wf.getnchannels() != 1 or wf.getsampwidth() != 2 or
                    wf.getcomptype() != "NONE"):
                result.success = False
                result.error = "Audio must be WAV mono PCM 16-bit"
                wf.close()
                return result

            rec = KaldiRecognizer(model, wf.getframerate())
            rec.SetWords(True)

            all_results = []
            while True:
                data = wf.readframes(4000)
                if len(data) == 0:
                    break
                if rec.AcceptWaveform(data):
                    all_results.append(json.loads(rec.Result()))
            all_results.append(json.loads(rec.FinalResult()))

            # Длительность
            result.duration_seconds = wf.getnframes() / wf.getframerate()
            wf.close()

            # Собираем текст и слова
            text_parts: list[str] = []
            for res in all_results:
                if "text" in res and res["text"]:
                    text_parts.append(res["text"])
                if "result" in res:
                    for w in res["result"]:
                        result.words.append(WordTiming(
                            word=w.get("word", ""),
                            start=w.get("start", 0.0),
                            end=w.get("end", 0.0),
                            confidence=w.get("conf", 0.0),
                        ))

            result.text = " ".join(text_parts)
            result.success = True

            self._total_transcriptions += 1
            self._total_seconds += result.duration_seconds

            logger.info(
                f"Vosk: распознано {result.word_count} слов "
                f"за {result.duration_seconds:.1f}с аудио"
            )

        except ImportError:
            out = self._fallback_whisper(audio_path, lang)
            if self._unload_after:
                self.unload()
            return out
        except Exception as e:
            result.success = False
            result.error = f"Ошибка Vosk: {e}"
            logger.error(f"Ошибка Vosk транскрибации: {e}")
        finally:
            if tmp_created:
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass
            if self._unload_after:
                self.unload()

        return result

    def _fallback_whisper(self, audio_path: str,
                          lang: str) -> TranscriptionResult:
        """Fallback на faster-whisper если Vosk недоступен."""
        result = TranscriptionResult(language=lang, engine="faster-whisper")
        try:
            from faster_whisper import WhisperModel

            device = getattr(config.whisper, "device", "cpu")
            if device == "auto":
                device = "cpu"

            model = WhisperModel(
                config.whisper.model_size,
                device=device,
                compute_type=config.whisper.compute_type,
            )
            segments, info = model.transcribe(
                audio_path,
                language=lang,
                beam_size=5,
                vad_filter=True,
            )
            text_parts = [seg.text.strip() for seg in segments]
            result.text = " ".join(text_parts)
            result.success = True
            result.duration_seconds = info.duration if hasattr(
                info, "duration") else 0.0
            logger.info(f"Whisper fallback: {result.word_count} слов")
        except ImportError:
            result.success = False
            result.error = (
                "Ни Vosk, ни faster-whisper не установлены. "
                "Установите: pip install vosk"
            )
        except Exception as e:
            result.success = False
            result.error = f"Fallback whisper ошибка: {e}"
        return result

    def preload(self) -> bool:
        """
        Предзагрузить модель в оперативную память — вызывается при старте бота.
        Первая транскрибация будет мгновенной (без задержки на загрузку).
        """
        if self._initialized:
            return True
        if getattr(getattr(config, "whisper", None), "engine", "vosk") == "off":
            return False
        try:
            model = self._get_model(self._default_language)
            if model is not None:
                logger.info(
                    f"✅ Vosk модель предзагружена в RAM ({self._default_language})")
                return True
        except Exception as e:
            logger.warning(f"Vosk preload: {e}")
        return False

    async def async_transcribe(self, audio_path: str, language: str = "") -> str:
        """
        Асинхронная обёртка над transcribe — не блокирует event loop.
        Запускает тяжёлую CPU-операцию в отдельном потоке.
        """
        import asyncio
        return await asyncio.to_thread(self.transcribe, audio_path, language)

    def is_available(self) -> bool:
        """Проверить, доступен ли STT движок."""
        try:
            import vosk  # noqa: F401
            return True
        except ImportError:
            try:
                import faster_whisper  # noqa: F401
                return True
            except ImportError:
                return False

    def get_stats(self) -> dict[str, Any]:
        """Статистика движка."""
        return {
            "engine": "vosk" if self._models else "not_loaded",
            "initialized": self._initialized,
            "models_loaded": list(self._models.keys()),
            "default_language": self._default_language,
            "total_transcriptions": self._total_transcriptions,
            "total_audio_seconds": round(self._total_seconds, 1),
            "models_dir": str(self._models_dir),
            "available": self.is_available(),
        }


# ─── Глобальный экземпляр ────────────────────────────────────────────────────

speech_engine = SpeechEngine()
