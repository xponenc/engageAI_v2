import time

from aiogram.fsm.context import FSMContext

from bots.test_bot.config import AUTH_CACHE_TTL_SECONDS


async def is_user_authorized(state: FSMContext) -> bool:
    """Проверяет авторизацию через кэш в FSM состоянии"""
    state_data = await state.get_data()
    cache = state_data.get("telegram_auth_cache", {})
    now = int(time.time())
    return (
        cache.get("core_user_id") is not None and
        now - cache.get("checked_at", 0) < AUTH_CACHE_TTL_SECONDS
    )