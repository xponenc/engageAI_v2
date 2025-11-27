import time
from datetime import datetime
from typing import Dict, Any, List

from engageai_core.ai.repositories import UserRepository


class UserStateManager:
    """
    Менеджер состояния пользователя

    Управляет:
    - Централизованным состоянием пользователя
    - Кэшированием для производительности
    - Синхронизацией между БД и памятью
    - Метриками вовлеченности
    - Историей диалога
    """

    def __init__(self, user_id: str):
        """
        Инициализация менеджера состояния

        Args:
            user_id: Уникальный идентификатор пользователя
        """
        self.user_id = str(user_id)
        self.user_repo = UserRepository()
        self.cache = {}  # Для быстрого доступа к состоянию

    def get_current_state(self) -> Dict[str, Any]:
        """
        Получает текущее состояние пользователя с кэшированием
        """
        # Проверяем кэш
        if self.user_id in self.cache:
            cached_state = self.cache[self.user_id]
            if time.time() - cached_state['timestamp'] < 60:  # Кэш живет 60 секунд
                return cached_state['state']

        # Получаем из БД
        user_profile = self.user_repo.get_profile(self.user_id)

        if not user_profile:
            # Создаем новый профиль для нового пользователя
            user_profile = self.user_repo.create_profile(self.user_id)

        # Формируем состояние из профиля
        state = {
            'user_id': self.user_id,
            'profile': {
                'english_level': user_profile.english_level,
                'learning_goals': user_profile.learning_goals or [],
                'profession': user_profile.profession or '',
                'available_time_per_week': user_profile.available_time_per_week or 180,
                'challenges': user_profile.challenges or []
            },
            'metrics': {
                'engagement_level': user_profile.engagement_level or 5,
                'trust_level': 6,  # Базовый уровень доверия для обучения
                'completion_rate': 0
            },
            'learning_plan': user_profile.learning_path or {},
            'current_lesson': user_profile.current_lesson or 0,
            'history': self._get_conversation_history(),
            'last_interaction': user_profile.updated_at.isoformat() if user_profile.updated_at else datetime.now().isoformat()
        }

        # Сохраняем в кэш
        self.cache[self.user_id] = {
            'state': state,
            'timestamp': time.time()
        }

        return state

    def _get_conversation_history(self) -> List[Dict[str, Any]]:
        """
        Получает историю последних сообщений для контекста

        TODO: Реализация получения истории из БД
        """
        # Для MVP возвращаем пустой список
        return []

    def update_state(self, user_message: str, agent_response: Dict[str, Any]):
        """
        Обновляет состояние пользователя на основе ответа агента
        """
        # Получаем текущее состояние
        current_state = self.get_current_state()

        # Обновляем метрики
        agent_state = agent_response.get('agent_state', {})

        # Обновляем engagement_level
        engagement_change = agent_state.get('engagement_change', 0)
        current_state['metrics']['engagement_level'] = max(1, min(10,
                                                                  current_state['metrics'][
                                                                      'engagement_level'] + engagement_change))

        # Обновляем профиль при наличии новой информации
        if 'estimated_level' in agent_state and agent_state['estimated_level']:
            current_state['profile']['english_level'] = agent_state['estimated_level']

        if 'new_goals' in agent_state:
            current_state['profile']['learning_goals'] = list(set(
                current_state['profile']['learning_goals'] + agent_state['new_goals']
            ))

        if 'profession' in agent_state:
            current_state['profile']['profession'] = agent_state['profession']

        if 'available_time' in agent_state:
            current_state['profile']['available_time_per_week'] = agent_state['available_time']

        if 'challenges' in agent_state:
            current_state['profile']['challenges'] = agent_state['challenges']

        # Обновляем учебный план
        if 'learning_plan' in agent_state:
            current_state['learning_plan'] = {
                'lessons': agent_state['learning_plan'],
                'created_at': datetime.now().isoformat(),
                'estimated_completion': agent_state.get('estimated_completion_time', '2 недели')
            }

        # Добавляем в историю диалога
        current_state['history'].append({
            'timestamp': datetime.now().isoformat(),
            'user_message': user_message,
            'agent_response': agent_response
        })

        # Ограничиваем историю последними 20 сообщениями
        current_state['history'] = current_state['history'][-20:]

        # Обновляем last_interaction
        current_state['last_interaction'] = datetime.now().isoformat()

        # Сохраняем изменения в БД
        self._save_to_database(current_state)

        # Обновляем кэш
        self.cache[self.user_id] = {
            'state': current_state,
            'timestamp': time.time()
        }

    def _save_to_database(self, state: Dict[str, Any]):
        """
        Сохраняет состояние в базу данных
        """
        user_profile = self.user_repo.get_profile(self.user_id)
        if not user_profile:
            user_profile = self.user_repo.create_profile(self.user_id)

        # Обновляем профиль
        profile = state['profile']
        user_profile.english_level = profile.get('english_level')
        user_profile.learning_goals = profile.get('learning_goals', [])
        user_profile.profession = profile.get('profession', '')
        user_profile.available_time_per_week = profile.get('available_time_per_week', 180)
        user_profile.challenges = profile.get('challenges', [])
        user_profile.engagement_level = state['metrics']['engagement_level']

        # Обновляем учебный план
        if 'learning_plan' in state and state['learning_plan']:
            user_profile.learning_path = state['learning_plan']

        # Обновляем текущий урок
        user_profile.current_lesson = state.get('current_lesson', 0)

        # Сохраняем
        user_profile.save()