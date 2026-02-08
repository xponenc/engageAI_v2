from django.utils import timezone
from curriculum.models.student.skill_snapshot import SkillSnapshot
from curriculum.models.student.skill_delta import SkillDelta


class SkillUpdateService:
    """
    Сервис обновления навыков студента после завершения урока.
    Создаёт POST_LESSON snapshot и delta.
    Вызывается автоматически после события COMPLETE.
    """

    # Настройки сглаживания
    SMOOTHING_ALPHA = 0.7  # Коэффициент сглаживания (0.0–1.0)

    @staticmethod
    def calculate_and_save_delta(enrollment, lesson):
        """
        Основной метод: расчёт и сохранение delta после урока.
        Возвращает созданный SkillDelta или None при ошибке.
        """
        # 1. Получаем самый свежий POST_LESSON snapshot (он должен быть создан после оценки)
        post_snapshot = SkillSnapshot.objects.filter(
            enrollment=enrollment,
            associated_lesson=lesson,
            snapshot_context="POST_LESSON"
        ).order_by('-snapshot_at').first()

        if not post_snapshot:
            # Если snapshot не создан (оценка ещё не завершена) — выходим
            return None

        # 2. Находим предыдущий снимок (любой самый свежий до текущего)
        pre_snapshot = SkillSnapshot.objects.filter(
            enrollment=enrollment,
            snapshot_at__lt=post_snapshot.snapshot_at
        ).order_by('-snapshot_at').first()

        # Если нет предыдущего — это первый урок, delta не считаем
        if not pre_snapshot:
            return None

        # 3. Расчёт delta
        deltas = {}
        all_skills = set(pre_snapshot.skills.keys()) | set(post_snapshot.skills.keys())

        for skill in all_skills:
            pre_val = pre_snapshot.skills.get(skill, 0.0)
            post_val = post_snapshot.skills.get(skill, 0.0)
            deltas[skill] = round(post_val - pre_val, 3)

        if deltas:
            deltas['overall'] = round(sum(deltas.values()) / len(deltas), 3)

        # 4. Сохранение delta
        delta_obj, created = SkillDelta.objects.update_or_create(
            student=enrollment.student,
            lesson=lesson,
            defaults={
                'enrollment': enrollment,
                'pre_snapshot': pre_snapshot,
                'post_snapshot': post_snapshot,
                'deltas': deltas,
                'metadata': {
                    'duration_min': post_snapshot.metadata.get('duration_min'),
                    'lesson_score': post_snapshot.metadata.get('lesson_score', 0.0),
                    'calculated_at': timezone.now().isoformat()
                }
            }
        )

        # 5. (Опционально) Обновление engagement_level студента
        if deltas.get('overall', 0) > 0:
            student = enrollment.student
            student.engagement_level = min(10, student.engagement_level + 1)
            student.save(update_fields=['engagement_level'])

        return delta_obj

    @classmethod
    def calculate_skill_deltas(
            cls,
            pre_snapshot: 'SkillSnapshot',
            lesson_feedback: dict
    ) -> dict:
        """
        Рассчитывает изменение навыков после урока.

        Использует экспоненциальное сглаживание:
        new_value = alpha * lesson_score + (1 - alpha) * prev_value

        где:
        - alpha = 0.7 — скорость адаптации (высокая = быстрое обучение)
        - lesson_score — оценка навыка в текущем уроке
        - prev_value — предыдущее значение навыка

        alpha = 0.7 означает:
            70% нового значения берется из текущего урока
            30% сохраняется от предыдущего значения

        Рекомендуемые значения alpha:
        - 0.3–0.5: консервативное (медленное обучение, стабильные оценки)
        - 0.6–0.8: сбалансированное (рекомендуется для большинства случаев)
        - 0.9–1.0: агрессивное (быстрое обучение, но может быть нестабильным)
        """
        if not pre_snapshot:
            # Нет предыдущего снимка — используем оценки урока как базовые
            return {
                skill: data["score"] if data else 0.0
                for skill, data in lesson_feedback.items()
            }

        deltas = {}
        alpha = cls.SMOOTHING_ALPHA

        for skill_name in ["grammar", "vocabulary", "listening", "reading", "writing", "speaking"]:
            lesson_score_data = lesson_feedback.get(skill_name)

            if lesson_score_data is None:
                # Навык не оценивался — оставляем предыдущее значение
                prev_value = getattr(pre_snapshot, skill_name, 0.0)
                deltas[skill_name] = prev_value
                continue

            lesson_score = lesson_score_data["score"]
            prev_value = getattr(pre_snapshot, skill_name, 0.0)

            # Экспоненциальное сглаживание
            new_value = (alpha * lesson_score) + ((1 - alpha) * prev_value)
            deltas[skill_name] = round(new_value, 3)

        return deltas
