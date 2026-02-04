from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List

from django.utils import timezone

from curriculum.models import LearningObjective
from curriculum.models.learning_process.learning_path import LearningPath
from curriculum.models.content.lesson import Lesson


# ============================================================
# Enums
# ============================================================

class LearningPathAdjustmentType(Enum):
    """
    Типы изменений учебного пути.
    Используются для:
    - логирования
    - explainability
    - teacher dashboard
    """

    ADVANCE = "advance"
    INSERT_REMEDIAL = "insert_remedial"
    REWIND_LEVEL = "rewind_level"
    SOFT_SKIP = "soft_skip"
    HOLD = "hold"


# ============================================================
# DTOs (входные данные)
# ============================================================

@dataclass
class LessonOutcomeContext:
    """
    Контекст результата прохождения урока.

    Формируется на основе:
    - Assessment
    - LessonMetrics
    - Aggregation по LearningObjective

    ⚠️ ВАЖНО:
    Этот класс НЕ знает о SkillProfile и Assessment напрямую.
    """

    lesson_id: int

    objective_scores: Dict[str, float]
    # identifier -> score (0.0–1.0)

    objective_attempts: Dict[str, int]
    # identifier -> number of attempts

    completed_at: datetime


@dataclass
class ObjectiveAnalysisResult:
    """
    Результат анализа целей обучения.
    """

    mastered: List[LearningObjective]
    weak: List[LearningObjective]
    problematic: List[LearningObjective]


# ============================================================
# Основной сервис
# ============================================================

class LearningPathAdaptationService:
    """
    Доменный сервис адаптации LearningPath.

    Назначение:
    - Анализировать результаты урока на уровне LearningObjective
    - Модифицировать LearningPath (НЕ Course)
    - Управлять ветвлениями, откатами, remedial-узлами

    Инварианты:
    - Course и Lesson не изменяются
    - Адаптация происходит ТОЛЬКО через LearningPath.nodes
    - Один вызов = одна атомарная адаптация
    """

    # -------------------------------
    # Пороговые значения (MVP)
    # -------------------------------

    MASTERED_THRESHOLD = 0.8
    WEAK_THRESHOLD = 0.5
    PROBLEM_ATTEMPTS = 2

    # ========================================================
    # Public API
    # ========================================================


    @staticmethod
    def _get_current_node(learning_path) -> dict:
        """
        Возвращает текущий активный node.
        """
        idx = learning_path.current_node_index

        try:
            return learning_path.nodes[idx]
        except (IndexError, TypeError):
            raise RuntimeError(
                f"Invalid current_node_index={idx} for learning_path={learning_path.id}"
            )

    @staticmethod
    def _find_next_available_index(nodes, start_index: int) -> int | None:
        """
        Возвращает индекс следующего допустимого node,
        применяя правило soft skip.
        """
        for idx in range(start_index + 1, len(nodes)):
            if nodes[idx]["status"] in ("unlocked", "recommended"):
                return idx
        return None

    def adapt_after_lesson(
        self,
        learning_path: LearningPath,
        outcome: LessonOutcomeContext
    ) -> LearningPathAdjustmentType:
        """
        Главная точка входа.

        Вызывается после завершения урока.
        Может:
        - продвинуть по пути
        - вставить remedial узел
        - откатить путь назад
        - зафиксировать удержание

        Возвращает:
        LearningPathAdjustmentType — для explainability и логов.
        """

        current_node = learning_path.current_node
        if not current_node:
            return LearningPathAdjustmentType.HOLD

        # 1. Анализ целей обучения
        analysis = self._analyze_objectives(outcome)

        # 2. Обновляем статус текущего узла
        self._update_current_node_status(
            learning_path=learning_path,
            analysis=analysis
        )

        # 3. Happy path — всё ок
        if not analysis.problematic:
            self._advance_to_next_available_node(learning_path)
            return LearningPathAdjustmentType.ADVANCE

        # 4. Есть проблемные цели → remedial
        if self._should_insert_remedial(analysis):
            self._insert_remedial_nodes(
                learning_path=learning_path,
                objectives=analysis.problematic
            )
            return LearningPathAdjustmentType.INSERT_REMEDIAL

        # 5. Множественные провалы → откат уровня
        if self._should_rewind_level(analysis):
            target_level = self._determine_lower_cefr_level(analysis.problematic)
            self._rewind_to_cefr_level(
                learning_path=learning_path,
                cefr_level=target_level
            )
            return LearningPathAdjustmentType.REWIND_LEVEL

        return LearningPathAdjustmentType.HOLD

    # ========================================================
    # Objective analysis
    # ========================================================

    def _analyze_objectives(
        self,
        outcome: LessonOutcomeContext
    ) -> ObjectiveAnalysisResult:
        """
        Классифицирует LearningObjective по результатам урока.
        """

        identifiers = outcome.objective_scores.keys()

        objectives = {
            obj.identifier: obj
            for obj in LearningObjective.objects.filter(
                identifier__in=identifiers,
                is_active=True
            )
        }

        mastered = []
        weak = []
        problematic = []

        for identifier, score in outcome.objective_scores.items():
            obj = objectives.get(identifier)
            if not obj:
                continue

            attempts = outcome.objective_attempts.get(identifier, 1)

            if score >= self.MASTERED_THRESHOLD:
                mastered.append(obj)
            elif score >= self.WEAK_THRESHOLD:
                weak.append(obj)
            elif attempts >= self.PROBLEM_ATTEMPTS:
                problematic.append(obj)
            else:
                weak.append(obj)

        return ObjectiveAnalysisResult(
            mastered=mastered,
            weak=weak,
            problematic=problematic
        )

    # ========================================================
    # Node mutation logic
    # ========================================================

    def _update_current_node_status(
        self,
        learning_path: LearningPath,
        analysis: ObjectiveAnalysisResult
    ) -> None:
        """
        Обновляет статус текущего узла.
        """

        node = learning_path.current_node
        if not node:
            return

        if analysis.problematic:
            node["status"] = "in_progress"
        else:
            node["status"] = "completed"
            node["completed_at"] = datetime.utcnow().isoformat()

        self._save_nodes(learning_path)

    def _advance_to_next_available_node(
        self,
        learning_path: LearningPath
    ) -> None:
        """
        Продвигается к следующему незавершённому узлу.
        Реализует soft skip.
        """

        nodes = learning_path.nodes
        idx = learning_path.current_node_index + 1

        while idx < len(nodes):
            if nodes[idx]["status"] not in ("completed", "skipped"):
                learning_path.current_node_index = idx
                learning_path.save(update_fields=["current_node_index"])
                return
            idx += 1

    def _insert_remedial_nodes(
        self,
        learning_path: LearningPath,
        objectives: List[LearningObjective]
    ) -> None:
        """
        Вставляет remedial-узлы сразу после текущего.
        """

        current_idx = learning_path.current_node_index
        nodes = learning_path.nodes

        remedial_nodes = []
        for obj in objectives:
            remedial_nodes.append({
                "node_id": f"remedial-{obj.identifier}-{datetime.utcnow().timestamp()}",
                "lesson_id": None,  # TODO: optional mapping to remedial lesson
                "title": f"Повтор: {obj.name}",
                "reason": f"Пробел по цели {obj.identifier}",
                "type": "remedial",
                "learning_objective": obj.identifier,
                "status": "locked",
                "prerequisites": [nodes[current_idx]["node_id"]],
                "triggers": []
            })

        # Вставляем после текущего узла
        learning_path.nodes = (
            nodes[:current_idx + 1] +
            remedial_nodes +
            nodes[current_idx + 1:]
        )

        self._save_nodes(learning_path)

    def _rewind_to_cefr_level(
        self,
        learning_path: LearningPath,
        cefr_level: str
    ) -> None:
        """
        Soft rewind: откат к урокам более низкого уровня.
        """

        nodes = learning_path.nodes

        for idx, node in enumerate(nodes):
            lesson_id = node.get("lesson_id")
            if not lesson_id:
                continue

            lesson = Lesson.objects.filter(id=lesson_id).first()
            if not lesson:
                continue

            if lesson.required_cefr == cefr_level:
                learning_path.current_node_index = idx
                break

        learning_path.save(update_fields=["current_node_index"])

    # ========================================================
    # Decision helpers
    # ========================================================

    def _should_insert_remedial(
        self,
        analysis: ObjectiveAnalysisResult
    ) -> bool:
        """
        MVP-эвристика:
        - есть problematic objectives
        """
        return bool(analysis.problematic)

    def _should_rewind_level(
        self,
        analysis: ObjectiveAnalysisResult
    ) -> bool:
        """
        TODO:
        - учитывать историю нескольких уроков
        - учитывать стабильность SkillTrajectory
        """
        return False  # MVP: отключено

    def _determine_lower_cefr_level(
        self,
        objectives: List[LearningObjective]
    ) -> str:
        """
        TODO:
        - использовать CEFRLevel enum
        - учитывать минимальный уровень среди целей
        """
        return objectives[0].cefr_level

    # ========================================================
    # Persistence helpers
    # ========================================================

    def _save_nodes(self, learning_path: LearningPath) -> None:
        """
        Сохраняет nodes и updated_at.
        """
        learning_path.save(update_fields=["nodes", "updated_at"])
