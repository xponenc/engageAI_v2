import json
import logging
from typing import List, Dict, Optional, Any

from django.core.cache import cache # TODO разбираться с кешем

from ai.llm_service.factory import llm_factory
from ai.orchestrator_v1.agents.agents_registry import agent_registry
from ai.orchestrator_v1.context.agent_context import AgentContext
from utils.setup_logger import setup_logger


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
        self.logger = setup_logger(name=__file__, log_dir="logs/universal_orchestrator",
                                   log_file="agent_selection_llm.log")


    async def select_agents(
            self,
            request_id: str,
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
        # cached_result = self._get_from_cache(request_id=request_id, cache_key=cache_key)
        #
        # if cached_result and not force_use_llm:
        #     logger.debug(f"Выбор агентов из кэша: {cached_result['agent_names']}")
        #     return cached_result

        # Шаг 2: Формирование промпта
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(context)

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

            if result.error:
                self.logger.error(f"[REQ:{request_id}] Ошибка выбора агентов через LLM: {result.error}")
                return self._get_fallback_selection()

            # Шаг 4: Парсинг и валидация результата
            selection = self._parse_and_validate_result(
                request_id=request_id,
                llm_response=result.response.message)

            # Шаг 5: Кэширование
            # self._save_to_cache(request_id=request_id, cache_key=cache_key, result=selection)

            return selection

        except Exception as e:
            self.logger.error(f"[REQ:{request_id}] Ошибка при выборе агентов через LLM: {e}", exc_info=True)
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
        user_context = context.user_context
        prompt= f"""
Контекст ученика:
{user_context.to_prompt()}

Сообщение ученика: 
{context.user_message}
"""
        return prompt

    def _parse_and_validate_result(self,request_id:str, llm_response: Any) -> Dict:
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
                self.logger.warning(f"[REQ:{request_id}] Невалидный JSON от LLM: {llm_response}")
                return self._get_fallback_selection()

        # Валидация структуры
        if not isinstance(llm_response, dict):
            return self._get_fallback_selection()

        # Обязательные поля
        required_fields = ["agent_names", "reasoning", "confidence"]
        for field in required_fields:
            if field not in llm_response:
                self.logger.warning(f"[REQ:{request_id}] Отсутствует обязательное поле: {field}")
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
        agents_metadata = agent_registry.get_agents_with_metadata()

        # Формируем описание агентов
        agents = [agent['name'] for agent in agents_metadata if agent.get("fallback_agent", False) == True]

        return {
            "agent_names": agents,
            "reasoning": "fallback on AgentSelectionLLM error",
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

    def _get_from_cache(self, request_id:str, cache_key: str) -> Optional[Dict]:
        """Получение результата из кэша"""
        try:
            return cache.get(cache_key)
        except Exception as e:
            self.logger.warning(f"[REQ:{request_id}] Ошибка при чтении из кэша: {e}")
            return None

    def _save_to_cache(self,request_id:str, cache_key: str, result: Dict):
        """Сохранение результата в кэш"""
        try:
            cache.set(cache_key, result, timeout=self.cache_ttl)
        except Exception as e:
            self.logger.warning(f"[REQ:{request_id}] Ошибка при записи в кэш: {e}")