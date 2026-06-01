"""
PDS-Ultimate Dependency Injection Container
=============================================
Централизованный контейнер зависимостей с lazy initialization.

Заменяет монолитный main.py:
- Каждый сервис создаётся один раз (singleton)
- Lazy initialization — только при первом обращении
- Чёткие зависимости между модулями
- Простое тестирование через override

Использование:
    container = Container()
    await container.start()
    agent = container.agent
    llm = container.llm_engine
    await container.stop()

Тестирование:
    container = Container()
    container.override("llm_engine", mock_llm)
    agent = container.agent  # получит mock_llm
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable

logger = logging.getLogger("pds_ultimate")


# ─── Service Lifecycle ───────────────────────────────────────────────────────


class ServiceState(Enum):
    """Состояние сервиса."""
    NOT_CREATED = auto()
    CREATED = auto()
    STARTED = auto()
    STOPPED = auto()
    FAILED = auto()


@dataclass
class ServiceEntry:
    """Запись о сервисе в контейнере."""
    name: str
    factory: Callable[..., Any]
    deps: list[str] = field(default_factory=list)
    instance: Any = None
    state: ServiceState = ServiceState.NOT_CREATED
    start_method: str | None = None  # async method to call on start
    stop_method: str | None = None   # async method to call on stop
    error: str | None = None
    init_time_ms: float = 0.0
    required: bool = True  # если False — предупреждение вместо ошибки

    @property
    def is_ready(self) -> bool:
        return self.state in (ServiceState.CREATED, ServiceState.STARTED)


# ─── Container ───────────────────────────────────────────────────────────────


class Container:
    """
    DI Container с lazy initialization и lifecycle management.

    Features:
    - Lazy singleton: сервис создаётся при первом обращении
    - Dependency resolution: сервис получает свои зависимости автоматически
    - Lifecycle: start() / stop() для async сервисов
    - Override: замена сервиса для тестов
    - Health check: статус каждого сервиса
    - Topological sort: правильный порядок инициализации
    """

    def __init__(self):
        self._registry: dict[str, ServiceEntry] = {}
        self._overrides: dict[str, Any] = {}
        self._started = False
        self._start_time: float = 0.0

    # ─── Registration ────────────────────────────────────────────────────

    def register(
        self,
        name: str,
        factory: Callable[..., Any],
        deps: list[str] | None = None,
        start_method: str | None = None,
        stop_method: str | None = None,
        required: bool = True,
    ) -> None:
        """
        Зарегистрировать сервис.

        Args:
            name: уникальное имя сервиса
            factory: callable, возвращающий экземпляр (может принимать deps как kwargs)
            deps: список имён зависимостей (передаются как kwargs в factory)
            start_method: имя async метода для запуска (e.g. "start")
            stop_method: имя async метода для остановки (e.g. "stop")
            required: если True, ошибка при инициализации — критична
        """
        if name in self._registry:
            logger.warning(f"Container: overwriting service '{name}'")

        self._registry[name] = ServiceEntry(
            name=name,
            factory=factory,
            deps=deps or [],
            start_method=start_method,
            stop_method=stop_method,
            required=required,
        )

    def register_instance(self, name: str, instance: Any) -> None:
        """Зарегистрировать готовый экземпляр (уже создан)."""
        self._registry[name] = ServiceEntry(
            name=name,
            factory=lambda: instance,
            instance=instance,
            state=ServiceState.CREATED,
        )

    def override(self, name: str, instance: Any) -> None:
        """
        Подменить сервис (для тестов).
        Override имеет приоритет над factory.
        """
        self._overrides[name] = instance

    def reset_overrides(self) -> None:
        """Сбросить все override."""
        self._overrides.clear()

    # ─── Resolution ──────────────────────────────────────────────────────

    def resolve(self, name: str) -> Any:
        """
        Получить экземпляр сервиса (lazy init).

        Raises:
            KeyError: если сервис не зарегистрирован
            RuntimeError: если не удалось создать сервис
        """
        # Check override first
        if name in self._overrides:
            return self._overrides[name]

        entry = self._registry.get(name)
        if not entry:
            raise KeyError(f"Service '{name}' not registered in container")

        # Already created
        if entry.instance is not None and entry.is_ready:
            return entry.instance

        # Resolve dependencies first
        resolved_deps = {}
        for dep_name in entry.deps:
            try:
                resolved_deps[dep_name] = self.resolve(dep_name)
            except (KeyError, RuntimeError) as e:
                if entry.required:
                    raise RuntimeError(
                        f"Failed to resolve dependency '{dep_name}' "
                        f"for service '{name}': {e}"
                    )
                logger.warning(
                    f"Optional dependency '{dep_name}' for '{name}' "
                    f"unavailable: {e}"
                )

        # Create instance
        start = time.time()
        try:
            if resolved_deps:
                entry.instance = entry.factory(**resolved_deps)
            else:
                entry.instance = entry.factory()
            entry.state = ServiceState.CREATED
            entry.init_time_ms = (time.time() - start) * 1000
        except Exception as e:
            entry.state = ServiceState.FAILED
            entry.error = str(e)
            if entry.required:
                raise RuntimeError(
                    f"Failed to create service '{name}': {e}")
            logger.warning(f"Optional service '{name}' failed: {e}")
            return None

        return entry.instance

    def __getattr__(self, name: str) -> Any:
        """Allow container.service_name syntax."""
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self.resolve(name)
        except KeyError:
            raise AttributeError(
                f"Service '{name}' not registered in container")

    def has(self, name: str) -> bool:
        """Проверить, зарегистрирован ли сервис."""
        return name in self._registry or name in self._overrides

    # ─── Lifecycle ───────────────────────────────────────────────────────

    async def start(self) -> list[str]:
        """
        Запустить все сервисы в правильном порядке.

        Returns:
            list of warnings (non-critical errors)
        """
        self._start_time = time.time()
        warnings: list[str] = []

        # Topological sort for correct init order
        order = self._topological_sort()

        for name in order:
            entry = self._registry[name]

            # Skip if override exists
            if name in self._overrides:
                entry.state = ServiceState.STARTED
                continue

            # Resolve (create) if not yet
            try:
                instance = self.resolve(name)
                if instance is None:
                    continue
            except RuntimeError as e:
                if entry.required:
                    raise
                warnings.append(f"{name}: {e}")
                continue

            # Call start method if defined
            if entry.start_method and hasattr(instance, entry.start_method):
                try:
                    start_fn = getattr(instance, entry.start_method)
                    await start_fn()
                    entry.state = ServiceState.STARTED
                    logger.info(f"  ✅ {name} started")
                except Exception as e:
                    entry.state = ServiceState.FAILED
                    entry.error = str(e)
                    if entry.required:
                        raise RuntimeError(
                            f"Failed to start service '{name}': {e}")
                    warnings.append(f"{name}: {e}")
                    logger.warning(f"  ⚠ {name}: {e}")
            else:
                entry.state = ServiceState.STARTED

        self._started = True
        elapsed = (time.time() - self._start_time) * 1000
        logger.info(
            f"Container started: {len(order)} services in {elapsed:.0f}ms")

        return warnings

    async def stop(self) -> None:
        """Остановить все сервисы в обратном порядке."""
        order = self._topological_sort()

        for name in reversed(order):
            entry = self._registry[name]
            if entry.instance is None:
                continue

            if entry.stop_method and hasattr(entry.instance, entry.stop_method):
                try:
                    stop_fn = getattr(entry.instance, entry.stop_method)
                    await stop_fn()
                    entry.state = ServiceState.STOPPED
                except Exception as e:
                    logger.warning(f"Error stopping {name}: {e}")
            else:
                entry.state = ServiceState.STOPPED

        self._started = False
        logger.info("Container stopped")

    # ─── Topological Sort ────────────────────────────────────────────────

    def _topological_sort(self) -> list[str]:
        """
        Topological sort сервисов по зависимостям (Kahn's algorithm).
        Гарантирует, что зависимости инициализируются первыми.
        """
        # Build in-degree map
        in_degree: dict[str, int] = {name: 0 for name in self._registry}
        adjacency: dict[str, list[str]] = {
            name: [] for name in self._registry
        }

        for name, entry in self._registry.items():
            for dep in entry.deps:
                if dep in self._registry:
                    adjacency[dep].append(name)
                    in_degree[name] += 1

        # BFS
        queue = [name for name, deg in in_degree.items() if deg == 0]
        result: list[str] = []

        while queue:
            node = queue.pop(0)
            result.append(node)
            for neighbor in adjacency[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Check for cycles
        if len(result) != len(self._registry):
            missing = set(self._registry) - set(result)
            logger.error(
                f"Circular dependency detected: {missing}")
            # Add remaining anyway (best effort)
            result.extend(missing)

        return result

    # ─── Health & Stats ──────────────────────────────────────────────────

    def get_health(self) -> dict[str, Any]:
        """Получить состояние всех сервисов."""
        services = {}
        for name, entry in self._registry.items():
            services[name] = {
                "state": entry.state.name,
                "init_time_ms": round(entry.init_time_ms, 1),
                "error": entry.error,
                "required": entry.required,
                "deps": entry.deps,
            }

        healthy = sum(
            1 for e in self._registry.values() if e.is_ready)
        total = len(self._registry)
        failed = sum(
            1 for e in self._registry.values()
            if e.state == ServiceState.FAILED
        )

        return {
            "overall": "healthy" if failed == 0 else "degraded",
            "services_total": total,
            "services_healthy": healthy,
            "services_failed": failed,
            "started": self._started,
            "uptime_ms": (
                (time.time() - self._start_time) * 1000
                if self._start_time else 0
            ),
            "services": services,
        }

    def get_stats(self) -> dict[str, Any]:
        """Краткая статистика."""
        return {
            "total": len(self._registry),
            "created": sum(
                1 for e in self._registry.values()
                if e.state != ServiceState.NOT_CREATED
            ),
            "started": sum(
                1 for e in self._registry.values()
                if e.state == ServiceState.STARTED
            ),
            "failed": sum(
                1 for e in self._registry.values()
                if e.state == ServiceState.FAILED
            ),
            "overrides": len(self._overrides),
        }

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"Container(services={stats['total']}, "
            f"started={stats['started']}, "
            f"failed={stats['failed']})"
        )


# ─── Global Instance ─────────────────────────────────────────────────────────

container = Container()
