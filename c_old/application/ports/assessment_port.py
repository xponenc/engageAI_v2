# curriculum/application/ports/assessment_port.py
from abc import ABC, abstractmethod

from curriculum.domain.value_objects.assessment_result import AssessmentResult
from curriculum.models.assessment.student_response import StudentTaskResponse
from curriculum.models.content.task import Task


class AssessmentPort(ABC):
    """Порт для оценки ответов студентов"""

    @abstractmethod
    def assess_task(self, task: Task, response: StudentTaskResponse) -> AssessmentResult:
        """Оценка заданий"""
        pass
