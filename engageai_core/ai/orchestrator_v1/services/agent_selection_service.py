import json
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime

from django.core.cache import cache # TODO разбираться с кешем

from ai.llm_service.factory import llm_factory
from ai.orchestrator_v1.agents.agents_registry import agent_registry
from ai.orchestrator_v1.context.agent_context import AgentContext

logger = logging.getLogger(__name__)


class AgentSelectionLLM:
    """
    Сервис выбора агентов через LLM.

    Преимущества перед правилами:
    1. Гибкость — легко адаптируется под новые агенты
    2. Контекстуальность — учитывает полный контекст запроса
    3. Оптимизация — выбирает минимально необходимый набор агентов
    4. Масштабируемость — не требует ручного обновления правил

    Недостатки:
    1. Стоимость — каждый вызов требует токенов LLM
    2. Скорость — медленнее правил (но кэшируется)

    Стратегия:
    - Использовать кэширование для частых комбинаций
    - Для простых случаев можно использовать правила как фолбэк
    """

    def __init__(self):
        self.llm = llm_factory
        self.cache_ttl = 300  # 5 минут

    async def select_agents(
            self,
            context: AgentContext,
            force_use_llm: bool = False
    ) -> Dict:
        """
        Выбор списка агентов через LLM.

        Алгоритм:
        1. Проверка кэша по хэшу контекста
        2. Формирование промпта со всеми агентами из реестра
        3. Вызов LLM для выбора оптимального набора
        4. Валидация результата
        5. Кэширование

        Возвращает:
        {
            "agent_names": ["ContentAgent", "SupportAgent"],
            "reasoning": "Выбраны агенты для объяснения грамматики с поддержкой...",
            "confidence": 0.92,
            "selection_method": "llm"
        }
        """
        # Шаг 1: Проверка кэша
        # cache_key = self._build_cache_key(context)
        # cached_result = self._get_from_cache(cache_key)
        #
        # if cached_result and not force_use_llm:
        #     logger.debug(f"Выбор агентов из кэша: {cached_result['agent_names']}")
        #     return cached_result

        # Шаг 2: Формирование промпта
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(context)
        print(system_prompt)
        print(user_prompt)

        # Шаг 3: Вызов LLM
        try:
            result = await self.llm.generate_json_response(
                system_prompt=system_prompt,
                user_message=user_prompt,
                temperature=0.2,  # Низкая креативность для консистентности
                context={
                    "user_id": context.user_context.user_id,
                }
            )

            print(result)

            if result.error:
                logger.error(f"Ошибка выбора агентов через LLM: {result.error}")
                return self._get_fallback_selection()

            # Шаг 4: Парсинг и валидация результата
            selection = self._parse_and_validate_result(result.response.message)

            # Шаг 5: Кэширование
            # self._save_to_cache(cache_key, selection)

            logger.info(
                f"LLM выбрал агентов: {selection['agent_names']} | "
                f"Уверенность: {selection['confidence']:.2f} | "
            )

            return selection

        except Exception as e:
            logger.error(f"Ошибка при выборе агентов через LLM: {e}", exc_info=True)
            return self._get_fallback_selection()

    def _build_system_prompt(self) -> str:
        """
        Формирование системного промпта для выбора агентов.

        Включает:
        - Роль и задачу LLM
        - Список всех доступных агентов с описаниями
        - Формат ожидаемого ответа
        - Критерии выбора
        """
        # Получаем всех агентов из реестра
        agents_metadata = agent_registry.get_agents_with_metadata()

        # Формируем описание агентов
        agents_descriptions = []
        for agent in agents_metadata:
            desc = f"- {agent['name']}: {agent['description']}"
            # if agent['supported_intents']:
            #     desc += f" (намерения: {', '.join(agent['supported_intents'])})"
            # if agent['capabilities']:
            #     desc += f" (возможности: {', '.join(agent['capabilities'])})"
            agents_descriptions.append(desc)

        agents_list = "\n".join(agents_descriptions)

        return f"""Вы — эксперт по выбору агентов для обработки запросов в системе обучения английскому языку.

ДОСТУПНЫЕ АГЕНТЫ:
{agents_list}

ВАША ЗАДАЧА:
Проанализируйте запрос студента и выберите оптимальный набор агентов для его обработки.

КРИТЕРИИ ВЫБОРА:
1. Каждый агент решает узкую задачу (грамматика, поддержка, профессиональный контекст)
2. Выбирайте минимально необходимый набор агентов
3. Учитывайте контекст студента (уровень, профессия, эмоциональное состояние)
4. При фрустрации добавляйте агент поддержки
5. При профессиональных тегах добавляйте профессиональный агент

ФОРМАТ ОТВЕТА (ТОЛЬКО JSON):
{{
    "agent_names": ["AgentName1", "AgentName2", ...],
    "reasoning": "Краткое обоснование выбора (1-2 предложения)",
    "confidence": 0.0-1.0  // Уверенность в выборе
}}

ВАЖНО:
- Возвращайте ТОЛЬКО валидный JSON
- Не добавляйте комментарии или пояснения
- Если сомневаетесь, выбирайте более консервативный набор агентов"""

    def _build_user_prompt(self, context: AgentContext) -> str:
        """
        Формирование пользовательского промпта с контекстом.

        Включает:
        - Сообщение студента
        - Профиль студента
        - Контекст урока
        - Поведенческие сигналы
        """
        print(f"_build_user_prompt\n{context=}")
        user_context = context.user_context

        # Базовый контекст
        prompt_parts = [
            f"Сообщение студента: \"{context.user_message}\"",
            "",
            "КОНТЕКСТ СТУДЕНТА:",
            f"- Уровень (CEFR): {user_context.cefr_level}",
            # f"- Профессиональные теги: {', '.join(context.get_professional_tags()) if context.get_professional_tags() else 'не указаны'}",
            # f"- Слабые места: {', '.join(context.get_weak_areas()) if context.get_weak_areas() else 'не выявлены'}",
            # f"- Цели обучения: {', '.join(context.user_context.get_learning_goals()) if context.user_context.get_learning_goals() else 'не указаны'}",
        ]

        # Контекст урока
        # if context.lesson_context:
        #     prompt_parts.extend([
        #         "",
        #         "КОНТЕКСТ УРОКА:",
        #         f"- Тип урока: {context.get_lesson_type()}",
        #         f"- Состояние: {context.get_lesson_state()}",
        #         f"- Прогресс: {context.lesson_context.progress.progress_percent:.0f}%",
        #         f"- Последний результат: {context.lesson_context.progress.last_task_result or 'нет данных'}",
        #     ])

        # Поведенческие сигналы
        frustration = user_context.confidence_level
        confidence = user_context.frustration_signals

        prompt_parts.extend([
            "",
            "ПОВЕДЕНЧЕСКИЕ СИГНАЛЫ:",
            f"- Фрустрация: {'да' if frustration else 'нет'}",
            f"- Уровень уверенности: {confidence}/10",
            # f"- Текущий стрик дней: {context.user_context.progress.current_streak_days}",
        ])

        # История разговора (последние 3 сообщения)
        # if context.conversation_history:
        #     history = context.conversation_history[-3:]
        #     if history:
        #         prompt_parts.extend([
        #             "",
        #             "ИСТОРИЯ РАЗГОВОРА (последние 3 сообщения):",
        #         ])
        #         for msg in history:
        #             role = "Студент" if msg.role == "user" else "Ассистент"
        #             prompt_parts.append(f"- {role}: {msg.content[:100]}")

        return "\n".join(prompt_parts)

    def _parse_and_validate_result(self, llm_response: Any) -> Dict:
        """
        Парсинг и валидация результата от LLM.

        Что делает:
        1. Проверяет структуру JSON
        2. Валидирует имена агентов (существуют ли в реестре)
        3. Проверяет обязательные поля
        4. Обеспечивает наличие хотя бы одного агента
        """
        # Парсинг JSON
        if isinstance(llm_response, str):
            try:
                llm_response = json.loads(llm_response)
            except json.JSONDecodeError:
                logger.warning(f"Невалидный JSON от LLM: {llm_response}")
                return self._get_fallback_selection()

        # Валидация структуры
        if not isinstance(llm_response, dict):
            return self._get_fallback_selection()

        # Обязательные поля
        required_fields = ["agent_names", "reasoning", "confidence"]
        for field in required_fields:
            if field not in llm_response:
                logger.warning(f"Отсутствует обязательное поле: {field}")
                return self._get_fallback_selection()

        # Валидация имён агентов
        available_agents = agent_registry.get_agent_names()
        agent_names = llm_response["agent_names"]

        if not isinstance(agent_names, list) or len(agent_names) == 0:
            return self._get_fallback_selection()

        # Фильтруем только существующие агенты
        valid_agent_names = [name for name in agent_names if name in available_agents]

        if not valid_agent_names:
            return self._get_fallback_selection()

        # Валидация уверенности
        confidence = llm_response.get("confidence", 0.5)
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            confidence = 0.5

        return {
            "agent_names": valid_agent_names,
            "reasoning": str(llm_response.get("reasoning", "Выбор через LLM")),
            "confidence": float(confidence),
            "selection_method": "llm"
        }

    def _get_fallback_selection(self) -> Dict:
        """
        Фолбэк-выбор агентов при ошибках LLM.


        """

        # TODO вернуть базовый набор агентов
        return {
            "agent_names": [],
            "reasoning": "fallback",
            "confidence": 0,
            "selection_method": "llm-fallback"
        }

    def _build_cache_key(self, context: AgentContext) -> str:
        """Формирование ключа кэша для идентичных запросов"""
        # Хэшируем ключевые параметры контекста
        key_parts = [
            context.get_cefr_level(),
            context.get_lesson_state() or "no_lesson",
            str(context.has_frustration()),
            str(context.get_confidence_level()),
            ",".join(sorted(context.get_professional_tags()[:3]))  # Первые 3 тега
        ]
        return "agent_selection_llm:" + "|".join(str(p) for p in key_parts)

    def _get_from_cache(self, cache_key: str) -> Optional[Dict]:
        """Получение результата из кэша"""
        try:
            return cache.get(cache_key)
        except Exception as e:
            logger.warning(f"Ошибка при чтении из кэша: {e}")
            return None

    def _save_to_cache(self, cache_key: str, result: Dict):
        """Сохранение результата в кэш"""
        try:
            cache.set(cache_key, result, timeout=self.cache_ttl)
        except Exception as e:
            logger.warning(f"Ошибка при записи в кэш: {e}")