class LearningPathProgressService:
    """
    Расчёт пользовательского прогресса по LearningPath.
    """

    @staticmethod
    def get_core_progress(learning_path) -> dict:
        """
        Возвращает прогресс по core-урокам:
        - completed
        - current
        - total
        """

        nodes = learning_path.nodes

        core_nodes = [
            node for node in nodes
            if node["type"] == "core"
        ]

        total = len(core_nodes)

        completed = [
            node for node in core_nodes
            if node["status"] == "completed"
        ]

        current = next(
            (node for node in core_nodes if node["status"] == "in_progress"),
            None
        )

        current_number = None
        if current:
            current_number = core_nodes.index(current) + 1

        return {
            "completed_lessons": len(completed),
            "current_lesson_number": current_number,
            "total_lessons": total
        }
