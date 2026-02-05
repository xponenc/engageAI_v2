from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List

from django.utils import timezone

from curriculum.models import LearningObjective
from curriculum.models.learning_process.learning_path import LearningPath
from curriculum.models.content.lesson import Lesson


class LearningPathAdjustmentType(Enum):
    ADVANCE = "advance"
    INSERT_REMEDIAL = "insert_remedial"
    REWIND_LEVEL = "rewind_level"
    SOFT_SKIP = "soft_skip"
    HOLD = "hold"


@dataclass
class LessonOutcomeContext:
    lesson_id: int
    objective_scores: Dict[str, float]
    objective_attempts: Dict[str, int]
    completed_at: datetime


@dataclass
class ObjectiveAnalysisResult:
    mastered: List[LearningObjective]
    weak: List[LearningObjective]
    problematic: List[LearningObjective]


class LearningPathAdaptationService:
    """
    Доменный сервис адаптации LearningPath.

    ❗ Инварианты:
    - Course и Lesson НЕ изменяются
    - Адаптация ТОЛЬКО через LearningPath.nodes
    """

    MASTERED_THRESHOLD = 0.8
    ADVANCE_LEVEL_THRESHOLD = 0.85
    WEAK_THRESHOLD = 0.5
    PROBLEM_ATTEMPTS = 2

    SKIPPABLE_STATUSES = ("completed", "skipped")
    ENTERABLE_STATUSES = ("in_progress", "unlocked", "recommended")

    # ========================================================
    # Public API
    # ========================================================

    def adapt_after_lesson(
        self,
        learning_path: LearningPath,
        outcome: LessonOutcomeContext
    ) -> LearningPathAdjustmentType:

        current_node = learning_path.current_node
        if not current_node:
            return LearningPathAdjustmentType.HOLD

        analysis = self._analyze_objectives(outcome)
        self._update_current_node_status(learning_path, analysis)

        # 5.1 Happy path
        if not analysis.problematic and not analysis.weak:
            self._advance_to_next_available_node(learning_path)
            return LearningPathAdjustmentType.ADVANCE

        # 5.2 Провал → remedial
        if self._should_insert_remedial(analysis):
            self._insert_remedial_nodes(learning_path, analysis.problematic)
            return LearningPathAdjustmentType.INSERT_REMEDIAL

        # 5.5 Понижение уровня
        if self._should_rewind_level(analysis):
            target_level = self._determine_lower_cefr_level(analysis.problematic)
            self._rewind_to_lower_cefr_level(learning_path, target_level)
            return LearningPathAdjustmentType.REWIND_LEVEL

        # 5.6 / 5.7 Повышение уровня
        if self._should_advance_level(analysis):
            target_level = self._determine_higher_cefr_level(analysis.mastered)
            self._advance_to_higher_cefr_level(learning_path, target_level)
            return LearningPathAdjustmentType.SOFT_SKIP

        return LearningPathAdjustmentType.HOLD

    # ========================================================
    # Objective analysis
    # ========================================================

    def _analyze_objectives(self, outcome: LessonOutcomeContext) -> ObjectiveAnalysisResult:
        identifiers = outcome.objective_scores.keys()

        objectives = {
            obj.identifier: obj
            for obj in LearningObjective.objects.filter(identifier__in=identifiers)
        }

        mastered, weak, problematic = [], [], []

        for identifier, score in outcome.objective_scores.items():
            obj = objectives.get(identifier)
            if not obj:
                continue

            attempts = outcome.objective_attempts.get(identifier, 1)

            if score >= self.ADVANCE_LEVEL_THRESHOLD:
                mastered.append(obj)
            elif score >= self.WEAK_THRESHOLD:
                weak.append(obj)
            elif attempts >= self.PROBLEM_ATTEMPTS:
                problematic.append(obj)
            else:
                weak.append(obj)

        return ObjectiveAnalysisResult(mastered, weak, problematic)

    # ========================================================
    # Node mutation
    # ========================================================

    def _update_current_node_status(self, learning_path, analysis):
        node = learning_path.current_node
        if not node:
            return

        if analysis.problematic:
            node["status"] = "in_progress"
        else:
            node["status"] = "completed"
            node["completed_at"] = timezone.now().isoformat()

        learning_path.save(update_fields=["nodes", "updated_at"])

    def _advance_to_next_available_node(self, learning_path):
        nodes = learning_path.nodes
        idx = learning_path.current_node_index + 1

        while idx < len(nodes):
            if nodes[idx]["status"] not in ("completed", "skipped"):
                learning_path.current_node_index = idx
                learning_path.save(update_fields=["current_node_index"])
                return
            idx += 1

    def _insert_remedial_nodes(self, learning_path, objectives):
        current_idx = learning_path.current_node_index
        nodes = learning_path.nodes

        remedial_nodes = []
        for obj in objectives:
            remedial_nodes.append({
                "node_id": f"remedial-{obj.identifier}-{timezone.now().timestamp()}",
                "lesson_id": None,  # TODO: привязать к remedial-lesson
                "type": "remedial",
                "title": f"Повтор: {obj.name}",
                "learning_objective": obj.identifier,
                "status": "locked",
                "created_at": timezone.now().isoformat()
            })

        learning_path.nodes = (
            nodes[:current_idx + 1] +
            remedial_nodes +
            nodes[current_idx + 1:]
        )
        learning_path.save(update_fields=["nodes", "updated_at"])

    # ========================================================
    # Rewind / Advance level
    # ========================================================

    def _rewind_to_lower_cefr_level(self, learning_path, target_cefr_level):
        nodes = learning_path.nodes
        rewind_index = None

        for idx, node in enumerate(nodes):
            lesson_id = node.get("lesson_id")
            if not lesson_id:
                continue

            lesson = Lesson.objects.filter(id=lesson_id).only("required_cefr").first()
            if lesson and lesson.required_cefr == target_cefr_level:
                rewind_index = idx
                break

        if rewind_index is None:
            return

        for idx in range(rewind_index, len(nodes)):
            if nodes[idx]["status"] == "locked":
                nodes[idx]["status"] = "recommended"

        learning_path.current_node_index = rewind_index
        learning_path.save(update_fields=["nodes", "current_node_index", "updated_at"])

    def _advance_to_higher_cefr_level(self, learning_path, target_cefr_level):
        nodes = learning_path.nodes
        advance_index = None

        for idx, node in enumerate(nodes):
            lesson_id = node.get("lesson_id")
            if not lesson_id:
                continue

            lesson = Lesson.objects.filter(id=lesson_id).only("required_cefr").first()
            if lesson and lesson.required_cefr == target_cefr_level:
                advance_index = idx
                break

        if advance_index is None:
            return

        for idx in range(advance_index):
            if nodes[idx]["status"] not in ("completed", "skipped"):
                nodes[idx]["status"] = "skipped"

        nodes[advance_index]["status"] = "in_progress"
        learning_path.current_node_index = advance_index

        learning_path.save(update_fields=["nodes", "current_node_index", "updated_at"])

    # ========================================================
    # Decision helpers
    # ========================================================

    def _should_insert_remedial(self, analysis):
        return bool(analysis.problematic)

    def _should_rewind_level(self, analysis):
        # TODO: учитывать несколько уроков + SkillTrajectory
        return False

    def _should_advance_level(self, analysis):
        return (
            bool(analysis.mastered)
            and not analysis.weak
            and not analysis.problematic
        )

    def _determine_lower_cefr_level(self, objectives):
        # TODO: использовать CEFRLevel enum
        return objectives[0].cefr_level

    def _determine_higher_cefr_level(self, mastered):
        # TODO: использовать CEFRLevel enum
        return mastered[0].cefr_level
