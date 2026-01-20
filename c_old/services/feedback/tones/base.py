class BaseTone:
    """
    Базовый интерфейс эмоционального тона.
    """

    def praise(self) -> str:
        raise NotImplementedError

    def support(self) -> str:
        raise NotImplementedError

    def retry(self) -> str:
        raise NotImplementedError

    def neutral(self) -> str:
        return "Продолжаем обучение."
