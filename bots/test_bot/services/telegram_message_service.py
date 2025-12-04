from typing import Optional
from aiogram.types import Message
from aiogram.fsm.context import FSMContext


class TelegramBotMessageService:
    """
    Сервис для работы с ai_message_id в FSM state бота.

    Хранит текущий ID сообщения, отправленного ботом, чтобы
    можно было привязать его к core и избежать путаницы при следующих сообщениях.
    """

    @staticmethod
    async def clear_ai_message_id(state: FSMContext):
        """
        Удаляет сохранённый ai_message_id из FSM state.
        Нужно вызывать после того, как сообщение успешно сохранено и отправлено,
        чтобы не перепутать его с новым сообщением.
        """
        await state.update_data(ai_message_id=None)

    @staticmethod
    async def set_ai_message_id(state: FSMContext, ai_message_id: int):
        """
        Сохраняет текущий ai_message_id в FSM state для дальнейшего использования.

        Args:
            state: FSMContext
            ai_message_id: ID объекта Message в core, созданного для AI-ответа
        """
        await state.update_data(ai_message_id=ai_message_id)

    @staticmethod
    async def get_ai_message_id(state: FSMContext) -> Optional[int]:
        """
        Получает текущий ai_message_id из FSM state.

        Returns:
            ai_message_id или None, если его нет
        """
        data = await state.get_data()
        return data.get("ai_message_id")
