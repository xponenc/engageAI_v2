# curriculum/infrastructure/rule_engine/rule_engine.py
from curriculum.domain.value_objects.assessment_result import AssessmentResult


class RuleEngine:
    """
    Движок правил для автоматической оценки.
    Обеспечивает гибкость в стратегиях оценки без изменения основной логики.
    """

    def evaluate_mcq_v2(self, task, response):
        """Оценка MCQ версии 2 (множественный выбор)"""
        try:
            # Логика оценки для MCQ v2
            student_choices = [int(i) for i in response.response_text.split(",")]
            correct_ids = task.content["correct_ids"]
            correct_count = sum(1 for c in student_choices if c in correct_ids)
            total_correct = len(correct_ids)

            score = correct_count / total_correct
            is_correct = (correct_count == total_correct)

            return AssessmentResult(
                score=score,
                is_correct=is_correct,
                error_tags=["partial_understanding"] if not is_correct and correct_count > 0 else [],
                feedback={
                    "correct_count": correct_count,
                    "total_correct": total_correct
                }
            )
        except Exception as e:
            return AssessmentResult(
                score=0.0,
                is_correct=False,
                error_tags=["invalid_format"],
                feedback={"error": f"Ошибка обработки: {str(e)}"}
            )

    def evaluate_short_text(self, task, response):
        """Оценка кратких текстовых ответов"""
        student_answer = response.response_text.strip().lower()
        correct_answers = [ans.lower() for ans in task.content.get("correct", [])]
        case_sensitive = task.content.get("case_sensitive", False)

        # Если регистр важен, используем оригинальные значения
        if case_sensitive:
            student_answer = response.response_text.strip()
            correct_answers = task.content.get("correct", [])

        # Простая проверка на совпадение
        is_correct = any(self._fuzzy_match(student_answer, correct) for correct in correct_answers)
        score = 1.0 if is_correct else 0.0

        return AssessmentResult(
            score=score,
            is_correct=is_correct,
            error_tags=[] if is_correct else ["concept_mismatch"],
            feedback={
                "hint": "Верный ответ!" if is_correct else "Попробуйте ещё раз"
            }
        )

    def _fuzzy_match(self, answer, correct_answer, threshold=0.8):
        """
        Простая fuzzy-проверка для неточных совпадений
        """
        # В реальной системе здесь будет более сложная логика
        return answer.strip() == correct_answer.strip()

    def evaluate_default(self, task, response):
        """Стратегия оценки по умолчанию"""
        return AssessmentResult(
            score=0.5,
            feedback={"message": "Ответ получен. Оценка будет произведена позже."},
            confidence=0.3
        )