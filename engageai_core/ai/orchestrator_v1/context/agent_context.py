"""
AgentContext: Единый контекст для всех агентов чат-оркестратора.


Ключевые принципы:
1. ЕДИНЫЙ КОНТЕКСТ — все агенты получают одинаковую базу данных
2. КОНТЕКСТНАЯ ИЗОЛЯЦИЯ — через `build_context_for_agent()` каждый агент получает ТОЛЬКО нужные ему данные
3. ЦЕЛИ И УВЕРЕННОСТЬ — система целей (1-10) и уровень уверенности для адаптации ответов
4. СОБЫТИЙНЫЙ ПОДХОД — все действия логируются как события для аналитики (Задача 2.1)
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Set
from datetime import datetime

from ai.orchestrator_v1.context.lesson_context import LessonContext
from ai.orchestrator_v1.context.user_context import UserContext


@dataclass
class GoalState:
    """
    Состояние цели обучения (адаптировано из промпта продажника).

    Цели определяют текущую фазу взаимодействия со студентом:
    - PROFILE_BUILDING: сбор информации о студенте (уровень, профессия, цели)
    - ENGAGEMENT: поддержание вовлечённости через микро-успехи
    - GAP_ANALYSIS: выявление слабых мест через диагностику
    - TUTORING: обучение и объяснение правил
    - PROGRESSION: навигация по учебному плану

    Оценка 1-10:
    - 1-3: цель почти не достигнута
    - 4-6: цель частично достигнута
    - 7-10: цель достигнута (можно переходить к следующей фазе)

    Примеры переходов:
    - Новый студент: PROFILE_BUILDING=3 → после 3 фактов → 7 → переход к GAP_ANALYSIS
    - Студент с ошибками: GAP_ANALYSIS=5 → после анализа 3 ошибок → 8 → переход к TUTORING
    """
    goal_type: str  # "prf", "eng", "gap", "tut", "prg"
    score: int = 3  # 1-10
    evidence: List[str] = field(default_factory=list)  # Факты, подтверждающие прогресс

    @property
    def is_achieved(self) -> bool:
        """Цель достигнута при оценке ≥7 с конкретными фактами"""
        return self.score >= 7 and len(self.evidence) >= 2

    def update(self, delta: int, evidence: Optional[str] = None):
        """Обновление цели с ограничением 1-10"""
        self.score = max(1, min(10, self.score + delta))
        if evidence:
            self.evidence.append(evidence)


@dataclass
class ConfidenceState:
    """
    Уровень уверенности студента (адаптировано из модуля TRUST_LOGIC промпта продажника).

    Уверенность управляет адаптацией ответов:
    - 1-4: низкая уверенность → упрощённые объяснения, микро-успехи, поддержка
    - 5-6: средняя уверенность → стандартные объяснения
    - 7-10: высокая уверенность → углублённые объяснения, сложные примеры

    Рост уверенности:
    - +1 за правильный ответ
    - +2 за серию из 3+ правильных ответов
    - +1 за активный вопрос ("почему", "как работает")

    Падение уверенности:
    - -1 за ошибку
    - -2 за серию из 3+ ошибок подряд (фрустрация)

    ВАЖНО: Уверенность НЕ блокирует ответ на учебный вопрос!
    Адаптация = изменение тона/структуры ответа, НЕ замена содержания.
    """
    level: int = 4  # 1-10, стартовый уровень
    frustration_signals: int = 0  # Счётчик ошибок подряд
    last_update: datetime = field(default_factory=datetime.now)

    def on_success(self, streak: int = 1):
        """Рост уверенности после успеха"""
        self.frustration_signals = max(0, self.frustration_signals - 1)
        if streak >= 3:
            self.level = min(10, self.level + 2)
        else:
            self.level = min(10, self.level + 1)
        self.last_update = datetime.now()

    def on_failure(self):
        """Падение уверенности после ошибки"""
        self.frustration_signals += 1
        if self.frustration_signals >= 3:
            self.level = max(1, self.level - 2)
        else:
            self.level = max(1, self.level - 1)
        self.last_update = datetime.now()

    @property
    def needs_support(self) -> bool:
        """Требуется ли эмоциональная поддержка?"""
        return self.level <= 4 and self.frustration_signals >= 3

    @property
    def can_advance(self) -> bool:
        """Можно ли переходить к сложному контенту?"""
        return self.level >= 7


@dataclass
class AgentContext:
    """
    Единый контекст для всех агентов чат-оркестратора.

    Структура обеспечивает:
    1. ПОЛНЫЙ КОНТЕКСТ СТУДЕНТА
       - Профиль (уровень, профессия, цели)
       - Прогресс (пройденные уроки, слабые места)
       - Эмоциональное состояние (уверенность, фрустрация)

    2. КОНТЕКСТ УРОКА
       - Состояние (открыт/на проверке/закрыт)
       - Прогресс выполнения
       - Ремедиация (причины, следующий урок)

    3. СИСТЕМА ЦЕЛЕЙ И УВЕРЕННОСТИ
       - 5 целей с оценкой 1-10 (как в промпте продажника)
       - Уровень уверенности для адаптации ответов
       - Приоритетная цель для выбора агента

    4. ИСТОРИЯ РАЗГОВОРА
       - Последние сообщения для контекстной памяти
       - Намерения предыдущих сообщений

    5. МЕТАДАННЫЕ ДЛЯ АНАЛИТИКИ
       - Уникальный ID запроса
       - Канал общения (web/telegram/whatsapp)
       - Временная метка

    Использование:
    >> # Базовый контекст для всех агентов
    >> context = AgentContext(
    ...     user_message="Почему здесь Past Perfect?",
    # ...     intent=IntentType.EXPLAIN_GRAMMAR,
    ...     user_context=user_context,
    ...     lesson_context=lesson_context,
    ...     goals={
    ...         "prf": GoalState("prf", score=8),
    ...         "gap": GoalState("gap", score=7),
    ...         "tut": GoalState("tut", score=5)
    ...     },
    ...     confidence=ConfidenceState(level=5, frustration_signals=2)
    ... )

    >> # Специализированный контекст для конкретного агента
    >> content_context = AgentContextService.build_context_for_agent(
    ...     agent_name="ContentAgent",
    ...     base_context=context
    ... )
    >> print(content_context.get_cefr_level())
    "B1"
    """

    # === ОСНОВНОЕ СООБЩЕНИЕ ===
    user_message: str
    # intent: IntentType  # Определённое намерение пользователя

    # === КОНТЕКСТЫ ===
    user_context: UserContext  # Глобальный контекст пользователя
    lesson_context: Optional[LessonContext] = None  # Контекст текущего урока

    # === ИСТОРИЯ РАЗГОВОРА ===
    # conversation_history: List[ConversationMessage] = field(default_factory=list)

    # === ДОПОЛНИТЕЛЬНЫЕ ДАННЫЕ ===
    extra_data: Dict[str, Any] = field(default_factory=dict)  # Для специализированных агентов

    # def __post_init__(self):
    #     """Инициализация целей по умолчанию, если не заданы"""
    #     if not self.goals:
    #         self.goals = {
    #             "prf": GoalState("prf", score=3),  # PROFILE_BUILDING
    #             "eng": GoalState("eng", score=5),  # ENGAGEMENT
    #             "gap": GoalState("gap", score=2),  # GAP_ANALYSIS
    #             "tut": GoalState("tut", score=2),  # TUTORING
    #             "prg": GoalState("prg", score=1),  # PROGRESSION
    #         }

    # === МЕТОДЫ ДОСТУПА К ДАННЫМ ===

    def get_user_id(self) -> int:
        """Получение ID пользователя"""
        return self.user_context.profile.user_id

    def get_username(self) -> str:
        """Получение имени пользователя"""
        return self.user_context.profile.username

    def get_cefr_level(self) -> str:
        """Получение текущего уровня пользователя"""
        return self.user_context.get_current_cefr_level()

    def get_professional_tags(self) -> List[str]:
        """Получение профессиональных тегов"""
        return self.user_context.get_professional_tags()

    def get_weak_areas(self) -> List[str]:
        """Получение слабых мест"""
        return list(self.user_context.get_weak_areas())

    def get_learning_goals(self) -> List[str]:
        """Получение целей обучения"""
        return self.user_context.get_learning_goals()

    def get_lesson_type(self) -> Optional[str]:
        """Получение типа текущего урока"""
        if self.lesson_context:
            return self.lesson_context.metadata.lesson_type.value
        return None

    def get_lesson_state(self) -> Optional[str]:
        """Получение состояния текущего урока"""
        if self.lesson_context:
            return self.lesson_context.progress.state.value
        return None

    def has_frustration(self) -> bool:
        """Есть ли признаки фрустрации?"""
        return self.confidence.frustration_signals >= 3

    def get_confidence_level(self) -> int:
        """Получение уровня уверенности (1-10)"""
        return self.confidence.level

    def needs_emotional_adaptation(self) -> bool:
        """Требуется ли адаптация ответа под эмоциональное состояние?"""
        return self.confidence.needs_support

    def get_priority_goal(self) -> str:
        """Получение приоритетной цели"""
        # Автоматическое определение приоритетной цели, если не задана
        if self.priority_goal == "prf" and self.goals["prf"].is_achieved:
            for goal_type in ["gap", "tut", "eng", "prg"]:
                if not self.goals[goal_type].is_achieved:
                    return goal_type
        return self.priority_goal

    # === МЕТОДЫ СЕРИАЛИЗАЦИИ ===

    def to_dict(self) -> Dict:
        """
        Сериализация в словарь для передачи в промпт агента.

        Включает ТОЛЬКО релевантные данные для генерации ответа:
        - Профиль студента
        - Контекст урока
        - Система целей и уверенности
        - История разговора (последние 5 сообщений)
        """
        return {
            "user_id": self.get_user_id(),
            "username": self.get_username(),
            "user_message": self.user_message,
            # "intent": self.intent.value,
            "cefr_level": self.get_cefr_level(),
            "professional_tags": self.get_professional_tags(),
            "weak_areas": self.get_weak_areas(),
            "learning_goals": self.get_learning_goals(),
            "lesson_type": self.get_lesson_type(),
            "lesson_state": self.get_lesson_state(),
            "goals": {k: v.score for k, v in self.goals.items()},
            "confidence_level": self.get_confidence_level(),
            "frustration_signals": self.confidence.frustration_signals,
            "priority_goal": self.get_priority_goal(),
            "has_frustration": self.has_frustration(),
            "needs_emotional_adaptation": self.needs_emotional_adaptation(),
            "conversation_history": [
                {
                    "role": msg.role,
                    "content": msg.content[:150],  # Обрезаем для экономии токенов
                    "intent": msg.intent.value if msg.intent else None
                }
                for msg in self.conversation_history[-5:]  # Последние 5 сообщений
            ],
            "channel": self.channel,
            "request_id": self.request_id,
        }

    def build_system_prompt_context(self) -> str:
        """
        Формирование контекста для системного промпта агента.

        Пример использования в агенте:
        >> system_prompt = f"Вы — эксперт по грамматике.\n{context.build_system_prompt_context()}"

        Возвращает строку с ключевыми данными для персонализации:
        - Уровень студента
        - Профессиональные теги
        - Слабые места
        - Эмоциональное состояние
        - Состояние урока
        """
        parts = [f"Студент: {self.get_username()}, уровень {self.get_cefr_level()}"]

        # Профиль пользователя

        if self.get_professional_tags():
            parts.append(f"Профессия: {', '.join(self.get_professional_tags())}")

        if self.get_learning_goals():
            parts.append(f"Цели обучения: {', '.join(self.get_learning_goals())}")

        if self.get_weak_areas():
            parts.append(f"Слабые места: {', '.join(self.get_weak_areas())}")

        # Контекст урока
        if self.lesson_context:
            parts.append(f"Текущий урок: {self.lesson_context.metadata.lesson_title}")
            parts.append(f"Состояние: {self.get_lesson_state()}")
            parts.append(f"Прогресс: {self.lesson_context.progress.progress_percent:.0f}%")

        # Эмоциональное состояние
        if self.has_frustration():
            parts.append(
                f"Эмоциональное состояние: фрустрация "
                f"({self.confidence.frustration_signals} ошибок подряд), "
                f"уверенность {self.get_confidence_level()}/10"
            )
        else:
            parts.append(f"Уверенность: {self.get_confidence_level()}/10")

        # Приоритетная цель
        priority_desc = {
            "prf": "сбор профиля",
            "eng": "поддержание вовлечённости",
            "gap": "анализ пробелов",
            "tut": "обучение",
            "prg": "навигация по плану"
        }
        parts.append(f"Приоритетная цель: {priority_desc.get(self.get_priority_goal(), 'неизвестно')}")

        return "\n".join(parts)
