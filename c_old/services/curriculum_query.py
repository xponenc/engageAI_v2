from datetime import timedelta
from typing import Optional, Iterable

from django.db.models import OuterRef, Exists

from curriculum.models import StudentTaskResponse, SkillSnapshot
from curriculum.models.student.enrollment import Enrollment
from curriculum.models.content.lesson import Lesson
from curriculum.models.content.task import Task


class CurriculumQueryService:
    """
    Read-only сервис доступа к учебному контенту.

    Инкапсулирует правила:
    - выбора текущего урока
    - порядка заданий
    - фильтрации неактивного контента

    TODO (CurriculumQueryService):

    1. Поддержка diagnostic lessons
    2. Фильтрация задач по ProfessionalTag (через weighting, не exclude)
    3. Поддержка branching curriculum
    4. Предзагрузка related (performance)
    """

    # ------------------------------------------------------------------
    # LESSON
    # ------------------------------------------------------------------

    def get_current_lesson(self, enrollment: Enrollment) -> Lesson:
        """
        Возвращает текущий урок для enrollment.

        Если текущий урок не установлен — выбирается первый доступный.
        """

        if enrollment.current_lesson:
            return enrollment.current_lesson

        first_lesson = (
            Lesson.objects
            .filter(course=enrollment.course, is_active=True)
            .order_by("order")
            .first()
        )

        return first_lesson

    # TASKS

    def get_next_task(self, enrollment: Enrollment) -> Optional[Task]:
        """
        Возвращает следующее невыполненное задание
        для студента в текущем уроке.
        """
        if not enrollment.current_lesson:
            return None

        student_responses = StudentTaskResponse.objects.filter(
            student=enrollment.student,
            task=OuterRef('pk'),
        )

        return (
            Task.objects
            .filter(
                lesson=enrollment.current_lesson,
                is_active=True,
            )
            .annotate(
                has_response=Exists(student_responses)
            )
            .filter(has_response=False)
            .order_by('order')
            .first()
        )

    # def get_lesson_history(self, enrollment: Enrollment, lesson: Lesson) -> list:
    #     """
    #     Возвращает историю ответов студента по уроку.
    #
    #     Возвращает список словарей с информацией о каждом задании и ответе:
    #     {
    #         'task': Task,
    #         'response': StudentTaskResponse,
    #         'assessment': Assessment,
    #         'is_completed': bool,
    #         'score': float,
    #         'feedback': str
    #     }
    #     """
    #     # Получаем все задания урока
    #     tasks = list(Task.objects.filter(lesson=lesson, is_active=True).order_by('order'))
    #
    #     # Получаем все ответы студента по уроку
    #     responses = StudentTaskResponse.objects.filter(
    #         student=enrollment.student,
    #         task__lesson=lesson
    #     ).select_related(
    #         'task', 'assessment'
    #     ).prefetch_related(
    #         'assessment__error_tags'
    #     ).order_by('submitted_at')
    #
    #     # Создаем словарь для быстрого поиска ответов по task_id
    #     responses_by_task = {response.task_id: response for response in responses}
    #
    #     # Формируем результат
    #     history = []
    #     for task in tasks:
    #         response = responses_by_task.get(task.id)
    #         assessment = response.assessment if response else None
    #
    #         history.append({
    #             'task': task,
    #             'response': response,
    #             'assessment': assessment,
    #             'is_completed': response is not None,
    #             'score': assessment.score if assessment else None,
    #             'feedback': assessment.feedback.get('message', '') if assessment and assessment.feedback else '',
    #             'submitted_at': response.submitted_at if response else None
    #         })
    #
    #     return history

    def get_lesson_history(self, enrollment: Enrollment, lesson: Lesson) -> dict:
        """
        Возвращает полную историю выполнения урока с контекстом.

        Возвращает словарь со следующей структурой:
        {
            'lesson': Lesson,  # Объект урока
            'is_completed': bool,  # Завершен ли урок
            'completion_date': datetime,  # Дата завершения (если завершен)
            'progress_percent': float,  # Прогресс по уроку в процентах
            'tasks': [{  # Детальная информация по каждому заданию
                'task': Task,
                'is_completed': bool,
                'attempts_count': int,  # Количество попыток
                'best_score': float,  # Лучший результат
                'last_response': StudentTaskResponse,
                'last_assessment': Assessment,
                'first_submitted_at': datetime,
                'last_submitted_at': datetime,
                'time_spent': timedelta  # Время на выполнение
            }],
            'skill_progress': {  # Прогресс по навыкам
                'grammar': {'before': float, 'after': float, 'delta': float},
                'vocabulary': {'before': float, 'after': float, 'delta': float},
                'listening': {'before': float, 'after': float, 'delta': float},
                'reading': {'before': float, 'after': float, 'delta': float},
                'writing': {'before': float, 'after': float, 'delta': float},
                'speaking': {'before': float, 'after': float, 'delta': float}
            },
            'statistics': {  # Общая статистика
                'total_time_spent': timedelta,  # Общее время на урок
                'average_score': float,  # Средняя оценка
                'completion_rate': float,  # Процент выполненных заданий
                'error_patterns': list,  # Повторяющиеся ошибки
                'strengths': list  # Сильные стороны
            },
            'recommendations': [{  # Рекомендации для улучшения
                'skill': str,  # Навык для улучшения
                'priority': int,  # Приоритет (1-3)
                'message': str  # Текст рекомендации
            }]
        }
        """
        # Получаем все задания урока
        tasks = list(Task.objects.filter(lesson=lesson, is_active=True).order_by('order'))

        # Получаем все ответы студента по уроку
        responses = StudentTaskResponse.objects.filter(
            student=enrollment.student,
            task__lesson=lesson
        ).select_related(
            'task', 'assessment'
        ).prefetch_related(
            'assessment'
        ).order_by('submitted_at')

        # Создаем словарь для быстрого поиска ответов по task_id
        responses_by_task = {}
        for response in responses:
            if response.task_id not in responses_by_task:
                responses_by_task[response.task_id] = []
            responses_by_task[response.task_id].append(response)

        # Рассчитываем статистику по каждому заданию
        tasks_data = []
        completed_count = 0
        total_score = 0
        total_time_spent = timedelta()

        for task in tasks:
            task_responses = responses_by_task.get(task.id, [])
            is_completed = len(task_responses) > 0

            if is_completed:
                completed_count += 1
                first_response = task_responses[0]
                last_response = task_responses[-1]

                # Рассчитываем время на задание (если есть дата первого и последнего ответа)
                time_spent = timedelta()
                if hasattr(first_response, 'submitted_at') and hasattr(last_response, 'submitted_at'):
                    time_spent = last_response.submitted_at - first_response.submitted_at

                total_time_spent += time_spent

                tasks_data.append({
                    'task': task,
                    'is_completed': is_completed,
                    'attempts_count': len(task_responses),
                    'last_response': last_response,
                    'last_assessment': last_response.assessment if last_response.assessment else None,
                    'first_submitted_at': first_response.submitted_at,
                    'last_submitted_at': last_response.submitted_at,
                    'time_spent': time_spent
                })
            else:
                tasks_data.append({
                    'task': task,
                    'is_completed': is_completed,
                    'attempts_count': 0,
                    'best_score': 0,
                    'last_response': None,
                    'last_assessment': None,
                    'first_submitted_at': None,
                    'last_submitted_at': None,
                    'time_spent': timedelta()
                })

        # Рассчитываем общий прогресс по уроку
        total_tasks = len(tasks)
        progress_percent = (completed_count / total_tasks * 100) if total_tasks > 0 else 0

        # Определяем, завершен ли урок (минимум 80% заданий выполнено)
        is_completed = progress_percent >= 80
        completion_date = None

        if is_completed and tasks_data:
            # Дата завершения - последний ответ
            completion_date = max(
                (data['last_submitted_at'] for data in tasks_data if data['last_submitted_at']),
                default=None
            )

        # Получаем прогресс по навыкам (если есть снимки)
        skill_progress = self._get_skill_progress_for_lesson(enrollment, lesson)

        # Формируем статистику
        average_score = self._calculate_lesson_average_score(responses)
        completion_rate = progress_percent / 100

        # Определяем паттерны ошибок
        error_patterns = self._identify_error_patterns(tasks_data)

        # Определяем сильные стороны
        strengths = self._identify_strengths(skill_progress)

        return {
            'lesson': lesson,
            'is_completed': is_completed,
            'completion_date': completion_date,
            'progress_percent': progress_percent,
            'tasks': tasks_data,
            'skill_progress': skill_progress,
            'statistics': {
                'total_time_spent': total_time_spent,
                'average_score': average_score,
                'completion_rate': completion_rate,
                'error_patterns': error_patterns,
                'strengths': strengths
            },
        }

    def _calculate_lesson_average_score(
            self,
            responses: Iterable[StudentTaskResponse],
    ) -> float:
        """
        Считает средний балл по уроку на основе structured_feedback.skill_evaluation.

        Учитываются только числовые score (int | float).
        None и некорректные значения игнорируются.
        """

        total_score: float = 0.0
        score_count: int = 0

        for response in responses:
            assessment = getattr(response, "assessment", None)
            if not assessment:
                continue

            feedback = getattr(assessment, "structured_feedback", None)
            if not isinstance(feedback, dict):
                continue

            skill_eval = feedback.get("skill_evaluation")
            if not isinstance(skill_eval, dict):
                continue

            for data in skill_eval.values():
                score = data.get("score") if isinstance(data, dict) else None
                if isinstance(score, (int, float)):
                    total_score += float(score)
                    score_count += 1

        return round(total_score / score_count, 2) if score_count > 0 else 0.0

    def _get_skill_progress_for_lesson(self, enrollment: Enrollment, lesson: Lesson) -> dict:
        """
        Рассчитывает прогресс по навыкам для урока.
        Возвращает словарь с изменением каждого навыка.
        """
        # Получаем последний снимок перед уроком
        # before_snapshot = SkillSnapshot.objects.filter(
        #     student=enrollment.student,
        #     created_at__lt=lesson.created_at
        # ).order_by('-snapshot_at').first()
        #
        # # Получаем снимок после урока
        # after_snapshot = SkillSnapshot.objects.filter(
        #     student=enrollment.student,
        #     lesson=lesson
        # ).order_by('-snapshot_at').first()

        skill_progress = {}
        skills = ['grammar', 'vocabulary', 'listening', 'reading', 'writing', 'speaking']

        for skill in skills:
            before_value = getattr(before_snapshot, skill, 0.5) if before_snapshot else 0.5
            after_value = getattr(after_snapshot, skill, before_value) if after_snapshot else before_value
            delta = after_value - before_value

            skill_progress[skill] = {
                'before': round(before_value, 2),
                'after': round(after_value, 2),
                'delta': round(delta, 2)
            }

        return skill_progress

    def _identify_error_patterns(self, tasks_data: list) -> list:
        """
        Выявляет повторяющиеся паттерны ошибок в заданиях.
        """
        error_patterns = []
        error_counts = {}

        for data in tasks_data:
            if data['last_assessment'] and data['last_assessment'].structured_feedback:
                feedback = data['last_assessment'].structured_feedback
                if 'errors' in feedback:
                    for error in feedback['errors']:
                        error_type = error.get('type', 'unknown')
                        error_counts[error_type] = error_counts.get(error_type, 0) + 1

        # Сортируем по частоте
        sorted_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)

        for error_type, count in sorted_errors[:3]:  # Топ-3 паттерна
            if count >= 2:  # Повторяющаяся ошибка
                patterns = {
                    'grammar': 'Грамматические ошибки (времена, согласование)',
                    'spelling': 'Орфографические ошибки',
                    'vocabulary': 'Неточное использование лексики',
                    'concept_gap': 'Недостаточное понимание концепции',
                    'audio_quality': 'Проблемы с качеством аудио',
                    'unclear_speech': 'Нечеткое произношение'
                }
                error_patterns.append({
                    'type': error_type,
                    'description': patterns.get(error_type, error_type),
                    'count': count
                })

        return error_patterns

    def _identify_strengths(self, skill_progress: dict) -> list:
        """
        Выявляет сильные стороны на основе прогресса по навыкам.
        """
        strengths = []

        for skill, data in skill_progress.items():
            if data['delta'] > 0.1:  # Значительный прогресс
                skill_descriptions = {
                    'grammar': 'грамматике',
                    'vocabulary': 'словарному запасу',
                    'listening': 'аудированию',
                    'reading': 'чтению',
                    'writing': 'письму',
                    'speaking': 'говорению'
                }

                strengths.append({
                    'skill': skill,
                    'description': f"Вы хорошо продвинулись в {skill_descriptions.get(skill, skill)}. Продолжайте в том же духе!",
                    'before': data['before'],
                    'after': data['after'],
                    'delta': data['delta']
                })

        return strengths

    def get_completed_lessons(self, enrollment: Enrollment) -> list:
        """
        Возвращает список пройденных уроков с информацией о прогрессе.

        Возвращает список словарей:
        {
            'lesson': Lesson,
            'completed_tasks': int,
            'total_tasks': int,
            'completion_percent': float,
            'last_response_date': datetime
        }
        """
        if not enrollment.current_lesson:
            return []

        # Получаем все уроки курса до текущего
        completed_lessons = Lesson.objects.filter(
            course=enrollment.course,
            is_active=True,
            order__lt=enrollment.current_lesson.order
        ).order_by('order').prefetch_related('tasks')

        result = []
        for lesson in completed_lessons:
            # Считаем общее количество заданий в уроке
            total_tasks = lesson.tasks.filter(is_active=True).count()

            # Считаем количество выполненных заданий
            completed_tasks = StudentTaskResponse.objects.filter(
                student=enrollment.student,
                task__lesson=lesson,
                task__is_active=True
            ).count()

            # Получаем дату последнего ответа
            last_response = StudentTaskResponse.objects.filter(
                student=enrollment.student,
                task__lesson=lesson
            ).order_by('-submitted_at').first()

            completion_percent = round((completed_tasks / total_tasks) * 100, 1) if total_tasks > 0 else 0

            result.append({
                'lesson': lesson,
                'completed_tasks': completed_tasks,
                'total_tasks': total_tasks,
                'completion_percent': completion_percent,
                'last_response_date': last_response.submitted_at if last_response else None
            })

        return result
