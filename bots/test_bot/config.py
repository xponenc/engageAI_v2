from pathlib import Path

from aiogram.types import BotCommand
from dotenv import load_dotenv, dotenv_values

from utils.setup_logger import setup_logger

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
BOT_ENV = BASE_DIR / ".env"

bot_config = dotenv_values(BOT_ENV)

BOT_NAME = bot_config.get("BOT_NAME")
BOT_TOKEN = bot_config.get("BOT_TOKEN")
BOT_ASSISTANT_SLUG = bot_config.get("BOT_ASSISTANT_SLUG")

AUTH_CACHE_TTL_SECONDS = 1 * 86400

BOT_INTERNAL_KEY = bot_config.get("BOT_INTERNAL_KEY")
WEBHOOK_FAST_API_IP = bot_config.get("CORE_FAST_API_IP")
WEBHOOK_FAST_API_PORT = bot_config.get("CORE_FAST_API_PORT")
# CORE_API = f"http://{CORE_FAST_API_IP}:{CORE_FAST_API_PORT}"
CORE_API = f"http://127.0.0.1:8000"

# """Иконки"""
TASK_EMOJI = u'\U0001F6E0'
MANAGER_EMOJI = u'\U0001F6DF'
CONSULTATION_EMOJI = u'\U0001F4AC'
STUDY_EMOJI = u'\U0001F393'
YES_EMOJI = u'\U00002705'
NO_EMOJI = u'\U0000274C'
CHECK_EMOJI = u'\U0001F6A9'
QUESTION_EMOJI = u'\U00002754'
EXCLAMATION_EMOJI = u'\U00002757'
RIGHT_ARROW_EMOJI = u'\U000027A1'
LEFT_ARROW_EMOJI = u'\U00002B05'
REPORT_EMOJI = u'\U0001F4C4'
PHOTO_EMOJI = u'\U0001F4F7'
CHANGE_EMOJI = u'\U0001F504'
SALE_EMOJI = u'\U0001F4B0'
STORE_EMOJI = u'\U0001F3F7'
EXCHANGE_EMOJI = u'\U0001F503'
START_EMOJI = u'\U0001F51D'
NODE_EMOJI = u'\U0001F194'
EXPERTISE_EMOJI = u'\U0001F477'
CONTACT_EMOJI = u'\U0001F4CC'
INSTALL_EMOJI = u'\U0001F4E5'
UNINSTALL_EMOJI = u'\U0001F4E4'
SCHEME_EMOJI = u'\U0001F5FA'
TARGET_EMOJI = u'\U0001F3AF'

# Telegram Message Effects
MESSAGE_EFFECT_FIRE = "5104841245755180586"  # Огонь
MESSAGE_EFFECT_LIKE = "5107584321108051014"  # лайк
MESSAGE_EFFECT_DISLIKE = "5104858069142078462"  # дизлайк
MESSAGE_EFFECT_CONFETTI = "5046509860389126442"  # 🎉 Конфетти
MESSAGE_EFFECT_POOP = "5046589136895476101"  # 💩

MAIN_COMMANDS = {
    "start": {
        "name": f"{START_EMOJI} Старт",
        "help_text": f"Начало работы с ботом",
        "callback_data": "START"
    },
}

GUEST_COMMANDS = {
    "base_test": {
        "name": f"{TARGET_EMOJI} Базовый тест на уровень языка",
        "help_text": f"Вы можете пройти вводное тестирование на знание английского языка",
        "callback_data": "BASE_TEST"
    },
    "registration": {
        "name": f"{STUDY_EMOJI} Регистрация",
        "help_text": f"Если вы уже зарегистрировались в личном кабинете нашего сайта, то"
                     f" тут можно привязать к нему ваш телеграм аккаунт",
        "callback_data": "REGISTRATION"
    },

}
CUSTOMER_COMMANDS = {
    "base_test": {
        "name": f"{TARGET_EMOJI} Базовый тест на уровень языка",
        "help_text": f"Вы можете пройти вводное тестирование на знание английского языка",
        "callback_data": "BASE_TEST"
    },
    "study": {
        "name": f"{STUDY_EMOJI} Обучение",
        "help_text": f"Что-то призывающее продолжить учебный процесс",
        "callback_data": "STUDY"
    },

}

MAIN_MENU = [
    BotCommand(command=f'/{key}', description=value.get("name", "")) for key, value in MAIN_COMMANDS.items()]
GUEST_MENU = [
    BotCommand(command=f'/{key}', description=value.get("name", "")) for key, value in GUEST_COMMANDS.items()]
CUSTOMER_MENU = [
    BotCommand(command=f'/{key}', description=value.get("name", "")) for key, value in CUSTOMER_COMMANDS.items()]

bot_logger = setup_logger(name=__file__, log_dir="logs/telegram_bot", log_file="bot.log")
