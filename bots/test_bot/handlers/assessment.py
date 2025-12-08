import html
from typing import Union

import yaml
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Update
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter

from bots.services.utils import get_assistant_slug
from bots.test_bot.config import YES_EMOJI, CUSTOMER_COMMANDS, NO_EMOJI, bot_logger, BOT_NAME
from bots.test_bot.filters.require_auth import AuthFilter
from bots.test_bot.services.api_process import core_post, auto_context
from bots.test_bot.services.sender import reply_and_update_last_message

assessment_router = Router()

bot_tag = f"[Bot:{BOT_NAME}]"


class AssessmentState(StatesGroup):
    waiting_mcq_answer = State()  # Для вопросов с вариантами ответов
    waiting_text_answer = State()  # Для текстовых вопросов


# --- helper для отправки вопроса ---
async def send_question(
        event: Union[Message, CallbackQuery],
        state: FSMContext,
        session_message: str = None,
        last_message_update_text: str = None,
):
    """
    question = { id, question_text, type, options }
    """

    if isinstance(event, CallbackQuery):
        bot = event.message.bot
    else:
        bot = event.bot

    assistant_slug = get_assistant_slug(bot)

    data = await state.get_data()
    assessment_test_data = data.get("assessment_test")
    question = assessment_test_data.get("question")

    question_text = question['text']
    question_number = question['number']
    question_total = question['total_questions']

    current_ai_response = data.get("current_ai_response")

    answer_text = session_message if session_message else ""
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
        answer_text += f"<b>Вопрос {question_number} из {question_total}:</b>\n\n"
        answer_text += f"{intro}\n\n" if intro else ""
        answer_text += f"{text_content}\n\n" if text_content else ""
        answer_text += f"{question_content}" if question_content else ""
    else:
        answer_text += (f"<b>Вопрос {question_number} из {question_total}:</b>"
                       f"\n\n{question_text}")

    answer_keyboard = None
    if question["type"] == "mcq":
        buttons = [
            [InlineKeyboardButton(text=o, callback_data=f"mcq_{index}")]
            for index, o in enumerate(question["options"])
        ]
        answer_keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await reply_and_update_last_message(
        event=event,
        state=state,
        last_message_update_text=last_message_update_text,
        answer_text=answer_text,
        answer_keyboard=answer_keyboard,
        current_ai_response=current_ai_response,
        assistant_slug=assistant_slug,
    )


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
    assistant_slug = get_assistant_slug(msg.bot)
    last_message_update_text = f"\n\n{NO_EMOJI}\t Отменено"
    answer_text = f"Тест прерван командой {command}. Вы можете начать его снова позже."

    await state.set_state(None)
    await state.update_data(
        assessment_test={},
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

    # Определяем тип события и получаем необходимые данные
    if isinstance(event, CallbackQuery):
        reply_target = event.message
        await event.answer()  # Отвечаем на callback
    else:  # Message
        reply_target = event

    # bot_logger.warning(f"process_start_assessment_test event:\n"
    #                    f"{yaml.dump(event.model_dump(), allow_unicode=True, default_flow_style=False)}")

    context = kwargs.get("context", {})

    # bot_logger.warning(f"process_start_assessment_test context:\n"
    #                    f"{yaml.dump(context, allow_unicode=True, default_flow_style=False)}")

    user_telegram_id = context["user_telegram_id"]

    last_message_update_text = f"\n\n{YES_EMOJI}\t Базовый тест уровня языка"
    assistant_slug = get_assistant_slug(reply_target.bot)

    ok, response = await core_post(
        url="/assessment/api/v1/assessment/start/",
        payload={"user_telegram_id": user_telegram_id},
        context=context
    )

    if not ok:
        bot_logger.error(f"{bot_tag} Ошибка при запуске теста {response}")
        answer_text = f"Хьюстон, у нас проблема... Ошибка при запуске теста. Попробуй позже."
        await reply_and_update_last_message(
            event=event,
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

    session_expired = response.get("expired_previous", False)
    session_id = response.get("session_id")
    question = response.get("question")
    core_answer = response.get("core_answer")

    await state.update_data(
        assessment_test={
            "session_id": session_id,
            "session_expired": session_expired,
            "question": question,
        },
        current_ai_response=core_answer,
    )

    session_message = "<i>Время отведенное на предыдущий тест завершилось.</i>\n\n" if session_expired else ""

    question_number = question.get("number")
    if question_number == 1:
        session_message += ("<b>Мы начинаем новую сессию, отвечайте спокойно и что-то подбадривающее"
                            " и мотивирующее...</b>\n\n")

    # Устанавливаем состояние в зависимости от типа вопроса
    if question["type"] == "mcq":
        await state.set_state(AssessmentState.waiting_mcq_answer)
    else:
        await state.set_state(AssessmentState.waiting_text_answer)

    # Отправляем первый вопрос
    await send_question(
        event=event,
        state=state,
        last_message_update_text=last_message_update_text,
        session_message=session_message,
    )


# --- MCQ выбор ---
@assessment_router.callback_query(AssessmentState.waiting_mcq_answer, F.data.startswith("mcq_"), AuthFilter())
@auto_context()
async def mcq_answer(callback: CallbackQuery, state: FSMContext, **kwargs):
    await callback.answer()
    print("\n\n\n\nMCQ ANSWER\n\n\n\n\n\n")


    bot_logger.info(f"mcq_answer Структура event при получении: {type(callback)}")
    bot_logger.info(f"callback: {yaml.dump(callback.model_dump(), default_flow_style=False)}")


    assistant_slug = get_assistant_slug(callback.message.bot)

    # Извлекаем ответ пользователя из callback без префикса
    answer_index = callback.data.lstrip("mcq_")

    data = await state.get_data()
    assessment_test_data = data.get("assessment_test")

    session_id = assessment_test_data["session_id"]

    question = assessment_test_data.get("question")
    question_id = question["id"]
    q_options = question["options"]

    answer = q_options[int(answer_index)]

    escaped_answer_text = html.escape(answer)
    last_message_update_text = f"\n\n{YES_EMOJI}\tОтвет получен\n\n<blockquote>{escaped_answer_text}</blockquote>"

    context = kwargs.get("context", {})  # получение контекста от auto_context

    payload = {
        "session_id": session_id,
        "answer_text": answer,
    }

    ok, response = await core_post(
        url=f"/assessment/api/v1/assessment/session/{session_id}/{question_id}/answer/",
        payload=payload,
        context=context
    )



    if not ok:
        bot_logger.error(f"{bot_tag} Ошибка при обработке ответа на вопроса id={question_id}"
                         f" в TestSession id={session_id}")
        answer_text = f"Хьюстон, у нас проблема... Тест остановлен, попробуй ещё раз позже."
        last_message_update_text = f"\n\n{NO_EMOJI}\tОтвет не получен\n"
        await reply_and_update_last_message(
            event=callback,
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

    session_expired = response.get("expired_previous", False)
    session_id = response.get("session_id")
    core_answer = response.get("core_answer")
    next_question = response.get("question")

    await state.update_data(
        assessment_test={
            "session_id": session_id,
            "session_expired": session_expired,
            "question": next_question,
        },
        current_ai_response=core_answer,
    )

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

        await reply_and_update_last_message(
            event=callback,
            state=state,
            last_message_update_text=last_message_update_text,
            answer_text=answer_text,
            answer_keyboard=answer_keyboard,
            current_ai_response=core_answer,
            assistant_slug=assistant_slug,
        )
        await state.set_state(None)
        await state.update_data(
            assessment_test={},
            current_ai_response={}
        )
        return

    if not next_question:
        bot_logger.error(f"{bot_tag} Ошибка при получении вопроса в TestSession id={session_id}\n"
                         f"Ответ сервера:\n\t{ok}\n\t{response}")
        answer_text = f"Хьюстон, у нас проблема... Тест остановлен, попробуй ещё раз позже."
        last_message_update_text = f"\n\n{NO_EMOJI}\tОтвет не получен\n"
        await reply_and_update_last_message(
            event=callback,
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

    # Устанавливаем новое состояние в зависимости от типа следующего вопроса
    if next_question["type"] == "mcq":
        await state.set_state(AssessmentState.waiting_mcq_answer)
    else:
        await state.set_state(AssessmentState.waiting_text_answer)

    await send_question(
        event=callback,
        state=state,
        last_message_update_text=last_message_update_text,
    )


# --- Обработчик текста во время MCQ вопроса -> мы не ждем текст, мы ждем callback ---
@assessment_router.message(AssessmentState.waiting_mcq_answer, AuthFilter())
async def handle_text_during_mcq(message: Message, state: FSMContext):
    session_message = f"<b>Пожалуйста, выберите вариант ответа, нажав на соответствующую кнопку под вопросом.</b> \n\n"
    last_message_update_text = f"\n\n{NO_EMOJI}\tНеправильный выбор"

    await state.update_data(
        current_ai_response={}
    )

    await send_question(
        event=message,
        state=state,
        last_message_update_text=last_message_update_text,
        session_message=session_message,
    )


# --- Обработчик callback во время текстового вопроса -> мы ждем текст ---
@assessment_router.callback_query(AssessmentState.waiting_text_answer, AuthFilter())
async def handle_callback_during_text_answer(callback: CallbackQuery, state: FSMContext):
    session_message = f"<b>Пожалуйста ответьте на задание текстом</b>\n\n"
    last_message_update_text = f"\n\n{NO_EMOJI}\tНеправильный выбор"

    await state.update_data(
        current_ai_response={}
    )

    await send_question(
        event=callback,
        state=state,
        last_message_update_text=last_message_update_text,
        session_message=session_message,
    )


# --- Текстовый ответ ---
@assessment_router.message(AssessmentState.waiting_text_answer, AuthFilter())
@auto_context()
async def process_text_answer(message: Message, state: FSMContext, **kwargs):
    assistant_slug = get_assistant_slug(message.bot)

    data = await state.get_data()
    assessment_test_data = data.get("assessment_test")

    session_id = assessment_test_data["session_id"]

    question = assessment_test_data.get("question")
    question_id = question["id"]

    escaped_answer_text = html.escape(message.text)
    last_message_update_text = f"\n\n{YES_EMOJI}\tОтвет получен\n\n<blockquote>{escaped_answer_text}</blockquote>"

    context = kwargs.get("context", {})  # получение контекста от auto_context
    payload = {
        "session_id": session_id,
        "question_id": question_id,
        "answer_text": message.text,
    }

    ok, response = await core_post(
        url=f"/assessment/api/v1/assessment/session/{session_id}/{question['id']}/answer/",
        payload=payload,
        context=context
    )

    if not ok:
        bot_logger.error(f"{bot_tag} Ошибка при получении вопроса в TestSession id={session_id}\n"
                         f"Ответ сервера:\n\t{ok}\n\t{response}")
        answer_text = f"Хьюстон, у нас проблема... Тест остановлен, попробуй ещё раз позже."
        last_message_update_text = f"\n\n{NO_EMOJI}\tОтвет не получен\n"
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

    session_expired = response.get("expired_previous", False)
    session_id = response.get("session_id")
    core_answer = response.get("core_answer")
    next_question = response.get("question")

    await state.update_data(
        assessment_test={
            "session_id": session_id,
            "session_expired": session_expired,
            "question": next_question,
        },
        current_ai_response=core_answer
    )

    # Тест завершён
    if response.get("finished"):
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

        await reply_and_update_last_message(
            event=message,
            state=state,
            last_message_update_text=last_message_update_text,
            answer_text=answer_text,
            answer_keyboard=answer_keyboard,
            current_ai_response=core_answer,
            assistant_slug=assistant_slug,
        )
        await state.set_state(None)
        await state.update_data(
            assessment_test={},
            current_ai_response={}
        )
        return

    if not next_question:
        bot_logger.error(f"{bot_tag} Ошибка при получении вопроса в TestSession id={session_id}\n"
                         f"Ответ сервера:\n\t{ok}\n\t{response}")
        answer_text = f"Хьюстон, у нас проблема... Тест остановлен, попробуй ещё раз позже."
        last_message_update_text = f"\n\n{NO_EMOJI}\tОтвет не получен\n"
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

    # Устанавливаем новое состояние в зависимости от типа следующего вопроса
    if next_question["type"] == "mcq":
        await state.set_state(AssessmentState.waiting_mcq_answer)
    else:
        await state.set_state(AssessmentState.waiting_text_answer)

    await send_question(
        event=message,
        state=state,
        last_message_update_text=last_message_update_text,
    )
