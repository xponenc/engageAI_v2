from utils.setup_logger import setup_logger


class BaseService:
    """Базовый класс для всех сервисных классов"""

    def __init__(self):
        self.logger = setup_logger(
            name=f"{__name__}.{self.__class__.__name__}",
            log_dir="logs/core_services",
            log_file=f"{self.__class__.__name__.lower()}.log"
        )

    @staticmethod
    def _prepare_error_response(detail: str, status_code: int) -> dict:
        """Универсальный метод подготовки ответа об ошибке"""
        return {
            "payload": {"detail": detail},
            "response_status": status_code
        }