"""
Автоматическая регистрация агентов из папки `agents`.
"""

import importlib
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Type, List

# # --- добавляем корень проекта в PYTHONPATH ---
# BASE_DIR = Path(__file__).resolve().parents[3]
# print(BASE_DIR)
#
# sys.path.insert(0, str(BASE_DIR))
#
# os.environ.setdefault(
#     "DJANGO_SETTINGS_MODULE",
#     "engageai_core.settings"
# )
#
# import django
#
# django.setup()

from ai.orchestrator_v1.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class AgentRegistry:
    """
    Реестр агентов с автоматической загрузкой из папки.

    Как это работает:
    1. При инициализации сканирует папку `curriculum/chat/agents/`
    2. Импортирует все модули, содержащие классы-наследники BaseAgent
    3. Регистрирует агенты по их уникальному имени
    4. Предоставляет методы для получения списка агентов и их описаний

    Пример использования:
    >> registry = AgentRegistry()
    >> agents = registry.get_all_agents()
    >> print(agents)
    {
        "ContentAgent": <ContentAgent object>,
        "WritingAgent": <WritingAgent object>,
        ...
    }
    """

    _instance = None
    _agents: Dict[str, Type[BaseAgent]] = {}
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AgentRegistry, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._agents = {}
            self._scan_and_register_agents()
            self._initialized = True
            logger.info(f"Зарегистрировано {len(self._agents)} агентов")

    def _scan_and_register_agents(self):
        """
        Сканирование папки с агентами и автоматическая регистрация.

        Алгоритм:
        1. Находит все .py файлы в папке `curriculum/chat/agents/`
        2. Исключает базовые файлы: __init__.py, base.py, registry.py
        3. Импортирует каждый модуль
        4. Находит все классы-наследники BaseAgent
        5. Регистрирует агенты по их имени (поле `name`)

        Важно:
        - Агент должен быть определён в отдельном файле
        - Агент должен наследоваться от BaseAgent
        - Агент должен иметь уникальное имя
        """
        # Путь к папке с агентами
        agents_dir = Path(__file__).parent

        # Сканируем все .py файлы
        for file_path in agents_dir.glob("*.py"):
            # Исключаем системные файлы
            if file_path.name in ["__init__.py", "base.py", "registry.py"]:
                continue

            # Импортируем модуль
            module_name = f"{__package__}.{file_path.stem}"
            try:
                module = importlib.import_module(module_name)

                # Находим все классы-наследники BaseAgent в модуле
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)

                    # Проверяем, что это класс и наследник BaseAgent
                    if (
                            isinstance(attr, type) and
                            issubclass(attr, BaseAgent) and
                            attr != BaseAgent
                    ):
                        # Создаём экземпляр для получения имени
                        agent_instance = attr()

                        # Регистрируем агента
                        self._register_agent(agent_instance.name, attr)

                        logger.debug(
                            f"Зарегистрирован агент: {agent_instance.name} "
                            f"({agent_instance.description})"
                        )

            except Exception as e:
                logger.error(f"Ошибка при загрузке агента из {module_name}: {e}")

    def _register_agent(self, name: str, agent_class: Type[BaseAgent]):
        """Регистрация агента в реестре"""
        if name in self._agents:
            logger.warning(f"Агент с именем '{name}' уже зарегистрирован. Пропускаем.")
            return

        self._agents[name] = agent_class

    def get_all_agents(self) -> Dict[str, Type[BaseAgent]]:
        """Получение всех зарегистрированных агентов"""
        return self._agents.copy()

    def get_agent_class(self, name: str) -> Type[BaseAgent]:
        """Получение класса агента по имени"""
        if name not in self._agents:
            raise ValueError(f"Агент '{name}' не найден в реестре")
        return self._agents[name]

    def get_agent_names(self) -> List[str]:
        """Получение списка имён всех агентов"""
        return list(self._agents.keys())

    def get_agents_descriptions(self) -> Dict[str, str]:
        """
        Получение описаний всех агентов в формате:
        {
            "ContentAgent": "Объяснение грамматики и лексики",
            "WritingAgent": "Проверка письменной речи",
            ...
        }
        """
        descriptions = {}
        for name, agent_class in self._agents.items():
            instance = agent_class()
            descriptions[name] = instance.description
        return descriptions

    def get_agents_with_metadata(self) -> List[Dict]:
        """
        Получение полной информации обо всех агентах.

        Возвращает:
        [
            {
                "name": "ContentAgent",
                "description": "Объяснение грамматики и лексики",
                "supported_intents": ["EXPLAIN_GRAMMAR", "ANALYZE_ERROR"],
                "capabilities": ["grammar_explanation", "vocabulary_teaching"]
            },
            ...
        ]
        """
        metadata = []
        for name, agent_class in self._agents.items():
            instance = agent_class()
            metadata.append({
                "name": instance.name,
                "description": instance.description,
                "supported_intents": instance.supported_intents,
                "capabilities": instance.capabilities if hasattr(instance, 'capabilities') else [],
                "fallback_agent": instance.fallback_agent if hasattr(instance, 'fallback_agent') else False
            })
        return metadata

    def reload_agents(self):
        """Перезагрузка агентов (для горячего обновления)"""
        self._agents = {}
        self._scan_and_register_agents()
        self._initialized = True
        logger.info(f"Перезагружено {len(self._agents)} агентов")


# Глобальный экземпляр реестра
agent_registry = AgentRegistry()
