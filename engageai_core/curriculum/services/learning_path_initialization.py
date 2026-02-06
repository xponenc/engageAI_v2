from django.utils import timezone

from curriculum.models import LearningObjective
from curriculum.models.learning_process.learning_path import LearningPath
from curriculum.models.content.lesson import Lesson


class LearningPathInitializationService:
    """
    Инициализирует LearningPath при зачислении студента на курс.

    Методологические принципы:
    - Старт НЕ с начала курса
    - Старт с первого урока, содержащего LearningObjective уровня студента
    - Все предыдущие уроки считаются skipped
    - Курс НЕ модифицируется
    """

    @staticmethod
    def initialize_for_enrollment(enrollment) -> LearningPath:
        student = enrollment.student
        course = enrollment.course

        start_cefr = student.english_level
        if start_cefr == "A1":
            start_cefr = "A2"

        print(f"{student.english_level=}")

        # Находим первый урок
        lessons = (
            Lesson.objects
            .filter(
                course=course,
                required_cefr=start_cefr,
                is_active=True,
                is_remedial=False,
            )
            .distinct()
            .order_by("order")
        )

        if not lessons.exists():
            raise RuntimeError(
                f"No Lesson found with LearningObjective for CEFR={start_cefr}"
            )

        first_lesson = lessons.first()
        print(first_lesson)

        # 3. Строим nodes по ВСЕМ урокам курса
        nodes = []
        current_node_index = None

        all_lessons = course.lessons.filter(is_active=True).order_by("order")
        print(lessons)

        for idx, lesson in enumerate(lessons):
            if lesson.order < first_lesson.order:
                status = "skipped"
            elif lesson.id == first_lesson.id:
                status = "in_progress"
                current_node_index = idx
            else:
                status = "locked"

            nodes.append({
                "node_id": f"lesson-{lesson.id}",
                "lesson_id": lesson.id,
                "title": lesson.title,
                "type": "core",
                "status": status,
                "prerequisites": [],
                "triggers": [],
                "created_at": timezone.now().isoformat()
            })

        if current_node_index is None:
            raise RuntimeError("Failed to determine starting node")

        # 4. Создаём LearningPath
        learning_path = LearningPath.objects.create(
            enrollment=enrollment,
            path_type="LINEAR",
            nodes=nodes,
            current_node_index=current_node_index,
            generated_at=timezone.now(),
            metadata={
                "initialized_by": "LearningPathInitializationService",
                "start_cefr": start_cefr,
                "start_lesson_id": first_lesson.id
            }
        )

        return learning_path
