import inspect
from typing import Union

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, BotCommandScopeChat, CallbackQuery, Update, InlineKeyboardMarkup, \
    InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from bots.services.utils import get_assistant_slug
from bots.test_bot.config import bot_logger, BOT_NAME, MAIN_MENU, GUEST_MENU, CUSTOMER_MENU, \
    CUSTOMER_COMMANDS, MAIN_COMMANDS, START_EMOJI, GUEST_COMMANDS, YES_EMOJI, NO_EMOJI
from bots.test_bot.filters.require_auth import AuthFilter
from bots.test_bot.handlers.start import MenuStates
from bots.test_bot.services.api_process import core_post, auto_context
from bots.test_bot.services.keyboards import reply_start_keyboard
from bots.test_bot.services.sender import reply_and_update_last_message

registration_router = Router()

bot_tag = f"[Bot:{BOT_NAME}]"


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


async def process_cancel_registration_by_command(event: Union[Message, CallbackQuery], state: FSMContext, **kwargs):
    """
    Ловим любую команду во время теста,
    очищаем состояние и повторно отправляем апдейт в диспетчер.
    """
    # if isinstance(event, CallbackQuery):
    #     msg = event.message
    #     update = Update(update_id=0, callback_query=event)
    # else:  # Message
    #     msg = event
    #     update = Update(update_id=0, message=event)
    #
    # command = msg.text
    #
    # data = await state.get_data()
    # last_message = data.get("last_message")
    #
    # if last_message:  # Сброс клавиатуры последнего сообщения и отметка о выбранном варианте
    #     message_id = last_message.get("id")
    #     text = last_message.get("text")
    #     text += f"\n\n{NO_EMOJI}\t Отменено"
    #     try:
    #         await msg.bot.edit_message_text(
    #             text=text, chat_id=msg.chat.id,
    #             message_id=message_id, reply_markup=None,
    #             parse_mode=ParseMode.HTML
    #         )
    #     except TelegramBadRequest:
    #         pass
    #
    # await state.clear()
    #
    # answer_text = (
    #     f"Регистрация прервана командой {command}. "
    #     "Вы можете начать её снова с помощью команды /registration."
    # )
    # answer_keyboard = None
    # answer_message = await msg.answer(
    #     text=answer_text, parse_mode=ParseMode.HTML, reply_markup=answer_keyboard
    # )
    #
    # await state.update_data(last_message={
    #     "id": answer_message.message_id,
    #     "text": answer_text,
    #     "keyboard": None
    # })
    #
    # # отправляем апдейт снова в общий роутинг aiogram
    # await state.set_state(None)
    # dp = msg.bot.dispatcher
    # await dp.feed_update(msg.bot, update)

    if isinstance(event, CallbackQuery):
        message = event.message
        bot = event.message.bot
        update = Update(update_id=0, callback_query=event)
    else:  # Message
        message = event
        bot = event.bot
        update = Update(update_id=0, message=event)

    command = message.text
    assistant_slug = get_assistant_slug(bot)
    last_message_update_text = f"\n\n{NO_EMOJI}\t Отменено"
    answer_text = f"Регистрация прервана командой {command}. Вы можете повторить позже."

    await state.set_state(None)
    await state.update_data(
        current_ai_response={}
    )

    await reply_and_update_last_message(
        event=event,
        state=state,
        last_message_update_text=last_message_update_text,
        answer_text=answer_text,
        current_ai_response=None,
        assistant_slug=assistant_slug,
    )

    # отправляем апдейт снова в общий роутинг aiogram
    dp = bot.dispatcher
    await dp.feed_update(bot, update)


@registration_router.message(Command("registration"))
async def start_registration(message: Message, state: FSMContext):
    await process_start_registration(
        event=message,
        state=state)


@registration_router.callback_query(F.data == GUEST_COMMANDS["registration"]["callback_data"])
async def start_registration_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await process_start_registration(callback, state)


async def process_start_registration(event: Union[Message, CallbackQuery], state: FSMContext, **kwargs):
    """
    Пользователь запускает регистрацию.
    Бот просит ввести код с сайта.
    """
    await state.set_state(MenuStates.registration)

    if isinstance(event, CallbackQuery):
        bot = event.message.bot
    else:  # Message
        bot = event.bot

    last_message_update_text = f"\n\n{YES_EMOJI}\t Регистрация"
    assistant_slug = get_assistant_slug(bot)
    answer_text = "Пожалуйста, введите код регистрации, который вы получили на сайте:"

    await reply_and_update_last_message(
        event=event,
        state=state,
        last_message_update_text=last_message_update_text,
        answer_text=answer_text,
        answer_keyboard=None,
        current_ai_response=None,
        assistant_slug=assistant_slug,
    )


@registration_router.message(StateFilter(MenuStates.registration))
@auto_context()
async def receive_registration_code(message: Message, state: FSMContext, **kwargs):
    """Получаем invite код пользователя и отправляем на backend."""
    context = kwargs.get("context", {})
    user_telegram_id = context["user_telegram_id"]
    assistant_slug = get_assistant_slug(message.bot)

    payload = {
        "user_telegram_id": user_telegram_id,
        "telegram_username": message.from_user.username,
        "telegram_username_first_name": message.from_user.first_name,
        "telegram_username_last_name": message.from_user.last_name,
        "registration_code": message.text.strip()
    }

    ok, response = await core_post(
        url="/accounts/api/v1/users/register_tg/",
        payload=payload,
        context=context
    )

    if not ok:
        bot_logger.error(f"{bot_tag} Ошибка при регистрации пользователя telegram_id={user_telegram_id}: {response}")

        # await message.bot.set_my_commands(MAIN_MENU + GUEST_MENU, scope=BotCommandScopeChat(chat_id=message.chat.id))
        answer_text = "Хьюстон, у нас проблема...попробуй еще раз попозже, мы уже все чиним"
        last_message_update_text = f"\n\n{NO_EMOJI}\t Код не получен"

        await reply_and_update_last_message(
            event=message,
            state=state,
            last_message_update_text=last_message_update_text,
            answer_text=answer_text,
            answer_keyboard=None,
            current_ai_response=None,
            assistant_slug=assistant_slug,
        )
        await state.set_state(None)
        await state.update_data(
            assessment_test={},
            current_ai_response={}
        )
        return

    profile = response.get("profile")

    await state.update_data(
        profile=profile,
        current_ai_response={}
    )

    if not profile:
        personal_account_url = response.get("personal_account_url")
        answer_text = ("Похоже я не смог найти такой ключ. Проверь еще ключ "
                       "в личном кабинете и попробуй еще раз")
        answer_keyboard = None
        if personal_account_url:
            answer_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🗝️ Личный кабинет",
                            url=personal_account_url
                        )
                    ],
                ]
            )

        last_message_update_text = f"\n\n{NO_EMOJI}\t Регистрация отклонена"
        await reply_and_update_last_message(
            event=message,
            state=state,
            last_message_update_text=last_message_update_text,
            answer_text=answer_text,
            answer_keyboard=answer_keyboard,
            current_ai_response=None,
            assistant_slug=assistant_slug,
        )
        await state.update_data(
            profile={},
            current_ai_response={}
        )
        return

    bot_logger.info(f"[{BOT_NAME}] Привязан аккаунт для telegram ID {user_telegram_id}:\n\t{profile} ")

    # await message.bot.set_my_commands([])
    # await message.bot.set_my_commands(MAIN_MENU + CUSTOMER_MENU, scope=BotCommandScopeChat(chat_id=message.chat.id))

    answer_text = (f"Привет, {profile['user_first_name']}\n\nСтартовое меню\n\n"
                   + "\n\n".join(f'{command.get("name")} - {command.get("help_text")}'
                                 for command in (list(MAIN_COMMANDS.values()) + list(CUSTOMER_COMMANDS.values()))))
    answer_keyboard = await reply_start_keyboard(
        items=list(value for value in CUSTOMER_COMMANDS.values()))

    last_message_update_text = f"\n\n{YES_EMOJI}\t Код принят"
    await reply_and_update_last_message(
        event=message,
        state=state,
        last_message_update_text=last_message_update_text,
        answer_text=answer_text,
        answer_keyboard=answer_keyboard,
        current_ai_response=None,
        assistant_slug=assistant_slug,
    )
