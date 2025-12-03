import html
import inspect
from typing import Union

import yaml
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Update
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter

from bots.test_bot.config import MESSAGE_EFFECT_CONFETTI, YES_EMOJI, CUSTOMER_COMMANDS, NO_EMOJI, bot_logger
from bots.test_bot.filters.require_auth import AuthFilter
from bots.test_bot.services.api_process import core_post, auto_context
from bots.test_bot.services.sender import reply_and_update_last_message

assessment_router = Router()


class AssessmentState(StatesGroup):
    waiting_mcq_answer = State()  # Для вопросов с вариантами ответов
    waiting_text_answer = State()  # Для текстовых вопросов


# --- helper для отправки вопроса ---
async def send_question(msg: Message, state: FSMContext, question: dict):
    """
    question = { id, question_text, type, options }
    """
    await state.update_data(question=question)

    question_text = question['text']
    question_number = question['number']
    question_total = question['total_questions']

    if question["type"] != "mcq":
        intro = ""
        text_content = ""
        question_content = question_text
        if "Text:" in question_text and "Question:" in question_text:
            try:
                text_part = question_text.split("Text:")[1]
                intro = question_text.split("Text:")[0]
                text_content = text_part.split("Question:")[0].strip()
                question_content = text_part.split("Question:")[1].strip()
            except IndexError:
                pass

        answer_text = f"<b>Вопрос {question_number} из {question_total}:</b>\n\n"
        answer_text += f"{intro}\n\n" if intro else ""
        answer_text += f"{text_content}\n\n" if text_content else ""
        answer_text += f"{question_content}" if question_content else ""
    else:
        answer_text = (f"<b>Вопрос {question_number} из {question_total}:</b>"
                       f"\n\n{question_text}")
    answer_keyboard = None

    # MCQ
    if question["type"] == "mcq":
        buttons = [
            [InlineKeyboardButton(text=o, callback_data=f"mcq_{index}")]
            for index, o in enumerate(question["options"])
        ]
        answer_keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    answer_message = await msg.answer(
        text=answer_text, parse_mode=ParseMode.HTML, reply_markup=answer_keyboard
    )

    await state.update_data(last_message={
        "id": answer_message.message_id,
        "text": answer_text,
        "keyboard": answer_keyboard.model_dump_json() if answer_keyboard else None
    })


# --- Прерывание теста базовыми командами ---
@assessment_router.message(F.text.startswith("/"), StateFilter(AssessmentState), AuthFilter())
async def cancel_test_by_command(message: Message, state: FSMContext):
    await process_cancel_test_by_command(message, state)


@assessment_router.callback_query(
    ~F.data == CUSTOMER_COMMANDS["base_test"]["callback_data"],
    StateFilter(AssessmentState),
    AuthFilter()
)
async def cancel_test_by_command_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await process_cancel_test_by_command(callback, state)


async def process_cancel_test_by_command(event: Union[Message, CallbackQuery], state: FSMContext):
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
    # answer_text = (
    #     f"Тест прерван командой {command}. Вы можете начать его снова позже."
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

    last_message_update_text = f"\n\n{NO_EMOJI}\t Отменено"
    answer_text = f"Тест прерван командой {command}. Вы можете начать его снова позже."
    await reply_and_update_last_message(
        message=msg,
        state=state,
        last_message_update_text=last_message_update_text,
        answer_text=answer_text ,
    )

    # отправляем апдейт снова в общий роутинг aiogram
    await state.set_state(None)
    dp = msg.bot.dispatcher
    await dp.feed_update(msg.bot, update)


# --- START ASSESSMENT TEST ---
@assessment_router.message(Command("base_test"), AuthFilter())
async def start_assessment_test(message: Message, state: FSMContext):
    await process_start_assessment_test(message, state)


@assessment_router.callback_query(F.data == CUSTOMER_COMMANDS["base_test"]["callback_data"], AuthFilter())
async def start_assessment_test_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await process_start_assessment_test(callback, state)


@auto_context()
async def process_start_assessment_test(event: Union[Message, CallbackQuery], state: FSMContext, **kwargs):
    """
    Запрашиваем backend → стартуем тест → получаем первый вопрос
    - For Message: reply to message
    - For CallbackQuery: reply to callback.message (and answer the callback to remove spinner)
    """
    update_id = getattr(event, "update_id", None)
    if isinstance(event, CallbackQuery):
        tg_user_id = event.from_user.id
        reply_target = event.message

        chat_id = event.message.chat.id
        event_message_id = event.message.message_id
        command = event.data
        event_type = "callback"
    else:  # Message
        tg_user_id = event.from_user.id
        reply_target = event

        chat_id = event.chat.id
        event_message_id = event.message_id
        command = event.text
        event_type = "message"

    context = kwargs.get("context", {})
    bot_logger.info(f"КОНТЕКСТ \n\n{context}")
    context.update({
        "update_id": update_id,
        "user_id": tg_user_id,
        "chat_id": chat_id,
        "message_id": event_message_id,
        "command": command[:100] if command else None,
        "function": "process_start_assessment_test",
        "action": "assessment_start"
    })
    bot_logger.info(f"НОВЫЙ КОНТЕКСТ \n\n{context}")


    data = await state.get_data()

    last_message = data.get("last_message")

    if last_message:  # Сброс клавиатуры последнего сообщения и отметка о выбранном варианте
        message_id = last_message.get("id")
        text = last_message.get("text")
        text += f"\n\n{YES_EMOJI}\t Базовый тест уровня языка"
        try:
            await reply_target.bot.edit_message_text(
                text=text, chat_id=reply_target.chat.id,
                message_id=message_id, reply_markup=None,
                parse_mode=ParseMode.HTML
            )
        except TelegramBadRequest:
            pass

    ok, response = await core_post(
        url="/assessment/api/v1/assessment/start/",
        payload={"telegram_id": tg_user_id},
        context=context
    )

    if not ok:
        answer_text = (
            f"Ошибка при запуске теста. Попробуй позже."
        )
        answer_keyboard = None
        answer_message = await reply_target.answer(answer_text, parse_mode=ParseMode.HTML, reply_markup=answer_keyboard)

        await state.update_data(last_message={
            "id": answer_message.message_id,
            "text": answer_text,
            "keyboard": None
        })
        return

    if response.get("expired_previous"):
        answer_text = (
            f"⚠️ Ваша предыдущая попытка теста истекла. Начинаю новый тест!"
        )
        answer_keyboard = None
        answer_message = await reply_target.answer(
            text=answer_text, parse_mode=ParseMode.HTML, reply_markup=answer_keyboard
        )

        await state.update_data(last_message={
            "id": answer_message.message_id,
            "text": answer_text,
            "keyboard": None
        })

    session_id = response.get("session_id")
    question = response.get("question")

    await state.update_data(session_id=session_id)

    # Устанавливаем состояние в зависимости от типа вопроса
    if question["type"] == "mcq":
        await state.set_state(AssessmentState.waiting_mcq_answer)
    else:
        await state.set_state(AssessmentState.waiting_text_answer)

    await send_question(reply_target, state, question)


# --- MCQ выбор ---
@assessment_router.callback_query(AssessmentState.waiting_mcq_answer, F.data.startswith("mcq_"), AuthFilter())
@auto_context()
async def mcq_answer(callback: CallbackQuery, state: FSMContext, **kwargs):
    await callback.answer()

    update_id = getattr(callback, "update_id", None)
    tg_user_id = callback.from_user.id

    chat_id = callback.message.chat.id
    event_message_id = callback.message.message_id
    command = callback.data
    event_type = "callback"

    # # Автоопределение вызывающей функции
    # try:
    #     caller_frame = inspect.currentframe().f_back
    #     caller_name = caller_frame.f_code.co_name if caller_frame else "unknown"
    #     caller_module = inspect.getmodule(caller_frame).__name__ if caller_frame else "unknown"
    # except Exception:
    #     caller_name = "unknown"
    #     caller_module = "unknown"
    #
    # context = {
    #     "update_id": update_id,
    #     "user_id": tg_user_id,
    #     "chat_id": chat_id,
    #     "message_id": event_message_id,
    #     "event_type": event_type,
    #     "handler": f"{caller_name} ({caller_module})",
    #     "command": command[:100] if command else None,
    #     "function": "process_start_assessment_test",
    #     "action": "assessment_start"
    # }

    # Извлекаем ответ без префикса
    answer_index = callback.data.lstrip("mcq_")

    data = await state.get_data()
    session_id = data["session_id"]
    last_message = data.get("last_message")

    question = data.get("question")
    q_options = question["options"]
    answer = q_options[int(answer_index)]

    if last_message:
        message_id = last_message["id"]
        text = last_message["text"]
        escaped_answer_text = html.escape(answer)
        text += f"\n\n{YES_EMOJI}\tОтвет получен\n\n<blockquote>{escaped_answer_text}</blockquote>"
        try:
            await callback.message.bot.edit_message_text(
                text=text, chat_id=callback.message.chat.id,
                message_id=message_id, reply_markup=None,
                parse_mode=ParseMode.HTML
            )
        except TelegramBadRequest:
            pass

    payload = {
        "session_id": session_id,
        "answer_text": answer,
        "telegram_id": callback.from_user.id,
    }

    ok, response = await core_post(
        url=f"/assessment/api/v1/assessment/session/{session_id}/{question.get('id', ' ')}/answer/",
        payload=payload,
        context=context
    )
    if not ok:
        answer_text = (
            f"Ошибка. Попробуй ещё раз позже."
        )
        answer_keyboard = None
        answer_message = await callback.message.answer(
            text=answer_text, parse_mode=ParseMode.HTML, reply_markup=answer_keyboard
        )

        await state.update_data(last_message={
            "id": answer_message.message_id,
            "text": answer_text,
            "keyboard": None
        })
        return

    # Тест завершён
    if response.get("finished"):
        # Сброс предыдущей клавиатуры
        level = response.get('level')
        view_url = response.get('view_url')

        answer_text = (
            f"🎉 <b>Тест завершён!</b>\n\n"
            f"Ваш уровень английского: <b>{level}</b> 🎯\n\n"
            f"Сейчас AI выполнит анализ и даст полный разбор, рекомендации и ошибки доступны в личном кабинете.\n"
            f"Загляните — это реально полезно 👇\n"
        )

        answer_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📊 Посмотреть подробный результат",
                        url=view_url
                    )
                ],
            ]
        )

        try:
            answer_message = await callback.message.answer(
                text=answer_text,
                parse_mode=ParseMode.HTML,
                reply_markup=answer_keyboard,
                message_effect_id=MESSAGE_EFFECT_CONFETTI
            )
        except TelegramBadRequest:
            answer_message = await callback.message.answer(
                text=answer_text,
                parse_mode=ParseMode.HTML,
                reply_markup=answer_keyboard,
            )

        await state.update_data(last_message={
            "id": answer_message.message_id,
            "text": answer_text,
            "keyboard": answer_keyboard.model_dump_json()
        })
        await state.set_state(None)

        return

    next_question = response.get("next_question")
    if not next_question:  # TODO какое то ошибочное состояние
        answer_text = (
            f"Ошибка. Вопросов больше нет."
        )
        answer_keyboard = None
        answer_message = await callback.message.answer(
            text=answer_text, parse_mode=ParseMode.HTML, reply_markup=answer_keyboard
        )

        await state.update_data(last_message={
            "id": answer_message.message_id,
            "text": answer_text,
            "keyboard": None
        })
        return

    # Устанавливаем новое состояние в зависимости от типа следующего вопроса
    if next_question["type"] == "mcq":
        await state.set_state(AssessmentState.waiting_mcq_answer)
    else:
        await state.set_state(AssessmentState.waiting_text_answer)

    await send_question(callback.message, state, next_question)


# --- Обработчик текста во время MCQ вопроса -> мы не ждем текст, мы ждем callback ---
@assessment_router.message(AssessmentState.waiting_mcq_answer, AuthFilter())
async def handle_text_during_mcq(message: Message, state: FSMContext):
    data = await state.get_data()
    last_message = data.get("last_message")

    if last_message:
        message_id = last_message["id"]
        text = last_message["text"]
        text += f"\n\n{NO_EMOJI}\tНеправильный выбор"
        keyboard = None
        try:
            await message.bot.edit_message_text(
                text=text, chat_id=message.chat.id,
                message_id=message_id, reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
        except TelegramBadRequest:
            pass

        answer_text = (
            f"<b>Пожалуйста, выберите вариант ответа, нажав на соответствующую кнопку под вопросом.</b>\n\n{text}"
        )
        answer_keyboard = InlineKeyboardMarkup.from_json(keyboard)

    else:
        answer_text = (
            f"<b>Пожалуйста, выберите вариант ответа, нажав на соответствующую кнопку под вопросом.</b>"
        )
        answer_keyboard = None

    answer_message = await message.answer(
        text=answer_text, parse_mode=ParseMode.HTML, reply_markup=answer_keyboard
    )

    await state.update_data(last_message={
        "id": answer_message.message_id,
        "text": answer_text,
        "keyboard": answer_keyboard
    })


# --- Обработчик callback во время текстового вопроса -> мы ждем текст ---
@assessment_router.callback_query(AssessmentState.waiting_text_answer, AuthFilter())
async def handle_callback_during_text_answer(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    last_message = data.get("last_message")

    if last_message:
        message_id = last_message["id"]
        text = last_message["text"]
        text += f"\n\n{NO_EMOJI}\tНеправильный выбор"
        keyboard = None
        try:
            await callback.message.bot.edit_message_text(
                text=text, chat_id=callback.message.chat.id,
                message_id=message_id, reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
        except TelegramBadRequest:
            pass

        answer_text = (
            f"<b>Пожалуйста ответьте на задание текстом</b>\n\n{text}"
        )
        answer_keyboard = InlineKeyboardMarkup.from_json(keyboard)

    else:
        answer_text = (
            f"<b>Пожалуйста ответьте на задание текстом</b>"
        )
        answer_keyboard = None

    answer_message = await callback.message.answer(
        text=answer_text, parse_mode=ParseMode.HTML, reply_markup=answer_keyboard
    )

    await state.update_data(last_message={
        "id": answer_message.message_id,
        "text": answer_text,
        "keyboard": answer_keyboard
    })


# --- Текстовый ответ ---
@assessment_router.message(AssessmentState.waiting_text_answer, AuthFilter())
@auto_context()
async def process_text_answer(message: Message, state: FSMContext, **kwargs):
    # update_id = getattr(message, "update_id", None)
    # tg_user_id = message.from_user.id
    #
    # chat_id = message.chat.id
    # event_message_id = message.message_id
    # command = message.text
    # event_type = "message"
    #
    # # context = kwargs.get("context", {})
    # # bot_logger.warning(f"process_text_answer context:\n"
    # #                  f"{yaml.dump(context, allow_unicode=True, default_flow_style=False)}")

    data = await state.get_data()
    session_id = data["session_id"]
    question = data["question"]
    last_message = data.get("last_message")

    if last_message:
        message_id = last_message["id"]
        text = last_message["text"]
        escaped_answer_text = html.escape(message.text)
        text += f"\n\n{YES_EMOJI}\tОтвет получен\n\n<blockquote>{escaped_answer_text}</blockquote>"

        try:
            await message.bot.edit_message_text(
                text=text, chat_id=message.chat.id,
                message_id=message_id, reply_markup=None,
                parse_mode=ParseMode.HTML
            )
        except TelegramBadRequest:
            pass

    payload = {
        "session_id": session_id,
        "answer_text": message.text,
        "telegram_id": message.from_user.id
    }

    ok, response = await core_post(
        url=f"/assessment/api/v1/assessment/session/{session_id}/{question['id']}/answer/",
        payload=payload,
        # context=context
    )

    if not ok:
        answer_text = (
            f"Ошибка. Попробуй ещё раз позже."
        )
        answer_keyboard = None
        answer_message = await message.answer(
            text=answer_text, parse_mode=ParseMode.HTML, reply_markup=answer_keyboard
        )

        await state.update_data(last_message={
            "id": answer_message.message_id,
            "text": answer_text,
            "keyboard": None
        })
        return

    # Тест завершён
    if response.get("finished"):
        # Сброс предыдущей клавиатуры
        level = response.get('level')
        view_url = response.get('view_url')

        answer_text = (
            f"🎉 <b>Тест завершён!</b>\n\n"
            f"Ваш уровень английского: <b>{level}</b> 🎯\n\n"
            f"Сейчас AI выполнит анализ и даст полный разбор, рекомендации и ошибки доступны в личном кабинете.\n"
            f"Загляните — это реально полезно 👇\n"
        )

        answer_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📊 Посмотреть подробный результат",
                        url=view_url
                    )
                ],
            ]
        )

        try:
            answer_message = await message.answer(
                text=answer_text,
                parse_mode=ParseMode.HTML,
                reply_markup=answer_keyboard,
                message_effect_id=MESSAGE_EFFECT_CONFETTI
            )
        except TelegramBadRequest:
            answer_message = await message.answer(
                text=answer_text,
                parse_mode=ParseMode.HTML,
                reply_markup=answer_keyboard,
            )

        await state.update_data(last_message={
            "id": answer_message.message_id,
            "text": answer_text,
            "keyboard": answer_keyboard.model_dump_json()
        })
        await state.set_state(None)

        return

    next_question = response.get("next_question")
    if not next_question:  # TODO какое то ошибочное состояние
        answer_text = (
            f"Ошибка. Вопросов больше нет."
        )
        answer_keyboard = None
        answer_message = await message.answer(
            text=answer_text, parse_mode=ParseMode.HTML, reply_markup=answer_keyboard
        )

        await state.update_data(last_message={
            "id": answer_message.message_id,
            "text": answer_text,
            "keyboard": None
        })
        return

    # Устанавливаем новое состояние в зависимости от типа следующего вопроса
    if next_question["type"] == "mcq":
        await state.set_state(AssessmentState.waiting_mcq_answer)
    else:
        await state.set_state(AssessmentState.waiting_text_answer)

    await send_question(message, state, next_question)
