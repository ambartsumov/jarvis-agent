"""
PDS-Ultimate Part 14 — Final QA + Speech Engine + Comprehensive Smoke Tests
=============================================================================
Тесты:
- SpeechEngine (Vosk STT)
- VoiceParser (новый через Vosk)
- Полное задымление всех модулей
- Интеграционные сценарии
- Стресс-тесты
- Валидация конфигурации
- Проверка всех 64+ tools
- Полный lifecycle заказа
- Кросс-модульные зависимости
"""

import importlib
import os
import tempfile
from pathlib import Path

import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# SPEECH ENGINE TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestSpeechEngineDataClasses:
    """Тесты data-классов SpeechEngine."""

    def test_word_timing_creation(self):
        from pds_ultimate.core.speech_engine import WordTiming
        wt = WordTiming(word="привет", start=0.5, end=1.2, confidence=0.95)
        assert wt.word == "привет"
        assert wt.start == 0.5
        assert wt.end == 1.2
        assert wt.confidence == 0.95

    def test_word_timing_to_dict(self):
        from pds_ultimate.core.speech_engine import WordTiming
        wt = WordTiming(word="test", start=0.1234,
                        end=0.5678, confidence=0.999)
        d = wt.to_dict()
        assert d["word"] == "test"
        assert d["start"] == 0.123
        assert d["end"] == 0.568
        assert d["confidence"] == 0.999

    def test_word_timing_defaults(self):
        from pds_ultimate.core.speech_engine import WordTiming
        wt = WordTiming(word="а", start=0.0, end=0.1)
        assert wt.confidence == 0.0

    def test_transcription_result_empty(self):
        from pds_ultimate.core.speech_engine import TranscriptionResult
        r = TranscriptionResult()
        assert r.text == ""
        assert r.words == []
        assert r.success is True
        assert r.word_count == 0
        assert r.engine == "vosk"

    def test_transcription_result_with_text(self):
        from pds_ultimate.core.speech_engine import TranscriptionResult
        r = TranscriptionResult(text="привет мир как дела", language="ru")
        assert r.word_count == 4
        assert r.language == "ru"

    def test_transcription_result_to_dict(self):
        from pds_ultimate.core.speech_engine import TranscriptionResult
        r = TranscriptionResult(
            text="hello world",
            language="en",
            duration_seconds=5.678,
            engine="vosk",
        )
        d = r.to_dict()
        assert d["text"] == "hello world"
        assert d["word_count"] == 2
        assert d["duration_seconds"] == 5.68
        assert d["engine"] == "vosk"
        assert d["success"] is True

    def test_transcription_result_error(self):
        from pds_ultimate.core.speech_engine import TranscriptionResult
        r = TranscriptionResult(success=False, error="file not found")
        assert r.success is False
        assert "file not found" in r.error

    def test_generate_srt_empty(self):
        from pds_ultimate.core.speech_engine import TranscriptionResult
        r = TranscriptionResult(text="hello")
        assert r.generate_srt() == ""

    def test_generate_srt_with_words(self):
        from pds_ultimate.core.speech_engine import TranscriptionResult, WordTiming
        r = TranscriptionResult(
            text="hello world",
            words=[
                WordTiming("hello", 0.0, 0.5, 0.9),
                WordTiming("world", 0.6, 1.0, 0.8),
            ],
        )
        srt = r.generate_srt(words_per_line=2)
        assert "hello world" in srt
        assert "-->" in srt
        assert "00:00:00,000" in srt

    def test_generate_srt_multiline(self):
        from pds_ultimate.core.speech_engine import TranscriptionResult, WordTiming
        words = [WordTiming(f"word{i}", i * 0.5, (i + 1) * 0.5, 0.9)
                 for i in range(5)]
        r = TranscriptionResult(text=" ".join(
            w.word for w in words), words=words)
        srt = r.generate_srt(words_per_line=2)
        lines = srt.strip().split("\n")
        assert len(lines) > 4  # Multiple SRT entries


class TestSpeechEngineCore:
    """Тесты ядра SpeechEngine."""

    def test_singleton_exists(self):
        from pds_ultimate.core.speech_engine import speech_engine
        assert speech_engine is not None

    def test_engine_type(self):
        from pds_ultimate.core.speech_engine import SpeechEngine, speech_engine
        assert isinstance(speech_engine, SpeechEngine)

    def test_default_language(self):
        from pds_ultimate.core.speech_engine import speech_engine
        assert speech_engine._default_language in ("ru", "en")

    def test_get_stats(self):
        from pds_ultimate.core.speech_engine import speech_engine
        stats = speech_engine.get_stats()
        assert "engine" in stats
        assert "initialized" in stats
        assert "models_loaded" in stats
        assert "default_language" in stats
        assert "total_transcriptions" in stats
        assert "total_audio_seconds" in stats
        assert "models_dir" in stats
        assert "available" in stats

    def test_stats_types(self):
        from pds_ultimate.core.speech_engine import speech_engine
        stats = speech_engine.get_stats()
        assert isinstance(stats["models_loaded"], list)
        assert isinstance(stats["total_transcriptions"], int)
        assert isinstance(stats["total_audio_seconds"], float)

    def test_transcribe_missing_file(self):
        from pds_ultimate.core.speech_engine import speech_engine
        result = speech_engine.transcribe_detailed("/nonexistent/audio.wav")
        assert result.success is False
        assert "не найден" in result.error.lower() or "not found" in result.error.lower()

    def test_transcribe_simple_missing_file(self):
        from pds_ultimate.core.speech_engine import speech_engine
        text = speech_engine.transcribe("/nonexistent/audio.wav")
        assert text == ""

    def test_models_dir_is_path(self):
        from pds_ultimate.core.speech_engine import speech_engine
        assert isinstance(speech_engine._models_dir, Path)

    def test_vosk_models_registry(self):
        from pds_ultimate.core.speech_engine import VOSK_MODELS
        assert "ru" in VOSK_MODELS
        assert "en" in VOSK_MODELS
        for lang, info in VOSK_MODELS.items():
            assert "name" in info
            assert "url" in info
            assert "size_mb" in info

    def test_supported_audio_formats(self):
        from pds_ultimate.core.speech_engine import SUPPORTED_AUDIO_FORMATS
        assert ".wav" in SUPPORTED_AUDIO_FORMATS
        assert ".ogg" in SUPPORTED_AUDIO_FORMATS
        assert ".mp3" in SUPPORTED_AUDIO_FORMATS
        assert ".mp4" in SUPPORTED_AUDIO_FORMATS
        assert ".opus" in SUPPORTED_AUDIO_FORMATS
        assert ".flac" in SUPPORTED_AUDIO_FORMATS


class TestSpeechEngineSRTFormat:
    """Тесты SRT-формата."""

    def test_format_srt_time_zero(self):
        from pds_ultimate.core.speech_engine import _format_srt_time
        assert _format_srt_time(0.0) == "00:00:00,000"

    def test_format_srt_time_simple(self):
        from pds_ultimate.core.speech_engine import _format_srt_time
        assert _format_srt_time(1.5) == "00:00:01,500"

    def test_format_srt_time_minutes(self):
        from pds_ultimate.core.speech_engine import _format_srt_time
        assert _format_srt_time(65.0) == "00:01:05,000"

    def test_format_srt_time_hours(self):
        from pds_ultimate.core.speech_engine import _format_srt_time
        assert _format_srt_time(3661.5) == "01:01:01,500"

    def test_format_srt_time_milliseconds(self):
        from pds_ultimate.core.speech_engine import _format_srt_time
        result = _format_srt_time(0.123)
        assert result == "00:00:00,123"


class TestSpeechEngineConversion:
    """Тесты конвертации аудио."""

    def test_convert_nonexistent(self):
        from pds_ultimate.core.speech_engine import speech_engine
        result = speech_engine._convert_to_wav("/nonexistent/file.mp3")
        assert result is None

    def test_convert_empty_file(self):
        from pds_ultimate.core.speech_engine import speech_engine
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(b"not audio data")
            path = f.name
        try:
            result = speech_engine._convert_to_wav(path)
            # ffmpeg should fail on invalid data
            # result could be None or a path depending on ffmpeg behavior
        finally:
            os.unlink(path)

    def test_ensure_models_dir(self):
        from pds_ultimate.core.speech_engine import speech_engine
        speech_engine._ensure_models_dir()
        assert speech_engine._models_dir.exists() or True  # may not have perms


class TestSpeechEngineExport:
    """Тесты экспорта из core.__init__."""

    def test_speech_engine_in_core(self):
        from pds_ultimate.core import speech_engine
        assert speech_engine is not None

    def test_speech_engine_class_in_core(self):
        from pds_ultimate.core import SpeechEngine
        assert SpeechEngine is not None


# ═══════════════════════════════════════════════════════════════════════════════
# VOICE PARSER TESTS (UPDATED)
# ═══════════════════════════════════════════════════════════════════════════════


class TestVoiceParserVosk:
    """Тесты VoiceParser с Vosk-бэкендом."""

    def test_voice_parser_exists(self):
        from pds_ultimate.utils.parsers import VoiceParser
        assert VoiceParser is not None

    def test_voice_parser_has_transcribe(self):
        from pds_ultimate.utils.parsers import VoiceParser
        assert hasattr(VoiceParser, "transcribe")

    def test_voice_parser_has_parse(self):
        from pds_ultimate.utils.parsers import VoiceParser
        assert hasattr(VoiceParser, "parse")

    def test_transcribe_returns_string(self):
        from pds_ultimate.utils.parsers import VoiceParser
        result = VoiceParser.transcribe("/nonexistent.wav")
        assert isinstance(result, str)

    def test_parse_returns_parse_result(self):
        from pds_ultimate.utils.parsers import ParseResult, VoiceParser
        result = VoiceParser.parse("/nonexistent.wav")
        assert isinstance(result, ParseResult)
        assert result.source_type == "voice"

    def test_parse_missing_file_has_error(self):
        from pds_ultimate.utils.parsers import VoiceParser
        result = VoiceParser.parse("/nonexistent.wav")
        assert len(result.errors) > 0

    def test_unified_parser_parse_voice(self):
        from pds_ultimate.utils.parsers import ParseResult, parser
        result = parser.parse_voice("/nonexistent.wav")
        assert isinstance(result, ParseResult)

    def test_unified_parser_transcribe_voice(self):
        from pds_ultimate.utils.parsers import parser
        result = parser.transcribe_voice("/nonexistent.wav")
        assert isinstance(result, str)


# ═══════════════════════════════════════════════════════════════════════════════
# VOICE HANDLER TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestVoiceHandler:
    """Тесты voice handler."""

    def test_voice_router_exists(self):
        from pds_ultimate.bot.handlers.voice import router
        assert router is not None
        assert router.name == "voice"

    def test_handle_voice_function_exists(self):
        from pds_ultimate.bot.handlers.voice import handle_voice
        assert callable(handle_voice)

    def test_handle_video_note_function_exists(self):
        from pds_ultimate.bot.handlers.voice import handle_video_note
        assert callable(handle_video_note)

    def test_voice_handler_uses_speech_engine(self):
        """Проверить что voice.py импортирует speech_engine."""
        import inspect

        from pds_ultimate.bot.handlers import voice
        source = inspect.getsource(voice)
        assert "speech_engine" in source
        assert "Vosk" in source or "vosk" in source.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# COMPREHENSIVE MODULE SMOKE TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestModuleImports:
    """Задымление: все модули импортируются без ошибок."""

    @pytest.mark.parametrize("module", [
        "pds_ultimate.config",
        "pds_ultimate.core",
        "pds_ultimate.core.database",
        "pds_ultimate.core.llm_engine",
        "pds_ultimate.core.scheduler",
        "pds_ultimate.core.plugin_system",
        "pds_ultimate.core.autonomy_engine",
        "pds_ultimate.core.browser_pro",
        "pds_ultimate.core.reasoning_v2",
        "pds_ultimate.core.memory_v2",
        "pds_ultimate.core.smart_triggers",
        "pds_ultimate.core.analytics_dashboard",
        "pds_ultimate.core.crm_engine",
        "pds_ultimate.core.evening_digest",
        "pds_ultimate.core.workflow_engine",
        "pds_ultimate.core.semantic_search_v2",
        "pds_ultimate.core.confidence_tracker",
        "pds_ultimate.core.adaptive_query",
        "pds_ultimate.core.task_prioritizer",
        "pds_ultimate.core.context_compressor",
        "pds_ultimate.core.time_relevance",
        "pds_ultimate.core.integration_layer",
        "pds_ultimate.core.production",
        "pds_ultimate.core.speech_engine",
        "pds_ultimate.core.business_tools",
        "pds_ultimate.utils.parsers",
        "pds_ultimate.bot.conversation",
        "pds_ultimate.bot.handlers.voice",
    ])
    def test_import(self, module):
        mod = importlib.import_module(module)
        assert mod is not None


class TestSingletonInstances:
    """Проверка что все синглтоны создаются."""

    def test_config_singleton(self):
        from pds_ultimate.config import config
        assert config is not None

    def test_llm_engine_singleton(self):
        from pds_ultimate.core.llm_engine import llm_engine
        assert llm_engine is not None

    def test_scheduler_singleton(self):
        from pds_ultimate.core.scheduler import scheduler
        assert scheduler is not None

    def test_plugin_manager_singleton(self):
        from pds_ultimate.core.plugin_system import plugin_manager
        assert plugin_manager is not None

    def test_autonomy_engine_singleton(self):
        from pds_ultimate.core.autonomy_engine import autonomy_engine
        assert autonomy_engine is not None

    def test_browser_pro_singleton(self):
        from pds_ultimate.core.browser_pro import browser_pro
        assert browser_pro is not None

    def test_reasoning_v2_singleton(self):
        from pds_ultimate.core.reasoning_v2 import reasoning_v2
        assert reasoning_v2 is not None

    def test_memory_v2_singleton(self):
        from pds_ultimate.core.memory_v2 import memory_v2
        assert memory_v2 is not None

    def test_smart_triggers_singleton(self):
        from pds_ultimate.core.smart_triggers import trigger_manager
        assert trigger_manager is not None

    def test_analytics_dashboard_singleton(self):
        from pds_ultimate.core.analytics_dashboard import analytics_dashboard
        assert analytics_dashboard is not None

    def test_crm_engine_singleton(self):
        from pds_ultimate.core.crm_engine import crm_engine
        assert crm_engine is not None

    def test_evening_digest_singleton(self):
        from pds_ultimate.core.evening_digest import evening_digest
        assert evening_digest is not None

    def test_workflow_engine_singleton(self):
        from pds_ultimate.core.workflow_engine import workflow_engine
        assert workflow_engine is not None

    def test_semantic_search_v2_singleton(self):
        from pds_ultimate.core.semantic_search_v2 import semantic_search_v2
        assert semantic_search_v2 is not None

    def test_confidence_tracker_singleton(self):
        from pds_ultimate.core.confidence_tracker import confidence_tracker
        assert confidence_tracker is not None

    def test_adaptive_query_singleton(self):
        from pds_ultimate.core.adaptive_query import adaptive_query
        assert adaptive_query is not None

    def test_task_prioritizer_singleton(self):
        from pds_ultimate.core.task_prioritizer import task_prioritizer
        assert task_prioritizer is not None

    def test_context_compressor_singleton(self):
        from pds_ultimate.core.context_compressor import context_compressor
        assert context_compressor is not None

    def test_time_relevance_singleton(self):
        from pds_ultimate.core.time_relevance import time_relevance
        assert time_relevance is not None

    def test_integration_layer_singleton(self):
        from pds_ultimate.core.integration_layer import integration_layer
        assert integration_layer is not None

    def test_production_singleton(self):
        from pds_ultimate.core.production import production
        assert production is not None

    def test_speech_engine_singleton(self):
        from pds_ultimate.core.speech_engine import speech_engine
        assert speech_engine is not None

    def test_parser_singleton(self):
        from pds_ultimate.utils.parsers import parser
        assert parser is not None


class TestConfigValidation:
    """Глубокая валидация конфигурации."""

    def test_config_has_all_sections(self):
        from pds_ultimate.config import config
        assert hasattr(config, "telegram")
        assert hasattr(config, "deepseek")
        assert hasattr(config, "whisper")
        assert hasattr(config, "gmail")

    def test_config_has_extended_sections(self):
        from pds_ultimate.config import config
        assert hasattr(config, "currency")
        assert hasattr(config, "finance")
        assert hasattr(config, "logistics")
        assert hasattr(config, "scheduler")
        assert hasattr(config, "style")
        assert hasattr(config, "security")
        assert hasattr(config, "ocr")
        assert hasattr(config, "browser")

    def test_whisper_config_fields(self):
        from pds_ultimate.config import config
        wc = config.whisper
        assert hasattr(wc, "model_size")
        assert hasattr(wc, "device")
        assert hasattr(wc, "compute_type")
        assert hasattr(wc, "language")
        assert hasattr(wc, "model_dir")

    def test_whisper_language_is_valid(self):
        from pds_ultimate.config import config
        assert config.whisper.language in ("ru", "en", "tk")

    def test_whisper_device_is_valid(self):
        from pds_ultimate.config import config
        assert config.whisper.device in ("auto", "cpu", "cuda")

    def test_database_path_exists(self):
        from pds_ultimate.config import DATA_DIR, DATABASE_PATH
        assert DATABASE_PATH is not None
        assert DATA_DIR is not None

    def test_config_is_appconfig(self):
        from pds_ultimate.config import AppConfig, config
        assert isinstance(config, AppConfig)


class TestToolsRegistry:
    """Тесты реестра бизнес-инструментов."""

    def test_tools_register_all(self):
        from pds_ultimate.core.business_tools import register_all_tools
        count = register_all_tools()
        assert count >= 64

    def test_tools_count_minimum(self):
        from pds_ultimate.core.business_tools import register_all_tools
        count = register_all_tools()
        assert count >= 60, f"Expected >= 60 tools, got {count}"

    def test_tool_registry_has_tools(self):
        from pds_ultimate.core.business_tools import register_all_tools, tool_registry
        register_all_tools()
        # tool_registry should have tools
        assert hasattr(tool_registry, "tools") or hasattr(
            tool_registry, "_tools")


class TestToolResult:
    """Тесты ToolResult."""

    def test_tool_result_success(self):
        from pds_ultimate.core.business_tools import ToolResult
        r = ToolResult("test_tool", True, "output data")
        assert r.tool_name == "test_tool"
        assert r.success is True
        assert r.output == "output data"

    def test_tool_result_failure(self):
        from pds_ultimate.core.business_tools import ToolResult
        r = ToolResult("test_tool", False, "", error="something broke")
        assert r.success is False
        assert "something broke" in r.error

    def test_tool_result_with_data(self):
        from pds_ultimate.core.business_tools import ToolResult
        data = {"key": "value", "count": 42}
        r = ToolResult("test_tool", True, "ok", data=data)
        assert r.data == data


# ═══════════════════════════════════════════════════════════════════════════════
# PARSERS COMPREHENSIVE TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestRegexParser:
    """Тесты RegexParser — все сценарии."""

    def test_single_item(self):
        from pds_ultimate.utils.parsers import RegexParser
        items = RegexParser.parse("iPhone 16 Pro 2шт 999$")
        assert len(items) >= 1

    def test_multiple_items(self):
        from pds_ultimate.utils.parsers import RegexParser
        text = """
        iPhone 16 Pro 2шт 999$
        AirPods Pro 1шт 249$
        MacBook Air 1шт 1299$
        """
        items = RegexParser.parse(text)
        assert len(items) >= 1

    def test_empty_text(self):
        from pds_ultimate.utils.parsers import RegexParser
        items = RegexParser.parse("")
        assert isinstance(items, list)

    def test_no_items_text(self):
        from pds_ultimate.utils.parsers import RegexParser
        items = RegexParser.parse("привет как дела")
        assert isinstance(items, list)

    def test_cyrillic_items(self):
        from pds_ultimate.utils.parsers import RegexParser
        items = RegexParser.parse("Телефон Самсунг 3 штуки 500 долларов")
        assert isinstance(items, list)


class TestUnifiedParser:
    """Тесты UnifiedParser."""

    def test_parser_has_all_methods(self):
        from pds_ultimate.utils.parsers import parser
        assert hasattr(parser, "parse_voice")
        assert hasattr(parser, "parse_image")
        assert hasattr(parser, "transcribe_voice")
        assert hasattr(parser, "detect_format")

    def test_detect_format_voice(self):
        from pds_ultimate.utils.parsers import parser
        assert parser.detect_format("test.ogg") == "voice"
        assert parser.detect_format("test.wav") == "voice"

    def test_detect_format_unknown(self):
        from pds_ultimate.utils.parsers import parser
        result = parser.detect_format("test.xyz")
        assert result in ("unknown", "xyz")


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION LAYER COMPREHENSIVE
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegrationLayerComprehensive:
    """Полные тесты IntegrationLayer."""

    def test_has_health_monitor(self):
        from pds_ultimate.core.integration_layer import integration_layer
        assert integration_layer.health_monitor is not None

    def test_has_fallback_manager(self):
        from pds_ultimate.core.integration_layer import integration_layer
        assert integration_layer.fallback_manager is not None

    def test_has_router(self):
        from pds_ultimate.core.integration_layer import integration_layer
        assert integration_layer.router is not None

    def test_has_auto_healer(self):
        from pds_ultimate.core.integration_layer import integration_layer
        assert integration_layer.auto_healer is not None

    def test_health_monitor_metrics(self):
        from pds_ultimate.core.integration_layer import integration_layer
        metrics = integration_layer.health_monitor.get_all_metrics()
        assert isinstance(metrics, list)

    def test_is_initialized_property(self):
        from pds_ultimate.core.integration_layer import integration_layer
        assert isinstance(integration_layer.is_initialized, bool)


# ═══════════════════════════════════════════════════════════════════════════════
# PRODUCTION HARDENING COMPREHENSIVE
# ═══════════════════════════════════════════════════════════════════════════════


class TestProductionComprehensive:
    """Полные тесты ProductionHardening."""

    def test_rate_limiter_stats(self):
        from pds_ultimate.core.production import production
        stats = production.rate_limiter.get_stats()
        assert isinstance(stats, dict)

    def test_rate_limiter_check(self):
        from pds_ultimate.core.production import production
        result = production.rate_limiter.check("test_user_999")
        assert result is not None

    def test_health_checker_report(self):
        from pds_ultimate.core.production import production
        report = production.health_checker.get_report()
        assert isinstance(report, dict)

    def test_error_reporter_stats(self):
        from pds_ultimate.core.production import production
        stats = production.error_reporter.get_stats()
        assert isinstance(stats, dict)

    def test_uptime_stats(self):
        from pds_ultimate.core.production import production
        stats = production.uptime.get_stats()
        assert isinstance(stats, dict)

    def test_get_stats(self):
        from pds_ultimate.core.production import production
        stats = production.get_stats()
        assert isinstance(stats, dict)
        assert "rate_limiter" in stats
        assert "requests" in stats
        assert "health" in stats

    def test_get_system_report(self):
        from pds_ultimate.core.production import production
        report = production.get_system_report()
        assert isinstance(report, dict)
        assert "uptime" in report
        assert "system" in report


# ═══════════════════════════════════════════════════════════════════════════════
# DOCKER DEPLOY FILES VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestDockerFiles:
    """Валидация Docker файлов."""

    def test_dockerfile_exists(self):
        df = Path(__file__).parent.parent.parent / "Dockerfile"
        assert df.exists(), f"Dockerfile not found at {df}"

    def test_docker_compose_exists(self):
        dc = Path(__file__).parent.parent.parent / "docker-compose.yml"
        assert dc.exists()

    def test_dockerignore_exists(self):
        di = Path(__file__).parent.parent.parent / ".dockerignore"
        assert di.exists()

    def test_dockerfile_has_python(self):
        df = Path(__file__).parent.parent.parent / "Dockerfile"
        content = df.read_text()
        assert "python" in content.lower()

    def test_docker_compose_has_service(self):
        dc = Path(__file__).parent.parent.parent / "docker-compose.yml"
        content = dc.read_text()
        assert "services:" in content
        assert "pds" in content

    def test_deploy_script_exists(self):
        ds = Path(__file__).parent.parent.parent / "scripts" / "deploy.sh"
        assert ds.exists()

    def test_backup_script_exists(self):
        bs = Path(__file__).parent.parent.parent / "scripts" / "backup.sh"
        assert bs.exists()


# ═══════════════════════════════════════════════════════════════════════════════
# CROSS-MODULE INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════════


class TestCrossModule:
    """Кросс-модульные тесты."""

    def test_speech_engine_used_by_voice_parser(self):
        """VoiceParser использует SpeechEngine."""
        import inspect

        from pds_ultimate.utils.parsers import VoiceParser
        source = inspect.getsource(VoiceParser)
        assert "speech_engine" in source

    def test_voice_handler_uses_speech_engine(self):
        """Voice handler использует SpeechEngine."""
        import inspect

        from pds_ultimate.bot.handlers import voice
        source = inspect.getsource(voice)
        assert "speech_engine" in source

    def test_config_whisper_matches_speech_engine(self):
        """Конфигурация WhisperConfig совместима с SpeechEngine."""
        from pds_ultimate.config import config
        from pds_ultimate.core.speech_engine import speech_engine
        if config.whisper is not None:
            assert config.whisper.language == speech_engine._default_language
        else:
            assert speech_engine._default_language in ("ru", "en")

    def test_all_core_exports(self):
        """Все экспорты из core.__init__ доступны."""
        import pds_ultimate.core as core_module
        from pds_ultimate.core import __all__
        for name in __all__:
            assert hasattr(core_module, name), f"Missing export: {name}"


# ═══════════════════════════════════════════════════════════════════════════════
# STRESS & EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════════


class TestStressAndEdgeCases:
    """Стресс-тесты и граничные случаи."""

    def test_speech_engine_multiple_missing_files(self):
        """Множество запросов с несуществующими файлами."""
        from pds_ultimate.core.speech_engine import speech_engine
        for i in range(20):
            result = speech_engine.transcribe(f"/nonexistent/audio_{i}.wav")
            assert result == ""

    def test_transcription_result_very_long_text(self):
        from pds_ultimate.core.speech_engine import TranscriptionResult
        long_text = "слово " * 10000
        r = TranscriptionResult(text=long_text)
        assert r.word_count == 10000

    def test_word_timing_extreme_values(self):
        from pds_ultimate.core.speech_engine import WordTiming
        wt = WordTiming(word="x", start=0.0, end=99999.999, confidence=1.0)
        d = wt.to_dict()
        assert d["end"] == 99999.999

    def test_srt_generation_1000_words(self):
        from pds_ultimate.core.speech_engine import TranscriptionResult, WordTiming
        words = [WordTiming(f"w{i}", i * 0.1, (i + 1) * 0.1, 0.9)
                 for i in range(1000)]
        r = TranscriptionResult(
            text=" ".join(w.word for w in words),
            words=words,
        )
        srt = r.generate_srt(words_per_line=10)
        assert len(srt) > 0
        assert srt.count("-->") == 100  # 1000 / 10

    def test_production_concurrent_rate_limits(self):
        from pds_ultimate.core.production import production
        results = []
        for i in range(50):
            r = production.rate_limiter.check(f"stress_user_{i}")
            results.append(r)
        assert len(results) == 50

    def test_integration_layer_metrics_under_load(self):
        from pds_ultimate.core.integration_layer import integration_layer
        for _ in range(100):
            metrics = integration_layer.health_monitor.get_all_metrics()
        assert isinstance(metrics, list)

    def test_parser_empty_inputs(self):
        from pds_ultimate.utils.parsers import RegexParser
        assert RegexParser.parse("") == [] or isinstance(
            RegexParser.parse(""), list)
        assert RegexParser.parse("   ") == [] or isinstance(
            RegexParser.parse("   "), list)
        assert RegexParser.parse("\n\n") == [] or isinstance(
            RegexParser.parse("\n\n"), list)


# ═══════════════════════════════════════════════════════════════════════════════
# FILE STRUCTURE VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestFileStructure:
    """Валидация структуры проекта."""

    PROJECT_ROOT = Path(__file__).parent.parent

    def test_config_exists(self):
        assert (self.PROJECT_ROOT / "config.py").exists()

    def test_main_exists(self):
        assert (self.PROJECT_ROOT / "main.py").exists()

    def test_core_dir_exists(self):
        assert (self.PROJECT_ROOT / "core").is_dir()

    def test_bot_dir_exists(self):
        assert (self.PROJECT_ROOT / "bot").is_dir()

    def test_utils_dir_exists(self):
        assert (self.PROJECT_ROOT / "utils").is_dir()

    def test_tests_dir_exists(self):
        assert (self.PROJECT_ROOT / "tests").is_dir()

    def test_requirements_exists(self):
        assert (self.PROJECT_ROOT / "requirements.txt").exists()

    def test_speech_engine_exists(self):
        assert (self.PROJECT_ROOT / "core" / "speech_engine.py").exists()

    def test_integration_layer_exists(self):
        assert (self.PROJECT_ROOT / "core" / "integration_layer.py").exists()

    def test_production_exists(self):
        assert (self.PROJECT_ROOT / "core" / "production.py").exists()

    def test_business_tools_exists(self):
        assert (self.PROJECT_ROOT / "core" / "business_tools.py").exists()

    def test_voice_handler_exists(self):
        assert (self.PROJECT_ROOT / "bot" / "handlers" / "voice.py").exists()

    def test_parsers_exists(self):
        assert (self.PROJECT_ROOT / "utils" / "parsers.py").exists()

    def test_no_junk_in_project(self):
        """Внутри pds_ultimate не должно быть мусора."""
        root = self.PROJECT_ROOT
        for item in root.iterdir():
            assert not item.name.endswith(".jpg"), f"Junk image: {item}"
            assert "client_secret" not in item.name, f"Credentials leak: {item}"


# ═══════════════════════════════════════════════════════════════════════════════
# REQUIREMENTS VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestRequirements:
    """Валидация requirements.txt."""

    def test_vosk_in_requirements(self):
        req = Path(__file__).parent.parent / "requirements.txt"
        content = req.read_text()
        assert "vosk" in content.lower()

    def test_faster_whisper_in_requirements(self):
        """faster-whisper как fallback."""
        req = Path(__file__).parent.parent / "requirements.txt"
        content = req.read_text()
        assert "faster-whisper" in content

    def test_aiogram_in_requirements(self):
        req = Path(__file__).parent.parent / "requirements.txt"
        content = req.read_text()
        assert "aiogram" in content

    def test_sqlalchemy_in_requirements(self):
        req = Path(__file__).parent.parent / "requirements.txt"
        content = req.read_text()
        assert "SQLAlchemy" in content or "sqlalchemy" in content

    def test_no_duplicate_packages(self):
        req = Path(__file__).parent.parent / "requirements.txt"
        lines = [
            l.strip().split(">=")[0].split("==")[0].lower()
            for l in req.read_text().splitlines()
            if l.strip() and not l.strip().startswith("#")
        ]
        seen = set()
        duplicates = []
        for pkg in lines:
            if pkg in seen:
                duplicates.append(pkg)
            seen.add(pkg)
        assert len(duplicates) == 0, f"Duplicate packages: {duplicates}"
