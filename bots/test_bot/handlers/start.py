import json

from aiogram import Router, F, Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, BotCommandScopeChat
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, CommandStart, StateFilter

from dotenv import load_dotenv

from bots.services.utils import get_assistant_slug
from bots.test_bot.config import MAIN_COMMANDS, bot_logger, BOT_NAME, \
    START_EMOJI, GUEST_COMMANDS, CUSTOMER_COMMANDS, MAIN_MENU, GUEST_MENU, CUSTOMER_MENU
from bots.test_bot.services.api_process import auto_context
from bots.test_bot.services.keyboards import reply_start_keyboard
from bots.test_bot.services.sender import reply_and_update_last_message

load_dotenv()

start_router = Router()

class MenuStates(StatesGroup):
    """Статусы состояний меню"""
    registration = State()
    base_test = State()


@start_router.startup()
async def set_menu_button(bot: Bot):
    # await bot.set_my_commands([])
    await bot.set_my_commands(MAIN_MENU + GUEST_MENU)


#
# @start_router.message(CommandStart())
# @start_router.message(StateFilter(None))
# @start_router.message(Command('start'))
# async def start(message: Message, state: FSMContext):
#     """start"""
#     await state.clear()
#     await state.set_state(None)
#
#     data = await state.get_data()
#
#     last_message = data.get("last_message")
#     if last_message:  # Сброс клавиатуры последнего сообщения и отметка о выбранном варианте
#         message_id = last_message.get("id")
#         text = last_message.get("text")
#         text += f"\n\n{START_EMOJI}\tСтартовое меню"
#         try:
#             await message.bot.edit_message_text(
#                 text=text, chat_id=message.chat.id,
#                 message_id=message_id, reply_markup=None,
#                 parse_mode=ParseMode.HTML
#             )
#         except TelegramBadRequest:
#             pass
#     telegram_auth_cache = data.get("telegram_auth_cache", {})
#     user_id = telegram_auth_cache.get("user_id")
#     if user_id:
#         profile = data.get("profile")
#         bot_logger.info(
#             f"[{BOT_NAME}] Access Granted for user with telegram ID {user_id}: {profile} {user_id}")
#
#         await state.set_state(AuthStates.authorized)
#
#         await state.update_data(user_data=profile)
#
#         # await message.bot.set_my_commands([])
#         await message.bot.set_my_commands(MAIN_MENU + CUSTOMER_MENU, scope=BotCommandScopeChat(chat_id=message.chat.id))
#
#         answer_text = (
#             f"Привет, {profile['user_first_name']}!\n\nСтартовое меню\n\n" +
#             "\n\n".join(f'{command.get("name")} - '
#                         f'{command.get("help_text")}'
#                         for command in list(CUSTOMER_COMMANDS.values()) + list(MAIN_COMMANDS.values()))
#         )
#         answer_keyboard = await reply_start_keyboard(
#             items=list(value for value in CUSTOMER_COMMANDS.values()))
#
#     else:
#         bot_logger.info(f"[{BOT_NAME}] Access Granted for user with telegram ID {message.from_user.id}: Anonymous")
#
#         await state.set_state(AuthStates.guest)
#
#         # await message.bot.set_my_commands([])
#         await message.bot.set_my_commands(MAIN_MENU + GUEST_MENU, scope=BotCommandScopeChat(chat_id=message.chat.id))
#
#         answer_text = (
#                 f"Привет, {message.chat.first_name or message.chat.username or message.chat.id or 'Anonymous'}\n\n"
#                 f"Стартовое меню\n\n" +
#                 "\n\n".join(f'{command.get("name")} - {command.get("help_text")}'
#                           for command in list(GUEST_COMMANDS.values()) + list(MAIN_COMMANDS.values()))
#         )
#
#         answer_keyboard = await reply_start_keyboard(
#             items=list(value for value in GUEST_COMMANDS.values()))
#
#     answer_message = await message.answer(answer_text, parse_mode=ParseMode.HTML, reply_markup=answer_keyboard)
#
#     await state.update_data(last_message={
#         "id": answer_message.message_id,
#         "text": answer_text,
#         "keyboard": answer_keyboard.model_dump_json() if answer_keyboard else None
#     })


@start_router.message(CommandStart())
# @start_router.message(StateFilter(None))
@start_router.message(Command('start'))
@auto_context()
async def start(message: Message, state: FSMContext, **kwargs):
    """start"""
    await state.clear()  # TODO временная заглушка сносящая все состояния при старте
    await state.set_state(None)

    data = await state.get_data()
    telegram_auth_cache = data.get("telegram_auth_cache", {})
    core_user_id = telegram_auth_cache.get("core_user_id")

    if core_user_id:
        # Авторизованный пользователь
        profile = data.get("profile")

        bot_logger.info(
            f"[{BOT_NAME}] Access Granted for user with telegram ID {message.from_user.id}: {profile} {core_user_id}"
        )

        await message.bot.set_my_commands(
            MAIN_MENU + CUSTOMER_MENU,
            scope=BotCommandScopeChat(chat_id=message.chat.id)
        )

        answer_text = (
                f"Привет, {profile['user_first_name']}!\n\nСтартовое меню\n\n"
                + "\n\n".join(f"{command['name']} - {command['help_text']}" for command in
                              list(CUSTOMER_COMMANDS.values()) + list(MAIN_COMMANDS.values()))
        )

        answer_keyboard = await reply_start_keyboard(
            items=[v for v in CUSTOMER_COMMANDS.values()]
        )

    else:
        # Гость
        bot_logger.info(
            f"[{BOT_NAME}] Access Granted for user with telegram ID {message.from_user.id}: Anonymous"
        )

        await message.bot.set_my_commands(
            MAIN_MENU + GUEST_MENU,
            scope=BotCommandScopeChat(chat_id=message.chat.id)
        )
        data = await state.get_data()
        bot_logger.info(f"{data=}")

        answer_text = (
                f"Привет, {message.chat.first_name or message.chat.username or message.chat.id or 'Anonymous'}\n\n"
                f"Стартовое меню\n\n"
                + "\n\n".join(f"{command['name']} - {command['help_text']}" for command in
                              list(GUEST_COMMANDS.values()) + list(MAIN_COMMANDS.values()))
        )

        answer_keyboard = await reply_start_keyboard(
            items=[v for v in GUEST_COMMANDS.values()]
        )

    assistant_slug = get_assistant_slug(message.bot)
    last_message_update_text = f"\n\n{START_EMOJI}\tСтартовое меню"
    await reply_and_update_last_message(
        event=message,
        state=state,
        last_message_update_text=last_message_update_text,
        answer_text=answer_text,
        answer_keyboard=answer_keyboard,
        assistant_slug=assistant_slug,
    )
