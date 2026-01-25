from django.utils import timezone
from curriculum.models.student.skill_snapshot import SkillSnapshot
from curriculum.models.student.skill_delta import SkillDelta


class SkillUpdateService:
    """
    Сервис обновления навыков студента после завершения урока.
    Создаёт POST_LESSON snapshot и delta.
    Вызывается автоматически после события COMPLETE.
    """

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