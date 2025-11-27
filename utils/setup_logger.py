"""
logger_setup.py

Утилита для создания и настройки логгера с ротацией файлов и выводом в консоль.
Поддерживает:
- Защиту от дублирования хендлеров
- Гибкие уровни логирования
- Безопасные пути
- Подробную документацию
- Цветной вывод в консоль (опционально, через colorlog)
"""

import os
import logging
from logging.handlers import RotatingFileHandler

# Попытка импортировать colorlog — если нет, работаем без цвета
try:
    from colorlog import ColoredFormatter
    HAS_COLORLOG = True
except ImportError:  # pragma: no cover
    HAS_COLORLOG = False


def setup_logger(
    name: str,
    log_dir: str = "logs",
    log_file: str = "debug.log",
    *,
    logger_level: int = logging.DEBUG,
    file_level: int = logging.DEBUG,
    console_level: int = logging.INFO,
    propagate: bool = False,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 3,
    use_color: bool = True
) -> logging.Logger:
    """
    Создаёт и настраивает логгер с ротацией файла и выводом в консоль.

    **Защита от повторной инициализации**: хендлеры добавляются только если их ещё нет.

    Args:
        name (str): Имя логгера. Рекомендуется ``__name__`` для иерархии модулей.
        log_dir (str, optional): Папка для логов. **Относительно текущей рабочей директории**.
                                 По умолчанию — ``"logs"``.
        log_file (str, optional): Имя файла лога. По умолчанию — ``"debug.log"``.

        logger_level (int, optional): Уровень логгера (фильтрует все сообщения).
                                      По умолчанию — ``logging.DEBUG``.
        file_level (int, optional): Уровень записи в файл. По умолчанию — ``logging.DEBUG``.
        console_level (int, optional): Уровень вывода в консоль. По умолчанию — ``logging.INFO``.

        propagate (bool, optional): Передавать ли сообщения родительскому логгеру.
                                    По умолчанию — ``False`` (чтобы не дублировать в root).
        max_bytes (int, optional): Максимальный размер файла до ротации.
                                   По умолчанию — 5 МБ.
        backup_count (int, optional): Количество резервных копий. По умолчанию — 3.
        use_color (bool, optional): Использовать цветной вывод в консоль (требует ``colorlog``).
                                    По умолчанию — ``True``. Если ``colorlog`` не установлен — игнорируется.

    Returns:
        logging.Logger: Настроенный логгер.

    Example:
        >>> logger = setup_logger(__name__, log_dir="logs/gateway", log_file="gateway.log")
        >>> logger.info("Gateway запущен")
    """
    logger = logging.getLogger(name)

    # Защита от повторной инициализации
    if logger.handlers:
        return logger

    logger.setLevel(logger_level)
    logger.propagate = propagate

    # Форматтер для файла (всегда чёрно-белый)
    file_formatter = logging.Formatter(
        "%(asctime)s [%(name)s:%(module)s:%(lineno)d] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Форматтер для консоли (с цветом или без)
    if use_color and HAS_COLORLOG:
        console_formatter = ColoredFormatter(
            "%(log_color)s%(asctime)s [%(name)s:%(module)s:%(lineno)d] [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'red,bg_white',
            },
            secondary_log_colors={},
            style='%'
        )
    else:
        console_formatter = logging.Formatter(
            "%(asctime)s [%(name)s:%(module)s:%(lineno)d] [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S"
        )

    # Путь к лог-файлу
    project_root = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    log_dir_abs = os.path.join(project_root, log_dir)
    os.makedirs(log_dir_abs, exist_ok=True)
    log_path = os.path.join(log_dir_abs, log_file)

    # Файловый хендлер
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8"
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Консольный хендлер
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    return logger