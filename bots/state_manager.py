class BotStateManager:
    """Менеджер состояния для ботов, доступный везде в приложении"""
    _bots = {}

    @classmethod
    def set_bots(cls, bots: dict):
        """Устанавливает состояние ботов"""
        cls._bots = bots.copy()

    @classmethod
    def get_bots(cls) -> dict:
        """Возвращает копию текущего состояния ботов"""
        return cls._bots.copy()

    @classmethod
    def get_bot(cls, bot_name: str) -> dict:
        """Возвращает конкретного бота по имени"""
        return cls._bots.get(bot_name)

    @classmethod
    def clear(cls):
        """Очищает состояние при завершении работы"""
        cls._bots = {}
