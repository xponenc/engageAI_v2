from rest_framework import serializers

from curriculum.models import SkillTrajectory


class SkillTrajectorySerializer(serializers.ModelSerializer):
    """
    Сериализация траектории одного навыка.
    """

    direction = serializers.SerializerMethodField()

    class Meta:
        model = SkillTrajectory
        fields = (
            "skill",
            "trend",
            "stability",
            "direction",
            "last_updated",
        )

    def get_direction(self, obj):
        if obj.trend > 0.15:
            return "improving"
        if obj.trend < -0.15:
            return "declining"
        return "stable"


class ExplainabilitySerializer(serializers.Serializer):
    """
    Сериализация explainability-результата.

    Это НЕ модель.
    """

    decision = serializers.CharField()
    primary_reason = serializers.CharField()
    supporting_factors = serializers.ListField()
    skill_insights = serializers.ListField()
    confidence = serializers.FloatField()


class AdminExplainabilityResponseSerializer(serializers.Serializer):
    """
    Финальный ответ для Teacher / Admin UI.
    """

    student_id = serializers.IntegerField()
    course = serializers.CharField()
    current_lesson = serializers.CharField(allow_null=True)
    last_outcome = serializers.CharField()

    explanation = ExplainabilitySerializer()
    skill_trajectories = SkillTrajectorySerializer(many=True)
