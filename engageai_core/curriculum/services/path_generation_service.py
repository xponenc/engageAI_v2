import json
from django.utils import timezone
from curriculum.models.learning_process.learning_path import LearningPath
from curriculum.models.content.lesson import Lesson
from users.models import CEFRLevel


# from curriculum.services.llm_gateway import LLMGateway  # Наш абстрактный гейтвей для GPT/Mistral


class PathGenerationService:
    """
    Сервис генерации и регенерации персонализированного учебного пути.
    Вызывается:
    - При первом зачислении (PERSONALIZED режим)
    - При значительном изменении профиля (цели, профессия, уровень)
    - Периодически (еженедельно) для корректировки по SkillDelta
    """

    @staticmethod
    def generate_personalized_path(enrollment):
        student = enrollment.student
        course = enrollment.course

        # Собираем контекст для LLM
        context = {
            "student_level": student.english_level,
            "learning_goals": student.learning_goals,
            "profession": student.profession,
            "professional_context": student.professional_context,
            "available_time_per_week_min": student.available_time_per_week or 180,
            "current_skills": PathGenerationService._get_current_skills(enrollment),
            "skill_trends": PathGenerationService._get_skill_trends(enrollment),
            "course_lessons": PathGenerationService._get_available_lessons(course, student.english_level),
        }

        prompt = f"""
Ты — эксперт по адаптивному обучению английскому языку.
Сгенерируй оптимальный персонализированный учебный путь для студента.

Контекст студента:
- Уровень CEFR: {context['student_level']}
- Цели обучения: {', '.join(context['learning_goals'])}
- Профессия: {context['profession'] or 'общая'}
- Профессиональный контекст: {context['professional_context'] or 'не указан'}
- Доступное время в неделю: {context['available_time_per_week_min']} минут
- Текущие навыки (0.0–1.0): {context['current_skills']}
- Тренды прогресса (delta за последние уроки): {context['skill_trends']}

Доступные уроки курса (id, title, level, skill_focus, estimated_minutes):
{json.dumps(context['course_lessons'], ensure_ascii=False, indent=2)}

Требования к пути:
1. Учитывай уровень, цели и профессию — приоритет урокам с релевантными примерами (IT, business и т.д.)
2. Начинай с уроков подходящего уровня, постепенно повышай сложность
3. Учитывай слабые навыки (низкие значения или отрицательные delta) — добавь дополнительные уроки
4. Соблюдай лимит времени: ~{context['available_time_per_week_min'] // 60} часов в неделю → 3–5 уроков
5. Добавляй remedial уроки при необходимости
6. Формат ответа — строго валидный JSON список узлов:

[
  {{
    "lesson_id": 12,
    "title": "Present Simple in IT Context",
    "reason": "Базовая грамматика + профессиональные примеры",
    "estimated_minutes": 25,
    "type": "core" | "remedial" | "practice"
  }},
  ...
]

Верни ТОЛЬКО JSON массив, без объяснений.
"""

        response = LLMGateway.call(
            model="gpt-4o-mini",  # или "mistral-large" при смене
            prompt=prompt,
            temperature=0.3,
            max_tokens=2000
        )

        try:
            nodes_raw = json.loads(response)
            nodes = []
            for idx, node in enumerate(nodes_raw):
                lesson = Lesson.objects.get(id=node["lesson_id"])
                nodes.append({
                    "node_id": idx + 1,
                    "lesson_id": lesson.id,
                    "title": node.get("title", lesson.title),
                    "reason": node.get("reason", ""),
                    "estimated_minutes": node.get("estimated_minutes", lesson.estimated_time),
                    "type": node.get("type", "core"),
                    "prerequisites": [],
                    "triggers": [],
                    "status": "in_progress" if idx == 0 else "locked"
                })

            # Создаём или обновляем путь
            path, created = LearningPath.objects.update_or_create(
                enrollment=enrollment,
                defaults={
                    "path_type": "PERSONALIZED",
                    "nodes": nodes,
                    "current_node_index": 0,
                    "generated_at": timezone.now(),
                    "metadata": {
                        "generated_by": "gpt-4o-mini",
                        "context_summary": context,
                        "prompt_version": "v2"
                    }
                }
            )
            return path

        except Exception as e:
            # Fallback на линейный путь при ошибке LLM
            return PathGenerationService.generate_linear_fallback(enrollment)

    @staticmethod
    def _get_current_skills(enrollment):
        latest = enrollment.skill_snapshots.order_by("-snapshot_at").first()
        return latest.skills if latest else {}

    @staticmethod
    def _get_skill_trends(enrollment):
        deltas = enrollment.skill_deltas.order_by("-calculated_at")[:5]
        return [d.deltas for d in deltas]

    @staticmethod
    def _get_available_lessons(course, level):
        next_level = PathGenerationService._get_next_cefr_level(level)

        lessons = course.lessons.filter(
            is_active=True,
            required_cefr__in=[level, next_level]  # ← здесь required_cefr, а не level
        )

        return [
            {
                "id": l.id,
                "title": l.title,
                "level": l.required_cefr,  # ← required_cefr, а не level
                "skill_focus": l.skill_focus,
                "estimated_minutes": l.duration_minutes or 25
            }
            for l in lessons
        ]


    @staticmethod
    def generate_linear_fallback(enrollment):
        """
        Резервная генерация линейного пути, если AI-генерация провалилась.
        - Берёт все активные уроки курса, подходящие уровню студента + следующий уровень.
        - Приоритизирует уроки по слабым навыкам (из последнего SkillSnapshot < 0.6).
        - Устанавливает статус: completed/in_progress/locked на основе истории.
        - Возвращает обновлённый LearningPath.
        """
        student = enrollment.student
        course = enrollment.course

        # Получаем уроки, подходящие уровню + следующий (для прогресса)
        level = student.english_level

        next_level = PathGenerationService._get_next_cefr_level(student.english_level)

        lessons = course.lessons.filter(
            is_active=True,
            required_cefr__in=[level, next_level]
        ).order_by("order")

        # Приоритизация по слабым навыкам (если есть snapshot)
        latest_snapshot = enrollment.skill_snapshots.order_by("-snapshot_at").first()
        if latest_snapshot:
            weak_skills = [skill for skill, value in latest_snapshot.skills.items() if value < 0.6]
            if weak_skills:
                # Перемещаем уроки с фокусом на слабые навыки вперёд
                prioritized_lessons = lessons.filter(skill_focus__overlap=weak_skills).order_by("order")
                other_lessons = lessons.exclude(id__in=prioritized_lessons.values_list("id", flat=True))
                lessons = list(prioritized_lessons) + list(other_lessons)

        # Строим nodes
        nodes = []
        completed_count = 0  # Для определения статуса на основе истории (можно расширить по LessonEventLog)
        for idx, lesson in enumerate(lessons):
            status = "locked"
            if idx == 0:  # Первый — всегда in_progress для новых
                status = "in_progress"
            elif completed_count < idx:  # Простая эвристика; заменить на реальный прогресс из LessonEventLog
                status = "locked"
            else:
                status = "completed"
                completed_count += 1

            nodes.append({
                "node_id": idx + 1,
                "lesson_id": lesson.id,
                "title": lesson.title,
                "reason": f"Линейный шаг: фокус на {lesson.skill_focus}",
                "estimated_minutes": lesson.duration_minutes or 30,
                "type": "core",
                "prerequisites": [idx] if idx > 0 else [],  # Простая цепочка
                "triggers": [],  # Нет адаптации в fallback
                "status": status
            })

        # Обновляем путь
        path, _ = LearningPath.objects.update_or_create(
            enrollment=enrollment,
            defaults={
                "path_type": "LINEAR",
                "nodes": nodes,
                "current_node_index": completed_count,  # Начать с первого unlocked
                "generated_at": timezone.now(),
                "metadata": {"generated_by": "fallback_linear", "reason": "AI unavailable"}
            }
        )
        return path

    @staticmethod
    def _get_next_cefr_level(current_level: str) -> str:
        """
        Использует централизованное перечисление CEFRLevel для последовательности A1 → A2 → ... → C2.
        """
        levels_order = [choice.value for choice in CEFRLevel]
        try:
            current_index = levels_order.index(current_level)
            next_index = min(current_index + 1, len(levels_order) - 1)
            return levels_order[next_index]
        except ValueError:
            return CEFRLevel.A1.value  # Fallback на начальный уровень
