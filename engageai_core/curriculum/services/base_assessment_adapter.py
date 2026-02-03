from abc import ABC, abstractmethod

from curriculum.models.assessment.assessment_result import AssessmentResult
from curriculum.models.content.task import Task
from curriculum.models.student.student_response import StudentTaskResponse
from utils.setup_logger import setup_logger


class AssessmentPort(ABC):
    """Порт для оценки ответов студентов"""

    logger = setup_logger(name=__file__, log_dir="logs/assessments", log_file="assessment.log")

    @abstractmethod
    def assess_task(self, task: Task, response: StudentTaskResponse) -> AssessmentResult:
        """Оценка заданий"""
        pass
