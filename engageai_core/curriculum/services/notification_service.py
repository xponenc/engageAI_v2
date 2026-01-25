import logging

logger = logging.getLogger(__name__)


class NotificationService:
    @staticmethod
    def send_adaptive_nudge(student, path):
        logger.info(f"Nudge для {student}: путь адаптирован. Проверьте новые уроки.")
        # В будущем: Telegram-бот, email, push
        # bot.send_message(student.telegram_id, f"Ваш путь обновлён! Добавлен remedial урок по {weak_skill}")
