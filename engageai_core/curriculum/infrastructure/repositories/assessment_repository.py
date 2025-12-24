# curriculum/infrastructure/repositories/assessment_repository.py
from django.utils import timezone

from curriculum.domain.value_objects.assessment_result import AssessmentResult
from curriculum.models.assessment.assessment import Assessment


class AssessmentRepository:
    @staticmethod
    def from_domain(assessment_result: AssessmentResult, task, enrollment):
        """Создает Django-модель из доменного объекта"""
        return Assessment(
            task=task,
            enrollment=enrollment,
            score=assessment_result.score,
            is_correct=assessment_result.is_correct,
            grade=assessment_result.grade.value,
            error_tags=assessment_result.error_tags,
            feedback=assessment_result.feedback,
            confidence=assessment_result.confidence,
            assessed_at=timezone.now()
        )

    @staticmethod
    def to_domain(assessment: Assessment) -> AssessmentResult:
        """Конвертирует Django-модель в доменный объект"""
        return AssessmentResult(
            score=assessment.score,
            is_correct=assessment.is_correct,
            error_tags=assessment.error_tags or [],
            feedback=assessment.feedback or {},
            confidence=assessment.confidence or 1.0
        )