# curriculum/chat/agents/base.py
"""
BaseAgent: Абстрактный базовый класс для всех агентов чат-оркестратора.

Соответствует ТЗ:
- Задача 1.1: Единый путь для студента через специализированных агентов
- Задача 2.1: Интеграция с событийной шиной для синхронизации
- Задача 5.2: Гибкость архитектуры (легко добавить/заменить агентов)

Ключевые принципы архитектуры:
1. Агент НИКОГДА не игнорирует учебный вопрос студента
2. Адаптация под эмоциональное состояние = изменение тона/структуры ответа, НЕ замена темы
3. Все агенты работают в композиции: основной агент = содержание, вспомогательные = адаптация
4. Единый контекст для всех агентов (состояние урока, цели, уверенность)
"""
import abc
import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

from ai.llm_service.dtos import GenerationResult
from ai.llm_service.factory import llm_factory
from ai.orchestrator_v1.context.agent_context import AgentContext

logger = logging.getLogger(__name__)


class BaseAgent(abc.ABC):
    """
    Абстрактный базовый класс для всех агентов чат-оркестратора.
    
    === ПОЛЯ КЛАССА (должны быть переопределены в наследниках) ===
    
    1. name: str
       Уникальное имя агента для идентификации в системе.
       
       Требования:
       - Должно быть уникальным в рамках всей системы
       - Рекомендуется использовать формат: "ContentAgent", "WritingAgent"
       - Используется для автоматической регистрации в реестре
       
       Пример:
           name = "ContentAgent"
    
    2. description: str
       Краткое описание назначения агента (1-2 предложения).
       
       Требования:
       - Должно быть понятным для человека
       - Используется в промптах для выбора агентов через LLM
       - Максимальная длина: 100 символов
       
       Пример:
           description = "Объяснение грамматики и лексики английского языка"
    
    3. supported_intents: List[str]
       Список намерений пользователя, которые агент может обрабатывать.
       
       Требования:
       - Строка в формате: "EXPLAIN_GRAMMAR", "CHECK_WRITING"
       - Используется для первичной фильтрации агентов
       - Может быть пустым списком (агент обрабатывает все намерения)
       
       Пример:
           supported_intents = ["EXPLAIN_GRAMMAR", "ANALYZE_ERROR", "WHY_WRONG"]
    
    4. capabilities: List[str] (опционально)
       Список возможностей агента для композиции с другими агентами.
       
       Требования:
       - Описывает, что агент умеет делать
       - Используется для выбора вспомогательных агентов
       - Может быть пустым списком
       
       Пример:
           capabilities = ["grammar_explanation", "vocabulary_teaching", "error_analysis"]
    
    5. version: str (опционально)
       Версия агента для отслеживания изменений.
       
       Требования:
       - Формат: "1.0", "2.1", "3.0-beta"
       - По умолчанию: "1.0"
       
       Пример:
           version = "2.1"
    
    === МЕТОДЫ ЭКЗЕМПЛЯРА ===
    
    1. __init__(self)
       Конструктор агента.
       
       Что делает:
       - Инициализирует доступ к LLM через фабрику
       - Настраивает логгер для агента
       - Инициализирует кэш (если используется)
       
       Пример:
           def __init__(self):
               super().__init__()
               self.llm = llm_factory
               self.logger = logging.getLogger(f"{__name__}.{self.name}")
    
    2. handle(self, context: AgentContext) -> AgentResponse
       Основной метод обработки запроса студента.
       
       Аргументы:
           context: AgentContext
               Полный контекст запроса, включающий:
               - Сообщение пользователя
               - Намерение пользователя
               - Профиль пользователя (уровень, профессия, цели)
               - Контекст текущего урока
               - История разговора
               - Поведенческие сигналы (фрустрация, уверенность)
       
       Возвращает:
           AgentResponse
               Стандартизированный ответ агента с:
               - Текстом ответа
               - Метаданными для аналитики
               - Флагами для оркестратора
       
       Требования:
           - Метод ДОЛЖЕН быть переопределён в наследниках
           - Агент ВСЕГДА отвечает по содержанию вопроса студента
           - Адаптация под эмоциональное состояние происходит НА УРОВНЕ ОРКЕСТРАТОРА
           - Любая ошибка обрабатывается через фолбэк-агента (не прерывает учебный процесс)
       
       Пример:
           async def handle(self, context: AgentContext) -> AgentResponse:
               # 1. Формируем промпт с контекстом
               system_prompt = self._build_system_prompt(context)
               
               # 2. Генерируем ответ через LLM
               response_text, tokens = await self._generate_response_with_llm(
                   system_prompt=system_prompt,
                   user_message=context.user_message,
                   context=context
               )
               
               # 3. Формируем ответ
               return AgentResponse(
                   text=response_text,
                   metadata={
                       "tokens_used": tokens,
                       "agent": self.name
                   }
               )
    
    === ЗАЩИЩЁННЫЕ МЕТОДЫ (для использования в наследниках) ===
    
    1. _build_system_prompt(self, context: AgentContext) -> str
       Формирование системного промпта для LLM с учётом контекста.
       
       Что делает:
       - Включает профиль пользователя (уровень, профессия)
       - Добавляет слабые места студента
       - Учитывает эмоциональное состояние (для адаптации тона)
       - Формулирует требования к ответу (длина, стиль)
       
       Пример:
           def _build_system_prompt(self, context: AgentContext) -> str:
               return f'''Вы — эксперт по грамматике английского языка.
               
               Контекст студента:
               - Уровень: {context.get_cefr_level()}
               - Профессия: {", ".join(context.get_professional_tags())}
               - Слабые места: {", ".join(context.get_weak_areas())}
               
               Ваша задача: объяснить правило максимально понятно и кратко.'''
    
    2. _generate_response_with_llm(
           self,
           system_prompt: str,
           user_message: str,
           context: AgentContext,
           temperature: float = 0.3,
           max_tokens: int = 500
       ) -> tuple[str, int]
       
       Безопасная генерация ответа через LLM.
       
       Что делает:
       - Вызывает LLM с заданными параметрами
       - Автоматически логирует вызов для аналитики (Задача 5.1 ТЗ)
       - Обрабатывает ошибки через фолбэк
       - Возвращает текст ответа и количество использованных токенов
       
       Аргументы:
           system_prompt: Системный промпт для агента
           user_message: Сообщение студента
           context: Контекст для персонализации
           temperature: Креативность ответа (0.1-0.7)
           max_tokens: Максимальная длина ответа
       
       Возвращает:
           (текст_ответа: str, токены_использовано: int)
    
    === СТАТИЧЕСКИЕ МЕТОДЫ ===
    
    1. can_handle_intent(cls, intent: str) -> bool
       Проверка, может ли агент обрабатывать данное намерение.
       
       Возвращает:
           True, если intent в supported_intents или supported_intents пустой
           False в противном случае
    
    === ПРИМЕР РЕАЛИЗАЦИИ НАСЛЕДНИКА ===
    
    ```python
    class ContentAgent(BaseAgent):
        \"\"\"Агент для объяснения грамматики и лексики\"\"\"
        
        name = "ContentAgent"
        description = "Объяснение грамматических правил и лексики английского языка"
        supported_intents = ["EXPLAIN_GRAMMAR", "PRACTICE_VOCABULARY", "ANALYZE_ERROR"]
        capabilities = ["grammar_explanation", "vocabulary_teaching", "error_analysis"]
        version = "1.0"
        
        async def handle(self, context: AgentContext) -> AgentResponse:
            # Формируем промпт с полным контекстом
            system_prompt = self._build_system_prompt(context)
            
            # Генерируем ответ через LLM
            response_text, tokens = await self._generate_response_with_llm(
                system_prompt=system_prompt,
                user_message=context.user_message,
                context=context,
                max_tokens=400,
                temperature=0.3
            )
            
            # Формируем ответ
            return AgentResponse(
                text=response_text,
                metadata={
                    "agent": self.name,
                    "tokens_used": tokens,
                    "intent": context.intent.value,
                    "cefr_level": context.get_cefr_level()
                }
            )
        
        def _build_system_prompt(self, context: AgentContext) -> str:
            \"\"\"Формирование промпта с контекстом студента\"\"\"
            emotional_tone = "поддерживающий" if context.has_frustration() else "нейтральный"
            
            return f'''Вы — эксперт по грамматике английского языка.
            
            Контекст студента:
            - Уровень: {context.get_cefr_level()}
            - Профессия: {", ".join(context.get_professional_tags())}
            - Слабые места: {", ".join(context.get_weak_areas())}
            - Эмоциональное состояние: {emotional_tone}
            
            Задача: Объясните правило максимально понятно, используйте примеры из профессиональной сферы студента.
            Максимальная длина ответа: 200 слов.'''
    ```
    """
    
    # === ПОЛЯ КЛАССА (должны быть переопределены в наследниках) ===
    
    name: str = "BaseAgent"
    description: str = "Abstract base agent"
    supported_intents: List[str] = []
    capabilities: List[str] = []
    version: str = "1.0"
    
    def __init__(self):
        """Инициализация агента"""
        self.llm = llm_factory
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    @abc.abstractmethod
    async def handle(self, context: AgentContext) -> 'AgentResponse':
        """
        Основной метод обработки запроса студента.
        
        ВАЖНО: Агент ВСЕГДА отвечает по содержанию вопроса студента.
        Адаптация под эмоциональное состояние происходит НА УРОВНЕ ОРКЕСТРАТОРА,
        а не через замену содержания ответа.
        
        Аргументы:
            context: Полный контекст запроса (см. AgentContext)
            
        Возвращает:
            AgentResponse с текстом ответа и метаданными
            
        Исключения:
            Любая ошибка обрабатывается оркестратором через фолбэк-агента.
            Агент НЕ должен прерывать учебный процесс из-за внутренних ошибок.
        """
        pass
    
    def _build_system_prompt(self, context: AgentContext) -> str:
        """
        Формирование системного промпта для LLM с учётом контекста.
        
        Базовая реализация — должна быть переопределена в наследниках.
        """
        return f"Вы — {self.description}. Отвечайте на вопросы студента."
    
    async def _generate_response_with_llm(
        self,
        system_prompt: str,
        user_message: str,
        context: AgentContext,
        temperature: float = 0.3,
        max_tokens: int = 500
    ) -> tuple[str, int]:
        """
        Безопасная генерация ответа через LLM.
        
        Что делает:
        - Вызывает LLM с заданными параметрами
        - Автоматически логирует вызов для аналитики (Задача 5.1 ТЗ)
        - Обрабатывает ошибки через фолбэк
        - Возвращает текст ответа и количество использованных токенов
        
        Аргументы:
            system_prompt: Системный промпт для агента
            user_message: Сообщение студента
            context: Контекст для персонализации
            temperature: Креативность ответа (0.1-0.7)
            max_tokens: Максимальная длина ответа
        
        Возвращает:
            (текст_ответа: str, токены_использовано: int)
        """
        try:
            result = await self.llm.generate_text(
                system_prompt=system_prompt,
                user_message=user_message,
                temperature=temperature,
                max_tokens=max_tokens,
                context={
                    "agent": self.name,
                    "user_id": context.user_id,
                    "intent": context.intent.value,
                }
            )
            
            tokens_used = result.metrics.input_tokens + result.metrics.output_tokens
            
            self.logger.info(
                f"LLM вызов завершён: агент={self.name}, "
                f"токены={tokens_used}, стоимость=${result.metrics.cost_total:.6f}"
            )
            
            return result.response.message, tokens_used
            
        except Exception as e:
            self.logger.error(f"Ошибка LLM в агенте {self.name}: {e}", exc_info=True)
            
            # Фолбэк-ответ (без прерывания учебного процесса)
            fallback_text = self._get_fallback_response(context)
            return fallback_text, 0
    
    def _get_fallback_response(self, context: AgentContext) -> str:
        """Генерация фолбэк-ответа при ошибках LLM"""
        return f"Давайте разберём этот вопрос подробнее. {context.user_message}"
    
    @classmethod
    def can_handle_intent(cls, intent: str) -> bool:
        """Проверка, может ли агент обрабатывать данное намерение"""
        return not cls.supported_intents or intent in cls.supported_intents
    
    def __str__(self) -> str:
        return f"{self.name} (v{self.version})"
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self.name}>"


@dataclass
class AgentResponse:
    """
    Стандартизированный ответ агента для агрегации оркестратором.
    
    Структура обеспечивает:
    - Единый формат для всех агентов
    - Метаданные для аналитики (Задача 2.3 ТЗ)
    - Флаги для адаптации ответа оркестратором
    - Поддержку мультимодальных ответов (текст + действия)
    """
    response: GenerationResult
    metadata: Dict[str, Any] = None
    suggested_actions: List[str] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if self.suggested_actions is None:
            self.suggested_actions = []
