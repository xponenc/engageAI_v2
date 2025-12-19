from curriculum.models import CurrentSkill, SkillSnapshot


class SkillSnapshotCreator:
    """
    Создаёт исторический snapshot навыков студента.
    """

    def create(self, student):
        skills = {
            cs.skill: cs.score
            for cs in CurrentSkill.objects.filter(student=student)
        }

        return SkillSnapshot.objects.create(
            student=student,
            grammar=skills.get("grammar", 0.0),
            vocabulary=skills.get("vocabulary", 0.0),
            listening=skills.get("listening", 0.0),
            reading=skills.get("reading", 0.0),
            writing=skills.get("writing", 0.0),
            speaking=skills.get("speaking", 0.0),
        )
