from django.apps import AppConfig


class CurriculumConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'curriculum'

    def ready(self):
        """
        Регистрируем сигналы и импортируем модули при загрузке приложения.
        """
        # Импортируем models для регистрации в Django
        import curriculum.models
