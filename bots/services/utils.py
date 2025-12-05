def get_assistant_slug(bot) -> str:
    """Получает assistant_slug из бота или конфига"""
    assistant_slug = getattr(bot, "assistant_slug", None)
    if not assistant_slug:
        from bots.test_bot.config import BOT_ASSISTANT_SLUG
        assistant_slug = BOT_ASSISTANT_SLUG
    return assistant_slug