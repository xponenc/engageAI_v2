from abc import ABC, abstractmethod

from curriculum.models.assessment.assessment_result import AssessmentResult
from curriculum.models.content.task import Task
from curriculum.models.student.student_response import StudentTaskResponse


class AssessmentPort(ABC):
    """Порт для оценки ответов студентов"""

    @abstractmethod
    def assess_task(self, task: Task, response: StudentTaskResponse) -> AssessmentResult:
        """Оценка заданий"""
        pass
