# TODO на позднюю разработку можно попробоавть реализовать выбор агента на основе правил до применения выбора через LLM
# """
# AgentSelectionService: Интеллектуальный выбор агентов на основе контекста.
#
# Соответствует ТЗ:
# - Задача 1.1: Центральный Умный Чат-Помощник (выбор правильных агентов под контекст)
# - Задача 2.1: Единая модель данных (выбор на основе структурированного контекста)
# - Задача 5.1: Оптимизация стоимости (минимизация избыточных вызовов агентов)
#
# Ключевые принципы:
# 1. НЕТ разделения на "основной/вспомогательный" — все агенты равноправны
# 2. Каждый агент решает узкую задачу (грамматика, поддержка, профессиональный контекст)
# 3. Выбор на основе: намерение + состояние урока + эмоциональный контекст + профиль
# 4. Гибридный подход: правила (95% случаев) + опционально LLM (сложные случаи)
# 5. Кэширование частых комбинаций для оптимизации
# """
# import json
# import logging
# from typing import List, Dict, Optional, Set, Tuple
# from dataclasses import dataclass, field
# from enum import Enum
# from datetime import datetime
#
# from django.conf import settings
# from django.core.cache import cache
#
# from curriculum.chat.context.agent_context import AgentContext, IntentType
# from curriculum.chat.context.lesson_context import LessonState
# from curriculum.chat.context.user_context import CEFRLevel, ProfessionalDomain, LearningGoal
#
# logger = logging.getLogger(__name__)
#
#
# class AgentName(str, Enum):
#     """Имена всех доступных агентов"""
#     CONTENT = "ContentAgent"  # Объяснение грамматики и лексики
#     WRITING = "WritingAgent"  # Проверка письменной речи
#     SPEAKING = "SpeakingAgent"  # Разговорная практика
#     PROFESSIONAL = "ProfessionalAgent"  # Профессиональные сценарии
#     PROGRESS = "ProgressAgent"  # Прогресс и аналитика
#     PLANNER = "PlannerAgent"  # Навигация и планирование
#     SUPPORT = "SupportAgent"  # Эмоциональная поддержка
#     GOALS = "GoalsAgent"  # Работа с целями
#     PLATFORM = "PlatformAgent"  # Технические вопросы
#     GAMIFICATION = "GamificationAgent"  # Достижения и бейджи
#     FALLBACK = "FallbackAgent"  # Резервный агент
#
#
# @dataclass
# class SelectionRule:
#     """
#     Правило выбора агентов.
#
#     Примеры правил:
#     - При намерении "объяснить грамматику" → всегда вызывать ContentAgent
#     - При фрустрации (≥3 ошибки) → добавить SupportAgent
#     - При профессиональных тегах → добавить ProfessionalAgent
#     """
#     name: str
#     description: str
#     priority: int  # Чем выше, тем раньше применяется
#
#     # Условия срабатывания
#     intent_in: Optional[Set[str]] = None
#     lesson_state_in: Optional[Set[LessonState]] = None
#     frustration_threshold: Optional[int] = None
#     confidence_threshold: Optional[int] = None
#     has_professional_tags: bool = False
#     weak_areas_in: Optional[Set[str]] = None
#
#     # Агенты для вызова при срабатывании
#     agents_to_add: List[AgentName] = field(default_factory=list)
#
#     # Флаги модификации
#     replace_existing: bool = False  # Заменить текущий список агентов
#
#     def matches(self, context: AgentContext) -> bool:
#         """Проверка соответствия контекста правилу"""
#         # Проверка намерения
#         if self.intent_in and context.intent.value not in self.intent_in:
#             return False
#
#         # Проверка состояния урока
#         if self.lesson_state_in and context.lesson_context:
#             if context.lesson_context.progress.state not in self.lesson_state_in:
#                 return False
#
#         # Проверка фрустрации
#         if self.frustration_threshold is not None:
#             frustration = context.lesson_context.frustration_signals if context.lesson_context else 0
#             if frustration < self.frustration_threshold:
#                 return False
#
#         # Проверка уверенности
#         if self.confidence_threshold is not None:
#             confidence = context.get_confidence_level()
#             if confidence > self.confidence_threshold:  # Низкая уверенность = высокий порог
#                 return False
#
#         # Проверка профессиональных тегов
#         if self.has_professional_tags:
#             if not context.get_professional_tags():
#                 return False
#
#         # Проверка слабых мест
#         if self.weak_areas_in and context.get_weak_areas():
#             weak_areas = set(context.get_weak_areas())
#             if not weak_areas.intersection(self.weak_areas_in):
#                 return False
#
#         return True
#
#
# @dataclass
# class SelectionResult:
#     """Результат выбора агентов"""
#     agent_names: List[str]
#     selection_method: str  # "rules", "llm", "cached"
#     rules_applied: List[str]
#     reasoning: str
#     confidence: float  # 0.0-1.0 уверенность в выборе
#     cache_key: Optional[str] = None
#
#
# class AgentSelectionService:
#     """
#     Сервис выбора агентов с гибридной логикой (правила + опционально LLM).
#
#     Архитектурные особенности:
#     - Все агенты равноправны — каждый решает свою узкую задачу
#     - НЕТ искусственного разделения на "основной/вспомогательный"
#     - Выбор на основе полного контекста (намерение + состояние + эмоции)
#     - Кэширование частых комбинаций для оптимизации (Задача 5.1 ТЗ)
#     - Поддержка горячей перезагрузки правил без перезапуска сервиса
#     """
#
#     _instance = None
#     _rules: List[SelectionRule] = []
#     _rules_last_loaded: Optional[datetime] = None
#
#     def __new__(cls):
#         if cls._instance is None:
#             cls._instance = super(AgentSelectionService, cls).__new__(cls)
#             cls._instance._initialize_rules()
#         return cls._instance
#
#     def _initialize_rules(self):
#         """Инициализация правил выбора агентов"""
#         self._rules = [
#             # === ПРАВИЛО 1: Базовые агенты по намерению ===
#             SelectionRule(
#                 name="grammar_explanation",
#                 description="Объяснение грамматики",
#                 priority=100,
#                 intent_in={"EXPLAIN_GRAMMAR", "ANALYZE_ERROR", "WHY_WRONG"},
#                 agents_to_add=[AgentName.CONTENT],
#                 replace_existing=True
#             ),
#             SelectionRule(
#                 name="vocabulary_practice",
#                 description="Практика лексики",
#                 priority=95,
#                 intent_in={"PRACTICE_VOCABULARY"},
#                 agents_to_add=[AgentName.CONTENT],
#                 replace_existing=True
#             ),
#             SelectionRule(
#                 name="writing_check",
#                 description="Проверка письменной речи",
#                 priority=90,
#                 intent_in={"CHECK_WRITING"},
#                 agents_to_add=[AgentName.WRITING],
#                 replace_existing=True
#             ),
#             SelectionRule(
#                 name="speaking_practice",
#                 description="Разговорная практика",
#                 priority=85,
#                 intent_in={"PRACTICE_SPEAKING", "EVALUATE_SPEECH", "START_CONVERSATION"},
#                 agents_to_add=[AgentName.SPEAKING],
#                 replace_existing=True
#             ),
#             SelectionRule(
#                 name="professional_scenario",
#                 description="Профессиональные сценарии",
#                 priority=80,
#                 intent_in={"PROFESSIONAL_SCENARIO", "ROLE_PLAY"},
#                 agents_to_add=[AgentName.PROFESSIONAL],
#                 replace_existing=True
#             ),
#             SelectionRule(
#                 name="progress_query",
#                 description="Вопросы о прогрессе",
#                 priority=75,
#                 intent_in={"QUERY_PROGRESS", "QUERY_NEXT_STEP", "ASK_REMEDIATION"},
#                 agents_to_add=[AgentName.PROGRESS, AgentName.PLANNER],
#                 replace_existing=True
#             ),
#             SelectionRule(
#                 name="gamification_query",
#                 description="Вопросы о достижениях",
#                 priority=70,
#                 intent_in={"QUERY_GAMIFICATION", "CHECK_ACHIEVEMENTS"},
#                 agents_to_add=[AgentName.GAMIFICATION],
#                 replace_existing=True
#             ),
#             SelectionRule(
#                 name="platform_help",
#                 description="Технические вопросы",
#                 priority=65,
#                 intent_in={"PLATFORM_HELP", "REPORT_BUG"},
#                 agents_to_add=[AgentName.PLATFORM],
#                 replace_existing=True
#             ),
#             SelectionRule(
#                 name="general_chat",
#                 description="Общая беседа",
#                 priority=60,
#                 intent_in={"GENERAL_CHAT"},
#                 agents_to_add=[AgentName.FALLBACK],
#                 replace_existing=True
#             ),
#
#             # === ПРАВИЛО 2: Контекстные агенты (добавляются к базовым) ===
#             SelectionRule(
#                 name="add_support_on_frustration",
#                 description="Добавить поддержку при фрустрации",
#                 priority=50,
#                 frustration_threshold=3,
#                 agents_to_add=[AgentName.SUPPORT],
#                 replace_existing=False  # ДОБАВЛЯЕМ к существующим агентам
#             ),
#             SelectionRule(
#                 name="add_goals_on_low_motivation",
#                 description="Добавить работу с целями при низкой мотивации",
#                 priority=45,
#                 confidence_threshold=4,  # Уверенность ≤4
#                 agents_to_add=[AgentName.GOALS],
#                 replace_existing=False
#             ),
#             SelectionRule(
#                 name="add_professional_context",
#                 description="Добавить профессиональный контекст при наличии тегов",
#                 priority=40,
#                 has_professional_tags=True,
#                 agents_to_add=[AgentName.PROFESSIONAL],
#                 replace_existing=False
#             ),
#             SelectionRule(
#                 name="add_weak_areas_focus",
#                 description="Фокус на слабых местах при анализе ошибок",
#                 priority=35,
#                 intent_in={"ANALYZE_ERROR", "WHY_WRONG"},
#                 weak_areas_in={"past_tenses", "prepositions", "articles", "irregular_verbs"},
#                 agents_to_add=[AgentName.CONTENT],
#                 replace_existing=False
#             ),
#
#             # === ПРАВИЛО 3: Специальные состояния урока ===
#             SelectionRule(
#                 name="in_review_state",
#                 description="Урок в состоянии проверки — фокус на прогрессе",
#                 priority=30,
#                 lesson_state_in={LessonState.IN_REVIEW},
#                 agents_to_add=[AgentName.PROGRESS],
#                 replace_existing=True
#             ),
#             SelectionRule(
#                 name="completed_state",
#                 description="Урок завершён — фокус на навигации",
#                 priority=25,
#                 lesson_state_in={LessonState.COMPLETED},
#                 agents_to_add=[AgentName.PLANNER, AgentName.PROGRESS],
#                 replace_existing=True
#             ),
#         ]
#
#         # Сортируем правила по приоритету (высший приоритет первым)
#         self._rules.sort(key=lambda r: r.priority, reverse=True)
#         self._rules_last_loaded = datetime.now()
#
#     async def select_agents(
#             self,
#             intent: str,
#             context: AgentContext,
#             use_llm_fallback: bool = False,
#             force_agents: Optional[List[str]] = None
#     ) -> SelectionResult:
#         """
#         Выбор списка агентов для обработки запроса.
#
#         Алгоритм:
#         1. Проверка кэша по хэшу контекста (быстро для частых комбинаций)
#         2. Применение правил в порядке приоритета
#         3. Опционально: валидация через LLM для сложных случаев
#         4. Кэширование результата
#
#         Возвращает:
#             SelectionResult с именами агентов и метаданными для аналитики
#         """
#         # Шаг 1: Проверка кэша
#         cache_key = self._build_cache_key(intent, context)
#         cached_result = self._get_from_cache(cache_key)
#         if cached_result:
#             logger.debug(f"Выбор агентов из кэша: {cached_result.agent_names}")
#             return cached_result
#
#         # Шаг 2: Применение правил
#         agent_names, rules_applied, reasoning = self._apply_rules(intent, context)
#
#         # Шаг 3: Валидация через LLM (опционально для сложных случаев)
#         if use_llm_fallback and len(agent_names) > 3:
#             llm_result = await self._validate_with_llm(agent_names, intent, context)
#             if llm_result:
#                 agent_names = llm_result.agent_names
#                 reasoning = f"LLM validation: {llm_result.reasoning}"
#
#         # Шаг 4: Удаление дубликатов и фолбэк при пустом результате
#         agent_names = list(dict.fromkeys(agent_names))  # Сохраняем порядок, удаляем дубли
#
#         if not agent_names:
#             agent_names = [AgentName.FALLBACK.value]
#             rules_applied = ["fallback_applied"]
#             reasoning = "No agents selected by rules — using fallback"
#
#         # Шаг 5: Формирование результата
#         result = SelectionResult(
#             agent_names=agent_names,
#             selection_method="rules",
#             rules_applied=rules_applied,
#             reasoning=reasoning,
#             confidence=0.95 if len(rules_applied) > 0 else 0.7,
#             cache_key=cache_key
#         )
#
#         # Шаг 6: Кэширование результата
#         self._save_to_cache(cache_key, result)
#
#         logger.info(
#             f"Выбраны агенты: {agent_names} | "
#             f"Правила: {rules_applied} | "
#             f"Контекст: intent={intent}, frustration={context.has_frustration()}, "
#             f"lesson_state={context.get_lesson_state()}"
#         )
#
#         return result
#
#     def _apply_rules(self, intent: str, context: AgentContext) -> Tuple[List[str], List[str], str]:
#         """
#         Применение правил выбора агентов.
#
#         Возвращает:
#             (список_агентов, применённые_правила, обоснование)
#         """
#         selected_agents: List[str] = []
#         applied_rules: List[str] = []
#         reasoning_parts: List[str] = []
#
#         # Применяем правила в порядке приоритета
#         for rule in self._rules:
#             if rule.matches(context):
#                 if rule.replace_existing:
#                     # Заменяем текущий список агентов
#                     selected_agents = [agent.value for agent in rule.agents_to_add]
#                     applied_rules = [rule.name]
#                     reasoning_parts = [f"Правило '{rule.name}': замена списка агентов"]
#                 else:
#                     # Добавляем агенты к существующему списку
#                     new_agents = [agent.value for agent in rule.agents_to_add]
#                     for agent in new_agents:
#                         if agent not in selected_agents:
#                             selected_agents.append(agent)
#                     applied_rules.append(rule.name)
#                     reasoning_parts.append(f"Правило '{rule.name}': добавлены агенты {new_agents}")
#
#                 # Логируем применение правила
#                 logger.debug(f"Применено правило '{rule.name}': {rule.description}")
#
#         # Если ни одно правило не сработало — используем фолбэк
#         if not selected_agents:
#             selected_agents = [AgentName.FALLBACK.value]
#             applied_rules = ["no_rules_matched"]
#             reasoning_parts = ["Ни одно правило не сработало — фолбэк"]
#
#         return selected_agents, applied_rules, "; ".join(reasoning_parts)
#
#     async def _validate_with_llm(
#             self,
#             current_agents: List[str],
#             intent: str,
#             context: AgentContext
#     ) -> Optional[SelectionResult]:
#         """
#         Валидация выбора агентов через LLM для сложных случаев.
#
#         Используется ТОЛЬКО при:
#         - Большом количестве агентов (>3)
#         - Конфликтующих правилах
#         - Низкой уверенности в выборе
#
#         Возвращает:
#             Оптимизированный список агентов или None (если валидация не требуется)
#         """
#         # Для пилота — заглушка (реализация при необходимости)
#         return None
#
#     def _build_cache_key(self, intent: str, context: AgentContext) -> str:
#         """
#         Формирование ключа кэша для идентичных запросов.
#
#         Ключ включает:
#         - Намерение
#         - Уровень пользователя
#         - Состояние урока
#         - Признаки фрустрации
#         - Профессиональные теги (хэш)
#         """
#         # Упрощённая реализация — для продакшена использовать хэширование
#         key_parts = [
#             intent,
#             context.get_cefr_level(),
#             context.get_lesson_state() or "no_lesson",
#             str(context.has_frustration()),
#             str(context.get_confidence_level()),
#             ",".join(sorted(context.get_professional_tags()[:3]))  # Первые 3 тега
#         ]
#         return "agent_selection:" + "|".join(str(p) for p in key_parts)
#
#     def _get_from_cache(self, cache_key: str) -> Optional[SelectionResult]:
#         """Получение результата из кэша"""
#         try:
#             cached = cache.get(cache_key)
#             if cached:
#                 # Восстанавливаем объект из словаря
#                 return SelectionResult(
#                     agent_names=cached["agent_names"],
#                     selection_method=cached["selection_method"],
#                     rules_applied=cached["rules_applied"],
#                     reasoning=cached["reasoning"],
#                     confidence=cached["confidence"],
#                     cache_key=cache_key
#                 )
#         except Exception as e:
#             logger.warning(f"Ошибка при чтении из кэша: {e}")
#         return None
#
#     def _save_to_cache(self, cache_key: str, result: SelectionResult):
#         """Сохранение результата в кэш"""
#         try:
#             cache.set(
#                 cache_key,
#                 {
#                     "agent_names": result.agent_names,
#                     "selection_method": result.selection_method,
#                     "rules_applied": result.rules_applied,
#                     "reasoning": result.reasoning,
#                     "confidence": result.confidence,
#                     "cached_at": datetime.now().isoformat()
#                 },
#                 timeout=300  # 5 минут
#             )
#         except Exception as e:
#             logger.warning(f"Ошибка при записи в кэш: {e}")
#
#     @classmethod
#     def reload_rules(cls):
#         """Горячая перезагрузка правил без перезапуска сервиса"""
#         instance = cls()
#         instance._initialize_rules()
#         logger.info(f"Правила выбора агентов перезагружены: {len(instance._rules)} правил")
#
#     @classmethod
#     def get_current_rules(cls) -> List[Dict]:
#         """Получение текущих правил в сериализуемом формате"""
#         instance = cls()
#         return [
#             {
#                 "name": rule.name,
#                 "description": rule.description,
#                 "priority": rule.priority,
#                 "conditions": {
#                     "intent_in": list(rule.intent_in) if rule.intent_in else None,
#                     "frustration_threshold": rule.frustration_threshold,
#                     "has_professional_tags": rule.has_professional_tags
#                 },
#                 "agents_to_add": [agent.value for agent in rule.agents_to_add],
#                 "replace_existing": rule.replace_existing
#             }
#             for rule in instance._rules
#         ]
#
#     @classmethod
#     def add_custom_rule(cls, rule: SelectionRule):
#         """Добавление кастомного правила в рантайме"""
#         instance = cls()
#         instance._rules.append(rule)
#         instance._rules.sort(key=lambda r: r.priority, reverse=True)
#         logger.info(f"Добавлено кастомное правило: {rule.name}")