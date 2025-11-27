from django.contrib.auth.models import Group
from django.core.management import BaseCommand


class Command(BaseCommand):
    help = "Создает тестовые блоги и посты для всех пользователей"

    def handle(self, *args, **options):
        self.stdout.write("Create base Groups")
        group_names = ["Обычный пользователь", "Верифицированный пользователь", "Модератор"]
        for name in group_names:
            group, created = Group.objects.get_or_create(name=name)
            if created:
                self.stdout.write(f"Group {name} created")
            else:
                self.stdout.write(f"Group {name} exist")
