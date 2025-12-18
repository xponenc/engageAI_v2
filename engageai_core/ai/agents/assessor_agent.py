from typing import Any

from curriculum.models import Task, StudentTaskResponse


class AutoAssessor:
    """
    Automatic assessor for closed tasks.
    """

    def assess(self, task: Task, response: StudentTaskResponse) -> bool:
        content = task.content
        answer = response.response_text

        if task.response_format == "single_choice":
            return self._assess_single_choice(content, answer)

        if task.response_format == "multiple_choice":
            return self._assess_multiple_choice(content, answer)

        if task.response_format == "short_text":
            return self._assess_short_text(content, answer)

        raise ValueError(
            f"Auto assessment not supported for response_format={task.response_format}"
        )

    # ------------------------------------------------------------------

    def _assess_single_choice(self, content: dict, answer: Any) -> bool:
        """
        answer expected: index (int) or stringified int
        """
        try:
            return int(answer) == int(content["correct_idx"])
        except (KeyError, ValueError, TypeError):
            return False

    def _assess_multiple_choice(self, content: dict, answer: Any) -> bool:
        """
        answer expected: list of indices or comma-separated string
        """
        try:
            expected = set(content["correct_idx"])
            actual = set(map(int, answer))
            return actual == expected
        except Exception:
            return False

    def _assess_short_text(self, content: dict, answer: str) -> bool:
        correct = content.get("correct", [])
        case_sensitive = content.get("case_sensitive", False)

        if not case_sensitive:
            answer = answer.lower()
            correct = [c.lower() for c in correct]

        return answer.strip() in correct
