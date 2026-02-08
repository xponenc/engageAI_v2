from celery import shared_task

from assessment.models import TestAnswer
from curriculum.services.auto_assessment_adapter import AutoAssessorAdapter
from curriculum.services.llm_assessment_adapter import LLMAssessmentAdapter


@shared_task(bind=True)
def evaluate_answer_to_test_task(
        self,
        test_answer_id: int,
        user_id: int,
        test_session_id: int
):
    """Оценка задания для тестовой сессии"""
    test_answer = TestAnswer.objects.select_related("question__session", "question__task").get(id=test_answer_id)
    test_question = test_answer.question
    task = test_question.task

    auto_adapter = AutoAssessorAdapter()
    llm_adapter = LLMAssessmentAdapter()

    try:
        print(test_answer)
        if task.response_format in AutoAssessorAdapter.SUPPORTED_FORMATS:
            result = auto_adapter.assess_task(task, test_answer)
        else:
            result = llm_adapter.assess_task(task, test_answer)
        print(result)
        test_answer.ai_feedback = {
            "task_id": result.task_id,
            "is_correct": result.is_correct,
            "cefr_target": result.cefr_target,
            "skill_evaluation": result.skill_evaluation,
            "summary": result.summary,
            "error_tags": result.error_tags,
            "metadata": result.metadata,
        }
        test_answer.evaluation_status = "success"

    except Exception:
        test_answer.evaluation_status = "failed"
        raise
    finally:
        test_answer.save()
