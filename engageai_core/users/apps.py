from django.apps import AppConfig


class AppUsersConfig(AppConfig):
    name = 'users'

    def ready(self):
        import users.signals

