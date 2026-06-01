"""
PDS-Ultimate Tests — conftest
================================
Фикстуры pytest для всех тестов.
"""

import os
import sys
from pathlib import Path

import pytest

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Устанавливаем тестовые переменные окружения ДО импорта config
os.environ.setdefault("TG_BOT_TOKEN", "test:BOT_TOKEN_123456")
os.environ.setdefault("TG_OWNER_ID", "999999999")
os.environ.setdefault("DEEPSEEK_API_KEY", "test_deepseek_key")
os.environ.setdefault("TG_API_ID", "12345")
os.environ.setdefault("TG_API_HASH", "test_api_hash")
os.environ.setdefault("GMAIL_ENABLED", "false")
os.environ.setdefault("WA_ENABLED", "false")
os.environ.setdefault("LOG_LEVEL", "DEBUG")
os.environ.setdefault("FINANCE_EXPENSE_PERCENT", "50.0")
os.environ.setdefault("FINANCE_SAVINGS_PERCENT", "50.0")


@pytest.fixture(scope="session")
def test_config():
    """Тестовая конфигурация."""
    from pds_ultimate.config import AppConfig
    return AppConfig.load()


@pytest.fixture
def db_session():
    """In-memory SQLite сессия для тестов."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from pds_ultimate.core.database import Base

    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    yield session

    session.close()
    engine.dispose()


@pytest.fixture
def session_factory():
    """Фабрика сессий для тестов (in-memory)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from pds_ultimate.core.database import Base

    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    yield factory

    engine.dispose()
