from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser

from curriculum.models import Student
from curriculum.services.analytics.dashboards.explainability import AdminExplainabilityService
from curriculum.services.analytics.dashboards.serializers import AdminExplainabilityResponseSerializer


class AdminStudentExplainabilityView(APIView):
    """
    API endpoint для explainability студента.

    GET /admin/students/<id>/explainability/

    пример выдачи
    {
        "student_id": 42,
        "course": "Core English Grammar",
        "current_lesson": "Past Perfect",
        "last_outcome": "SIMPLIFY",
        "explanation": {
        "decision": "SIMPLIFY",
        "primary_reason": "Обнаружено снижение навыков: grammar",
        "supporting_factors": [
              {"type": "decline", "skills": ["grammar"]}
        ],
        "skill_insights": [
            {
                "skill": "grammar",
                "trend": -0.21,
                "stability": 0.32,
                "direction": "declining"
            }
        ],
        "confidence": 0.78
        },
        "skill_trajectories": [
            {
                "skill": "grammar",
                "trend": -0.21,
                "stability": 0.32,
                "direction": "declining",
                "last_updated": "2025-12-17T10:30:00Z"
            }
        ]
    }
    """

    permission_classes = [IsAdminUser]

    def get(self, request, student_id):
        student = get_object_or_404(Student, id=student_id)

        service = AdminExplainabilityService()
        data = service.build_for_student(student)

        if "error" in data:
            return Response(data, status=400)

        serializer = AdminExplainabilityResponseSerializer({
            "student_id": student.pk,
            "course": data["course"].title,
            "current_lesson": (
                data["current_lesson"].title
                if data["current_lesson"] else None
            ),
            "last_outcome": data["last_outcome"],
            "explanation": data["explanation"],
            "skill_trajectories": data["skill_trajectories"],
        })

        return Response(serializer.data)
