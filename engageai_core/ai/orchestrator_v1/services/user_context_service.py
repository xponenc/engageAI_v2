# users/services/user_context_service.py
"""
UserContextService: ЕДИНСТВЕННАЯ ТОЧКА ВХОДА для получения контекста пользователя.
Содержит ВСЮ логику получения данных из БД и других источников.
Соответствует ТЗ Задача 2.1: Синхронизация данных через единый сервис.
"""
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from ai.orchestrator_v1.context.user_context import UserContext
from curriculum.services.frustration_analyzer import FrustrationAnalyzer

User = get_user_model()


class UserContextService:
    """
    Сервис получения контекста пользователя.

    Ответственность:
    - Единая точка доступа к данным пользователя
    - Интеграция с разными источниками (БД, аналитика, кэш)
    - Формирование единого контекста для всех агентов

    НЕ ответственность:
    - Хранение данных (это задача UserContext)
    - Бизнес-логика обучения (это задача агентов)
    """

    @classmethod
    async def get_context(cls, user_id: int, user_message: str) -> UserContext:
        """
        Единственная точка входа для получения контекста пользователя.

        Алгоритм:
        1. Получаем данные из БД (User + Student)
        2. Формируем профиль
        3. Добавляем поведенческие сигналы (заглушки для пилота)
        4. Возвращаем чистый контейнер данных

        ВАЖНО: НЕТ зависимостей от несуществующих сервисов!
        """
        # Шаг 1: Получаем пользователя и его профиль
        user = await User.objects.select_related('student').aget(id=user_id)

        # Шаг 2: Формируем базовые данные
        username = user.username
        email = user.email

        # Шаг 3: Данные из профиля студента (если существует)
        cefr_level = None
        profession = None
        confidence_level = 5
        learning_goals = []
        frustration_signals = 0
        is_critically_frustrated = False

        if hasattr(user, 'student') and user.student:
            student = user.student
            cefr_level = student.english_level
            profession = student.profession
            if isinstance(student.learning_goals, list):
                learning_goals = student.learning_goals
            confidence_level = student.confidence_level

            state = await sync_to_async(FrustrationAnalyzer.analyze)(student.id, user_message)

            frustration_signals = state.score  # 0–10
            is_critically_frustrated = state.is_critical

        # Шаг 4: Формируем контекст (чистый контейнер данных)
        return UserContext(
            user_id=user_id,
            username=username,
            email=email,
            cefr_level=cefr_level,
            profession=profession,
            learning_goals=learning_goals,
            frustration_signals=frustration_signals,
            is_critically_frustrated=is_critically_frustrated,
            confidence_level=confidence_level
        )
