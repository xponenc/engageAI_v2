import inspect
from typing import Union

from aiogram import Router, F, Dispatcher
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, BotCommandScopeChat, CallbackQuery, Update
from aiogram.fsm.context import FSMContext

from bots.bots_engine import BOTS
from bots.test_bot.config import bot_logger, BOT_NAME, MAIN_MENU, GUEST_MENU, CUSTOMER_MENU, \
    CUSTOMER_COMMANDS, MAIN_COMMANDS, START_EMOJI, GUEST_COMMANDS, YES_EMOJI, NO_EMOJI
from bots.test_bot.filters.require_auth import AuthFilter
from bots.test_bot.handlers.start import MenuStates, AuthStates
from bots.test_bot.services.api_process import core_post
from bots.test_bot.services.keyboards import reply_start_keyboard

registration_router = Router()


# --- Прерывание регистрации базовыми командами ---
@registration_router.message(F.text.startswith("/"), StateFilter(MenuStates.registration), AuthFilter())
async def cancel_test_by_command(message: Message, state: FSMContext):
    await process_cancel_registration_by_command(message, state)


@registration_router.callback_query(
    ~F.data == GUEST_COMMANDS["registration"]["callback_data"],
    StateFilter(MenuStates.registration),
    AuthFilter()
)
async def cancel_test_by_command_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await process_cancel_registration_by_command(callback, state)


async def process_cancel_registration_by_command(event: Union[Message, CallbackQuery], state: FSMContext):
    """
    Ловим любую команду во время теста,
    очищаем состояние и повторно отправляем апдейт в диспетчер.
    """
    if isinstance(event, CallbackQuery):
        msg = event.message
        update = Update(update_id=0, callback_query=event)
    else:  # Message
        msg = event
        update = Update(update_id=0, message=event)

    command = msg.text

    data = await state.get_data()
    last_message = data.get("last_message")

    if last_message:  # Сброс клавиатуры последнего сообщения и отметка о выбранном варианте
        message_id = last_message.get("id")
        text = last_message.get("text")
        text += f"\n\n{NO_EMOJI}\t Отменено"
        try:
            await msg.bot.edit_message_text(
                text=text, chat_id=msg.chat.id,
                message_id=message_id, reply_markup=None,
                parse_mode=ParseMode.HTML
            )
        except TelegramBadRequest:
            pass

    await state.clear()

    answer_text = (
        f"Регистрация прервана командой {command}. "
        "Вы можете начать её снова с помощью команды /registration."
    )
    answer_keyboard = None
    answer_message = await msg.answer(
        text=answer_text, parse_mode=ParseMode.HTML, reply_markup=answer_keyboard
    )

    await state.update_data(last_message={
        "id": answer_message.message_id,
        "text": answer_text,
        "keyboard": None
    })

    # отправляем апдейт снова в общий роутинг aiogram
    await state.set_state(None)
    dp = msg.bot.dispatcher
    await dp.feed_update(msg.bot, update)


@registration_router.message(Command("registration"))
async def start_registration(message: Message, state: FSMContext):
    await process_start_registration(message, state)


@registration_router.callback_query(F.data == GUEST_COMMANDS["registration"]["callback_data"])
async def start_registration_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await process_start_registration(callback.message, state)


async def process_start_registration(message: Message, state: FSMContext):
    """
    Пользователь запускает регистрацию.
    Бот просит ввести код с сайта.
    """
    data = await state.get_data()
    last_message = data.get("last_message")

    if last_message:  # Сброс клавиатуры последнего сообщения и отметка о выбранном варианте
        message_id = last_message.get("id")
        text = last_message.get("text")
        text += f"\n\n{YES_EMOJI}\t Регистрация"
        try:
            await message.bot.edit_message_text(
                text=text, chat_id=message.chat.id,
                message_id=message_id, reply_markup=None,
                parse_mode=ParseMode.HTML
            )
        except TelegramBadRequest:
            pass

    await state.set_state(MenuStates.registration)

    answer_text = "Пожалуйста, введите код регистрации, который вы получили на сайте:"
    answer_keyboard = None
    answer_message = await message.answer(
        text=answer_text, parse_mode=ParseMode.HTML, reply_markup=answer_keyboard
    )

    await state.update_data(last_message={
        "id": answer_message.message_id,
        "text": answer_text,
        "keyboard": None
    })


@registration_router.message(StateFilter(MenuStates.registration))
async def receive_registration_code(message: Message, state: FSMContext):
    """Получаем invite код пользователя и отправляем на backend."""
    update_id = getattr(message, "update_id", None)
    tg_user_id = message.from_user.id

    chat_id = message.chat.id
    event_message_id = message.message_id
    command = message.text
    event_type = "message"

    # Автоопределение вызывающей функции
    try:
        caller_frame = inspect.currentframe().f_back
        caller_name = caller_frame.f_code.co_name if caller_frame else "unknown"
        caller_module = inspect.getmodule(caller_frame).__name__ if caller_frame else "unknown"
    except Exception:
        caller_name = "unknown"
        caller_module = "unknown"

    context = {
        "update_id": update_id,
        "user_id": tg_user_id,
        "chat_id": chat_id,
        "message_id": event_message_id,
        "event_type": event_type,
        "handler": f"{caller_name} ({caller_module})",
        "command": command[:100] if command else None,
        "function": "process_start_assessment_test",
        "action": "assessment_start"
    }

    data = await state.get_data()
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

    payload = {
        "telegram_id": tg_user_id,
        "telegram_username": message.from_user.username,
        "registration_code": message.text.strip()
    }

    tg_user_id = message.from_user.id
    ok, response = await core_post(
        url="/accounts/api/v1/users/register_tg/",
        payload=payload,
        context=context
    )

    if not ok:
        answer_text = "Хьюстон, у нас проблема...попробуй еще раз попозже, мы уже все чиним"
        answer_keyboard = None
        answer_message = await message.answer(answer_text, parse_mode=ParseMode.HTML, reply_markup=answer_keyboard)

        await message.bot.set_my_commands(MAIN_MENU + GUEST_MENU, scope=BotCommandScopeChat(chat_id=message.chat.id))

        await state.update_data(last_message={
            "id": answer_message.message_id,
            "text": answer_text,
            "keyboard": None
        })
        return

    core_user_id = response.get("user_id")
    if not core_user_id:
        answer_text = ("Похоже я не смог найти такой ключ. Проверь еще раз ключ "
                       "в личном кабинете и попробуй еще раз")
        answer_keyboard = None
        answer_message = await message.answer(
            text=answer_text, parse_mode=ParseMode.HTML, reply_markup=answer_keyboard
        )

        await message.bot.set_my_commands(MAIN_MENU + GUEST_MENU, scope=BotCommandScopeChat(chat_id=message.chat.id))

        await state.update_data(last_message={
            "id": answer_message.message_id,
            "text": answer_text,
            "keyboard": None
        })
        return

    profile = response.get("profile")
    bot_logger.info(f"[{BOT_NAME}] Привязан аккаунт telegram для telegram ID {tg_user_id}: {profile} {core_user_id}")

    await state.update_data(user_data=profile)

    # await message.bot.set_my_commands([])
    await message.bot.set_my_commands(MAIN_MENU + CUSTOMER_MENU, scope=BotCommandScopeChat(chat_id=message.chat.id))

    answer_text = (f"Привет, {profile['user_first_name']}\n\nСтартовое меню\n\n"
                   + "\n\n".join(f'{command.get("name")} - {command.get("help_text")}'
                                 for command in (list(MAIN_COMMANDS.values()) + list(CUSTOMER_COMMANDS.values()))))
    answer_keyboard = await reply_start_keyboard(
        items=list(value for value in CUSTOMER_COMMANDS.values()))
    answer_message = await message.answer(
        text=answer_text, parse_mode=ParseMode.HTML, reply_markup=answer_keyboard
    )

    await state.update_data(last_message={
        "id": answer_message.message_id,
        "text": answer_text,
        "keyboard": answer_keyboard.model_dump_json()
    })
