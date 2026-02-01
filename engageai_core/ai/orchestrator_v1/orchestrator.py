# curriculum/chat/orchestrator.py
"""
UniversalOrchestrator: Центральный оркестратор чата с композицией агентов.

Соответствует ТЗ:
- Задача 1.1: Центральный Умный Чат-Помощник, ведущий студента за руку через интеллектуальную оркестрацию
- Задача 2.1: Единая модель данных (интеграция с сервисами контекста)
- Задача 2.3: Аналитика выбора агентов и эффективности ответов
- Задача 5.1: Оптимизация стоимости через кэширование и минимизацию вызовов

Ключевые принципы архитектуры:
1. АВТОМАТИЧЕСКАЯ РЕГИСТРАЦИЯ АГЕНТОВ
   - Все агенты в папке `agents/` автоматически регистрируются через `AgentRegistry`
   - НЕТ ручного перечисления в Enum — новые агенты добавляются созданием файла

2. ВЫБОР АГЕНТОВ ЧЕРЕЗ LLM
   - LLM анализирует полный контекст и выбирает оптимальный набор агентов
   - НЕТ жёстких правил — система адаптируется под новые сценарии
   - Кэширование частых комбинаций для оптимизации стоимости

3. РАВНОПРАВИЕ АГЕНТОВ
   - НЕТ разделения на "основной/вспомогательный"
   - Каждый агент решает узкую задачу:
     * ContentAgent → объяснение грамматики
     * SupportAgent → эмоциональная поддержка
     * ProfessionalAgent → профессиональный контекст
     * ...и другие

4. АГРЕГАЦИЯ ЧЕРЕЗ TOP MANAGER
   - При вызове нескольких агентов — ответы собираются через отдельный агент (TopManager)
   - НЕТ шаблонной конкатенации — естественный, связный текст через LLM
   - TopManager получает все компоненты и формирует финальный ответ

5. КОНТЕКСТНАЯ ИЗОЛЯЦИЯ
   - Каждый агент получает ТОЛЬКО нужные ему данные через `AgentContextService.build_context_for_agent()`
   - Базовый агент НЕ содержит бизнес-логики (адаптация через промпт, не постобработку)
"""
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime

from ai.orchestrator_v1.services.lesson_context_service import LessonContextService
from utils.setup_logger import setup_logger

# --- добавляем корень проекта в PYTHONPATH ---
BASE_DIR = Path(__file__).resolve().parents[2]
print(BASE_DIR)

sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "engageai_core.settings"
)

import django

django.setup()

from ai.orchestrator_v1.agents.agents_registry import agent_registry
from ai.orchestrator_v1.agents.base import AgentResponse
from ai.orchestrator_v1.context.agent_context import AgentContext
from ai.orchestrator_v1.services.agent_selection_service import AgentSelectionLLM
from llm_logger.models import LogLLMRequest, LLMRequestType
from ai.orchestrator_v1.services.user_context_service import UserContextService
from ai.orchestrator_v1.top_manager import TopManagerAgent


class UniversalOrchestrator:
    """
    Универсальный оркестратор чата с композицией агентов.

    Архитектурные особенности:
    - Единая точка входа для всех чат-запросов
    - Интеграция с сервисами контекста (пользователь, урок)
    - Выбор агентов через LLM с кэшированием
    - Параллельный вызов агентов
    - Агрегация ответов через специализированный агент (TopManager)

    Пример использования:
    >> orchestrator = UniversalOrchestrator()
    >> response = await orchestrator.route_message(
    ..     user_message="Почему здесь Past Perfect?",
    ..     user_id=42,
    ..     lesson_id=156
    .. )
    >> print(response)
    "Past Perfect здесь потому, что одно действие завершилось РАНЬШЕ другого в прошлом..."
    """

    def __init__(self, use_cache: bool = False, cache_ttl: int = 300):
        """
        Инициализация оркестратора.

        Аргументы:
            use_cache: bool — использовать кэширование выбора агентов (оптимизация стоимости)
            cache_ttl: int — время жизни кэша в секундах (по умолчанию 5 минут)
        """
        self.agent_registry = agent_registry
        self.agent_selector = AgentSelectionLLM()
        self.use_cache = use_cache
        self.cache_ttl = cache_ttl
        self.logger = setup_logger(name=__file__, log_dir="logs/universal_orchestrator", log_file="orchestrator.log")

        # Предзагрузка агентов
        self._agents_cache: Dict[str, Any] = {}
        self._preload_agents()

        self.logger.info(
            f"Orchestrator инициализирован: "
            f"агентов={len(self.agent_registry.get_agent_names())}, "
            f"кэш={'включён' if use_cache else 'отключён'}"
        )

    def _preload_agents(self):
        """Предзагрузка агентов для ускорения первого вызова"""
        for agent_name in self.agent_registry.get_agent_names():
            try:
                agent_class = self.agent_registry.get_agent_class(agent_name)
                self._agents_cache[agent_name] = agent_class()
            except Exception as e:
                self.logger.error(f"Ошибка предзагрузки агента {agent_name}: {e}")

    async def route_message(
            self,
            user_message: str,
            user_id: int,
            message_context: Optional[Dict] = None,
    ) -> str:
        """
        Полный цикл обработки сообщения студента.

        Этапы:
        1. Формирование контекста через сервисы (пользователь + урок)
        2. Выбор оптимального набора агентов через LLM
        3. Параллельный вызов всех выбранных агентов
        4. Агрегация ответов через TopManager (если агентов > 1)

        Аргументы:
            user_message: str — сообщение студента
            user_id: int — ID пользователя
            page_context: Optional[Dict] — контекст с дополнительными параметрам в рамках
            которого было отправлено сообщение

        Возвращает:
            str — финальный ответ для студента

        Исключения:
            Любая ошибка обрабатывается через фолбэк, учебный процесс НЕ прерывается
        """
        start_time = datetime.now()
        request_id = f"orch_{user_id}_{int(start_time.timestamp())}"

        if message_context:
            _message_context = {
                key: value
                for key, value in {
                    "page": message_context.get("page"),
                    "enrollment_id": message_context.get("enrollment_id"),
                    "course_id": message_context.get("course_id"),
                    "lesson_id": message_context.get("lesson_id"),
                    "task_id": message_context.get("task_id"),
                }.items()
                if value is not None
            }
        else:
            _message_context = {}

        self.logger.info(f"{request_id} Новый входящий запрос к UniversalOrchestrator: "
                         f"{user_id=}, {user_message=}, {_message_context=}")
        try:
            # === ЭТАП 1: Формирование контекста ===
            context = await self._build_context(
                request_id=request_id,
                user_message=user_message,
                user_id=user_id,
                message_context=_message_context,
            )

            # === ЭТАП 2: Выбор агентов через LLM ===
            selection = await self.agent_selector.select_agents(
                context=context,
                force_use_llm=False  # Использовать кэш при наличии
            )
            print(f"{selection=}")

            # === ЭТАП 3: Параллельный вызов агентов ===
            agent_responses = await self._call_agents_parallel(
                agent_names=selection["agent_names"],
                base_context=context,
                request_id=request_id
            )
            print(f"{agent_responses=}")

            # === ЭТАП 4: Агрегация ответов ===
            final_response = await self._aggregate_responses(
                agent_responses=agent_responses,
                context=context,
            )

            # === ЭТАП 5: Логирование для аналитики ===
            await self._log_orchestration_event(
                request_id=request_id,
                user_id=user_id,
                user_message=user_message,
                selection=selection,
                agent_responses=agent_responses,
                final_response=final_response,
                processing_time_ms=int((datetime.now() - start_time).total_seconds() * 1000)
            )

            self.logger.info(
                f"Запрос обработан: user={user_id}, "
                f"агенты={selection['agent_names']}, "
                f"время={int((datetime.now() - start_time).total_seconds() * 1000)}мс"
            )

            return final_response

        except Exception as e:
            self.logger.error(
                f"Критическая ошибка в оркестраторе: {e}",
                exc_info=True,
                extra={"user_id": user_id, "request_id": request_id}
            )

            # Фолбэк-ответ без прерывания учебного процесса
            fallback_response = (
                "Извините, произошла временная техническая сложность. "
                "Ваш запрос очень важен для нас — пожалуйста, повторите его через несколько секунд."
            )

            # Логирование ошибки
            await self._log_orchestration_error(
                request_id=request_id,
                user_id=user_id,
                error=str(e),
                user_message=user_message
            )

            return fallback_response

    async def _build_context(
            self,
            request_id: str,
            user_message: str,
            user_id: int,
            message_context: Dict,
    ) -> AgentContext:
        """
        Формирование полного контекста для агентов.

        Интеграция с сервисами:
        - UserContextService — профиль, прогресс, геймификация
        - LessonContextService — состояние урока, ремедиация

        Возвращает:
            AgentContext с полным контекстом для агентов
        """

        user_context = await UserContextService.get_context(user_id=user_id, user_message=user_message)

        page = message_context.get("page")
        enrollment_id = message_context.get("enrollment_id")
        course_id = message_context.get("course_id")
        lesson_id = message_context.get("lesson_id")
        task_id = message_context.get("task_id")

        lesson_context = {}
        if lesson_id:
            lesson_context = await LessonContextService.get_context(
                lesson_id=lesson_id, user_id=user_id, user_message=user_message
            )

        context = AgentContext(
            user_message=user_message,
            user_context=user_context,
            lesson_context=lesson_context,
        )

        self.logger.debug(
            f"Контекст сформирован: user={user_id}, "
            # f"lesson_state={context.get_lesson_state()}"
        )

        return context

    async def _call_agents_parallel(
            self,
            agent_names: List[str],
            base_context: AgentContext,
            request_id: str
    ) -> List[dict]:
        """
        Параллельный вызов всех выбранных агентов.

        Особенности:
        - Каждый агент получает специализированный контекст через `build_context_for_agent()`
        - Обработка ошибок каждого агента изолирована (ошибка одного не ломает всех)
        - Таймаут 30 секунд на все вызовы
        """
        # Формирование задач для параллельного выполнения
        tasks = []

        for agent_name in agent_names:
            # Получение экземпляра агента
            if agent_name in self._agents_cache:
                agent = self._agents_cache[agent_name]
            else:
                try:
                    agent_class = self.agent_registry.get_agent_class(agent_name)
                    agent = agent_class()
                    self._agents_cache[agent_name] = agent
                except Exception as e:
                    self.logger.error(f"Ошибка создания агента {agent_name}: {e}")
                    continue

            # Добавление задачи
            tasks.append(
                asyncio.wait_for(
                    agent.handle(base_context),
                    timeout=25.0  # Таймаут на один агент
                )
            )

        # Параллельное выполнение с обработкой ошибок
        if not tasks:
            self.logger.warning("Нет агентов для вызова — возвращаем фолбэк")
            return [AgentResponse(text="Я не могу ответить на этот вопрос. Давайте обсудим что-то другое?")]

        # Выполнение всех задач параллельно
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Фильтрация успешных результатов
        valid_responses = []
        for i, result in enumerate(results):
            agent_name = agent_names[i]

            if isinstance(result, Exception):
                self.logger.error(
                    f"Ошибка агента {agent_name}: {result}",
                    exc_info=True,
                    extra={"request_id": request_id}
                )
                # Фолбэк для сломанного агента
                # valid_responses.append(AgentResponse(text=""))
            elif isinstance(result, AgentResponse):
                agent = self._agents_cache[agent_name]

                valid_responses.append({
                    "agent_name": agent.__class__.__name__,
                    "agent_role": agent.description,
                    "agent_response": result
                })
            else:
                self.logger.warning(f"Невалидный ответ от агента {agent_name}: {type(result)}")
                # valid_responses.append(AgentResponse(text=""))

        self.logger.debug(f"Вызвано агентов: {len(agent_names)}, успешных: {len(valid_responses)}")

        return valid_responses

    async def _aggregate_responses(
            self,
            agent_responses: List[Dict],
            context: AgentContext,
    ) -> str:
        """
        Агрегация ответов через TopManager.

        Логика:
        - 1 агент → возвращаем его ответ напрямую (без агрегации)
        - 2+ агентов → вызываем TopManager для сборки связного текста

        Почему НЕ конкатенация:
        ❌ "Объяснение: ... [разрыв] Микро-успех: ... [разрыв] Пример: ..."
        ✅ "Объяснение с плавно вплетённым микро-успехом и примером"
        """
        try:
            # Получение TopManager
            top_manager = TopManagerAgent()

            # # Формирование контекста для агрегации
            # aggregation_context = await top_manager.agg(
            #     base_context=context,
            #     extra_={
            #         "agent_responses": [
            #             {
            #                 "agent": resp.metadata.get("agent", f"agent_{i}"),
            #                 "text": resp.text,
            #                 "metadata": resp.metadata
            #             }
            #             for i, resp in enumerate(agent_responses)
            #         ],
            #         "selection_reasoning": selection.get("reasoning", ""),
            #         "selection_confidence": selection.get("confidence", 0.5)
            #     }
            # )

            # Вызов агрегатора
            aggregation_result = await asyncio.wait_for(
                top_manager.handle(agents_responses=agent_responses, context=context),
                timeout=30.0
            )

            print(aggregation_result)

            self.logger.debug(f"Агрегация завершена: {aggregation_result}")

            return aggregation_result

        except Exception as e:
            self.logger.error(f"Ошибка агрегации через TopManager: {e}", exc_info=True)

            # Фолбэк: умная конкатенация (не идеально, но лучше пустого ответа)
            parts = []
            for resp in agent_responses:
                text = resp.text.strip()
                if text and len(text) > 5:
                    parts.append(text)

            if parts:
                return " ".join(parts[:3])  # Берём первые 3 части
            else:
                return "Спасибо за ваш вопрос. Я работаю над тем, чтобы дать вам лучший ответ."

    async def _log_orchestration_event(
            self,
            request_id: str,
            user_id: int,
            user_message: str,
            selection: Dict[str, Any],
            agent_responses: List[dict],
            final_response: str,
            processing_time_ms: int
    ):
        """
        Логирование события оркестрации для административного дашборда (Задача 2.3 ТЗ).

        Сохраняет:
        - Выбранных агентов и обоснование выбора
        - Время обработки
        - Длину ответов
        - Уверенность LLM в выборе
        """
        try:
            await LogLLMRequest.objects.acreate(
                request_type=LLMRequestType.CHAT,
                model_name="orchestrator_v2",
                prompt=user_message,
                response=final_response,
                tokens_in=0,  # Оркестратор не тратит токены напрямую
                tokens_out=0,
                cost_in=0,
                cost_out=0,
                cost_total=0,
                duration_sec=processing_time_ms / 1000.0,
                error_message="",
                metadata={
                    "request_id": request_id,
                    "selected_agents": selection["agent_names"],
                    "selection_reasoning": selection.get("reasoning", ""),
                    "selection_confidence": selection.get("confidence", 0.5),
                    "selection_method": selection.get("selection_method", "unknown"),
                    "agent_count": len(agent_responses),
                    # "agent_responses": agent_responses, # TODO надо сериализовать ответы агентов
                    "processing_time_ms": processing_time_ms
                },
                user_id=user_id,
                status="SUCCESS"
            )
        except Exception as e:
            self.logger.warning(f"Не удалось записать лог оркестрации: {e}")

    async def _log_orchestration_error(
            self,
            request_id: str,
            user_id: int,
            error: str,
            user_message: str
    ):
        """Логирование критической ошибки оркестратора"""
        try:
            await LogLLMRequest.objects.acreate(
                request_type=LLMRequestType.CHAT,
                model_name="orchestrator_v2",
                prompt=user_message[:500],
                response="",
                tokens_in=0,
                tokens_out=0,
                cost_in=0,
                cost_out=0,
                cost_total=0,
                duration_sec=0,
                error_message=error[:500],
                metadata={
                    "request_id": request_id,
                    "error_type": "orchestrator_critical"
                },
                user_id=user_id,
                status="ERROR"
            )
        except Exception as e:
            self.logger.error(f"Не удалось записать лог ошибки: {e}")


if __name__ == "__main__":
    o = UniversalOrchestrator()
    resp = asyncio.run(o.route_message(user_message="Не понял я это ваш Past Perfect", user_id=2))
    print(resp.response.response.message)

