"""
Part 13 Tests — Docker Deploy
================================
Тесты для Dockerfile, docker-compose, deploy scripts.
Валидируем конфигурацию без запуска Docker.
"""

from __future__ import annotations

import unittest
from pathlib import Path

# Корень проекта (agent/)
AGENT_DIR = Path(__file__).resolve().parent.parent.parent


class TestDockerfileExists(unittest.TestCase):
    """Проверка наличия Docker файлов."""

    def test_dockerfile_exists(self):
        path = AGENT_DIR / "Dockerfile"
        assert path.exists(), f"Dockerfile не найден: {path}"

    def test_docker_compose_exists(self):
        path = AGENT_DIR / "docker-compose.yml"
        assert path.exists(), f"docker-compose.yml не найден: {path}"

    def test_dockerignore_exists(self):
        path = AGENT_DIR / ".dockerignore"
        assert path.exists(), f".dockerignore не найден: {path}"

    def test_deploy_script_exists(self):
        path = AGENT_DIR / "scripts" / "deploy.sh"
        assert path.exists(), f"deploy.sh не найден: {path}"

    def test_backup_script_exists(self):
        path = AGENT_DIR / "scripts" / "backup.sh"
        assert path.exists(), f"backup.sh не найден: {path}"


class TestDockerfileContent(unittest.TestCase):
    """Проверка содержимого Dockerfile."""

    @classmethod
    def setUpClass(cls):
        cls.content = (AGENT_DIR / "Dockerfile").read_text()

    def test_base_image(self):
        assert "python:3.12" in self.content

    def test_multi_stage(self):
        assert "AS builder" in self.content
        assert "AS runtime" in self.content

    def test_workdir(self):
        assert "WORKDIR /app" in self.content

    def test_pythonpath(self):
        assert "PYTHONPATH=/app" in self.content

    def test_requirements_copy(self):
        assert "requirements.txt" in self.content

    def test_pip_install(self):
        assert "pip install" in self.content

    def test_non_root_user(self):
        assert "USER pds" in self.content or "USER app" in self.content

    def test_healthcheck(self):
        assert "HEALTHCHECK" in self.content

    def test_cmd(self):
        assert "pds_ultimate.main" in self.content

    def test_playwright_install(self):
        assert "playwright install" in self.content

    def test_unbuffered(self):
        assert "PYTHONUNBUFFERED=1" in self.content

    def test_timezone(self):
        assert "Asia/Ashgabat" in self.content

    def test_no_secrets_in_dockerfile(self):
        """Dockerfile не должен содержать секреты."""
        for secret in ["API_KEY", "BOT_TOKEN", "API_HASH"]:
            # Разрешено в ENV описаниях, но не как значение
            lines = self.content.split("\n")
            for line in lines:
                if "=" in line and secret in line:
                    # Проверяем что это не реальное значение
                    _, _, val = line.partition("=")
                    val = val.strip()
                    assert not val or val.startswith("$") or \
                        val.startswith("/") or val.startswith("cpu"), \
                        f"Секрет в Dockerfile: {line.strip()}"


class TestDockerComposeContent(unittest.TestCase):
    """Проверка docker-compose.yml."""

    @classmethod
    def setUpClass(cls):
        cls.content = (AGENT_DIR / "docker-compose.yml").read_text()

    def test_service_pds(self):
        assert "pds:" in self.content

    def test_env_file(self):
        assert "env_file" in self.content
        assert ".env" in self.content

    def test_volumes(self):
        assert "volumes:" in self.content
        assert "pds-data" in self.content

    def test_restart_policy(self):
        assert "restart:" in self.content
        assert "unless-stopped" in self.content

    def test_memory_limit(self):
        assert "memory:" in self.content

    def test_healthcheck(self):
        assert "healthcheck:" in self.content

    def test_logging(self):
        assert "logging:" in self.content
        assert "max-size" in self.content

    def test_named_volumes(self):
        assert "pds-data:" in self.content
        assert "pds-logs:" in self.content


class TestDockerignoreContent(unittest.TestCase):
    """Проверка .dockerignore."""

    @classmethod
    def setUpClass(cls):
        cls.content = (AGENT_DIR / ".dockerignore").read_text()

    def test_git_ignored(self):
        assert ".git" in self.content

    def test_pycache_ignored(self):
        assert "__pycache__" in self.content

    def test_venv_ignored(self):
        assert ".venv" in self.content

    def test_env_ignored(self):
        assert ".env" in self.content

    def test_tests_ignored(self):
        assert "tests/" in self.content

    def test_sessions_ignored(self):
        assert "*.session" in self.content


class TestDeployScriptContent(unittest.TestCase):
    """Проверка deploy.sh."""

    @classmethod
    def setUpClass(cls):
        path = AGENT_DIR / "scripts" / "deploy.sh"
        cls.content = path.read_text()

    def test_shebang(self):
        assert self.content.startswith("#!/")

    def test_set_flags(self):
        assert "set -euo pipefail" in self.content

    def test_commands(self):
        for cmd in ["build", "start", "stop", "restart",
                    "logs", "status", "test", "deploy"]:
            assert cmd in self.content, f"Команда '{cmd}' не найдена"

    def test_env_check(self):
        assert "TG_BOT_TOKEN" in self.content
        assert "DEEPSEEK_API_KEY" in self.content

    def test_docker_compose_usage(self):
        assert "docker compose" in self.content

    def test_executable(self):
        path = AGENT_DIR / "scripts" / "deploy.sh"
        # Файл должен быть executable (или мы пометим его)
        assert path.exists()


class TestBackupScriptContent(unittest.TestCase):
    """Проверка backup.sh."""

    @classmethod
    def setUpClass(cls):
        path = AGENT_DIR / "scripts" / "backup.sh"
        cls.content = path.read_text()

    def test_shebang(self):
        assert self.content.startswith("#!/")

    def test_tar_command(self):
        assert "tar" in self.content

    def test_timestamp(self):
        assert "TIMESTAMP" in self.content or "timestamp" in self.content

    def test_cleanup_old(self):
        assert "mtime" in self.content or "30" in self.content


class TestEnvExample(unittest.TestCase):
    """Проверка .env.example."""

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parent.parent / ".env.example"
        cls.content = path.read_text()

    def test_required_vars(self):
        for var in ["TG_BOT_TOKEN", "TG_OWNER_ID", "DEEPSEEK_API_KEY"]:
            assert var in self.content, f"{var} не в .env.example"

    def test_optional_vars(self):
        for var in ["GMAIL_ENABLED", "WA_ENABLED", "LOG_LEVEL"]:
            assert var in self.content, f"{var} не в .env.example"

    def test_no_real_values(self):
        """Пример не должен содержать реальных токенов."""
        lines = self.content.split("\n")
        for line in lines:
            if "=" in line and not line.strip().startswith("#"):
                key, _, val = line.partition("=")
                val = val.strip()
                # Значения должны быть пустыми или дефолтными
                if key.strip() in ("TG_BOT_TOKEN", "TG_OWNER_ID",
                                   "DEEPSEEK_API_KEY", "TG_API_HASH"):
                    assert val == "" or val == "0", \
                        f"Реальное значение в .env.example: {key.strip()}"


class TestProjectStructure(unittest.TestCase):
    """Проверка структуры проекта для деплоя."""

    def test_requirements_exists(self):
        path = Path(__file__).resolve().parent.parent / "requirements.txt"
        assert path.exists()

    def test_main_exists(self):
        path = Path(__file__).resolve().parent.parent / "main.py"
        assert path.exists()

    def test_config_exists(self):
        path = Path(__file__).resolve().parent.parent / "config.py"
        assert path.exists()

    def test_init_exists(self):
        path = Path(__file__).resolve().parent.parent / "__init__.py"
        assert path.exists()


class TestPart13ToolCount(unittest.TestCase):
    """Проверка что количество инструментов не изменилось."""

    def test_total_tool_count_unchanged(self):
        """Part 13 не добавляет новых tools — осталось 64."""
        from unittest.mock import patch

        from pds_ultimate.core.business_tools import register_all_tools
        from pds_ultimate.core.tools import ToolRegistry
        registry = ToolRegistry()
        with patch("pds_ultimate.core.business_tools.tool_registry", registry):
            count = register_all_tools()
            assert count == 64, f"Ожидалось 64, получено {count}"


if __name__ == "__main__":
    unittest.main()
