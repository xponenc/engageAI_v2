import json

from aiogram import Router, F, Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, BotCommandScopeChat
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, CommandStart, StateFilter

from dotenv import load_dotenv

from bots.test_bot.config import MAIN_COMMANDS, bot_logger, BOT_NAME, \
    START_EMOJI, GUEST_COMMANDS, CUSTOMER_COMMANDS, MAIN_MENU, GUEST_MENU, CUSTOMER_MENU
from bots.test_bot.services.keyboards import reply_start_keyboard

load_dotenv()

start_router = Router()


class AuthStates(StatesGroup):
    """Статусы состояний пользователя"""
    authorized = State()
    guest = State()


class MenuStates(StatesGroup):
    """Статусы состояний меню"""
    registration = State()
    base_test = State()


@start_router.startup()
async def set_menu_button(bot: Bot):
    # await bot.set_my_commands([])
    await bot.set_my_commands(MAIN_MENU + GUEST_MENU)


@start_router.message(CommandStart())
@start_router.message(StateFilter(None))
@start_router.message(Command('start'))
async def start(message: Message, state: FSMContext):
    """start"""
    # await state.update_data(user_data={})
    await state.set_state(None)

    await state.clear()

    data = await state.get_data()
    await message.answer(json.dumps(data))
    print(f"start data= {data}")
    bot_logger.info(
        f"[{BOT_NAME}] start data= {data}")
    last_message = data.get("last_message")
    if last_message:  # Сброс клавиатуры последнего сообщения и отметка о выбранном варианте
        message_id = last_message.get("id")
        text = last_message.get("text")
        text += f"\n\n{START_EMOJI}\tСтартовое меню"
        try:
            await message.bot.edit_message_text(
                text=text, chat_id=message.chat.id,
                message_id=message_id, reply_markup=None,
                parse_mode=ParseMode.HTML
            )
        except TelegramBadRequest:
            pass
    telegram_auth_cache = data.get("telegram_auth_cache", {})
    user_id = telegram_auth_cache.get("user_id")
    if user_id:
        profile = data.get("profile")
        bot_logger.info(
            f"[{BOT_NAME}] Access Granted for user with telegram ID {user_id}: {profile} {user_id}")

        await state.set_state(AuthStates.authorized)

        await state.update_data(user_data=profile)

        # await message.bot.set_my_commands([])
        await message.bot.set_my_commands(MAIN_MENU + CUSTOMER_MENU, scope=BotCommandScopeChat(chat_id=message.chat.id))

        answer_text = (
            f"Привет, {profile['user_first_name']}!\n\nСтартовое меню\n\n" +
            "\n\n".join(f'{command.get("name")} - '
                        f'{command.get("help_text")}'
                        for command in list(CUSTOMER_COMMANDS.values()) + list(MAIN_COMMANDS.values()))
        )
        answer_keyboard = await reply_start_keyboard(
            items=list(value for value in CUSTOMER_COMMANDS.values()))

    else:
        bot_logger.info(f"[{BOT_NAME}] Access Granted for user with telegram ID {message.from_user.id}: Anonymous")

        await state.set_state(AuthStates.guest)

        # await message.bot.set_my_commands([])
        await message.bot.set_my_commands(MAIN_MENU + GUEST_MENU, scope=BotCommandScopeChat(chat_id=message.chat.id))

        answer_text = (
                f"Привет, {message.chat.first_name or message.chat.username or message.chat.id or 'Anonymous'}\n\n"
                f"Стартовое меню\n\n" +
                "\n\n".join(f'{command.get("name")} - {command.get("help_text")}'
                          for command in list(GUEST_COMMANDS.values()) + list(MAIN_COMMANDS.values()))
        )

        answer_keyboard = await reply_start_keyboard(
            items=list(value for value in GUEST_COMMANDS.values()))

    answer_message = await message.answer(answer_text, parse_mode=ParseMode.HTML, reply_markup=answer_keyboard)

    await state.update_data(last_message={
        "id": answer_message.message_id,
        "text": answer_text,
        "keyboard": answer_keyboard.model_dump_json()
    })
