import yaml
from pathlib import Path


class FeedbackTemplateLoader:
    """
    Загружает и кэширует YAML-шаблоны обратной связи.
    """

    BASE_PATH = Path(__file__).resolve().parent / "templates"

    def load(self, name: str) -> dict:
        path = self.BASE_PATH / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Feedback template not found: {name}")

        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
