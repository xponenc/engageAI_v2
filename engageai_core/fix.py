
import os
import django

# Настраиваем Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'engageai_core.settings')  # Замените на ваш settings модуль
django.setup()

from curriculum.models import Task, StudentTaskResponse
from curriculum.config.dependency_factory import CurriculumServiceFactory

factory = CurriculumServiceFactory()
curriculum_service = factory.create_learning_service()
lesson_assessment_service = curriculum_service.assessment_service

response = StudentTaskResponse.objects.get(pk=198)

assessment = lesson_assessment_service.assess(response)
