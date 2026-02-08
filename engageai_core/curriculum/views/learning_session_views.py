import json
import logging
import math

from celery.result import AsyncResult
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.shortcuts import redirect, render, get_object_or_404
from django.urls import reverse_lazy, reverse, NoReverseMatch
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, TemplateView
from django.http import JsonResponse, Http404

from chat.views import ChatContextMixin
# from curriculum.config.dependency_factory import CurriculumServiceFactory
from curriculum.models.content.task import ResponseFormat, Task
from curriculum.models.student.enrollment import Enrollment, LessonStatus
from ..forms import LessonTasksForm

from curriculum.tasks import assess_lesson_tasks, launch_full_assessment
from ..models import LessonAssessmentResult, TaskAssessmentResult, Course
from ..models.content.lesson import Lesson
from ..models.learning_process.lesson_event_log import LessonEventType
from ..models.student.skill_snapshot import SkillSnapshot
from ..models.student.student_response import StudentTaskResponse
from ..services.learning_path_adaptation import LearningPathAdaptationService
from ..services.learning_path_progress import LearningPathProgressService
from ..services.lesson_assessment_service import LessonAssessmentService
from ..services.lesson_event_service import LessonEventService
from ..validators import SkillDomain

logger = logging.getLogger(__name__)


class LearningSessionView(LoginRequiredMixin, ChatContextMixin, TemplateView):
    """
    Class-Based View для отображения и завершения текущего урока.
    GET — показывает урок
    POST — обрабатывает отправку ответов, оценку и завершение урока
    """
    template_name = "curriculum/learning_session.html"

    def get(self, request, *args, **kwargs):
        pk = kwargs.get("pk")
        enrollment = self._get_enrollment(pk)
        lesson, current_node = self._get_current_lesson_and_node(enrollment)
        lesson_tasks = lesson.active_tasks

        lesson_assessment = LessonAssessmentResult.objects.filter(
            enrollment=enrollment,
            lesson=lesson,
        ).exists()
        if lesson_assessment:
            print(lesson_assessment)
            return redirect("curriculum:lesson_history", lesson.id)

        if current_node.get("status") != "in_progress":
            learning_path = enrollment.learning_path
            current_node_index = enrollment.learning_path.current_node_index
            learning_path.nodes[current_node_index]["status"] = "in_progress"
            learning_path.save(update_fields=['nodes', ])
            # Логируем начало урока (если ещё не было в эту сессию)
            LessonEventService.create_event(
                student=enrollment.student,
                enrollment=enrollment,
                lesson=lesson,
                event_type=LessonEventType.START,
                channel="WEB",
                metadata={
                    "node_id": current_node["node_id"],
                    "path_type": enrollment.learning_path.path_type,
                    "reason": current_node.get("reason", ""),
                    "type": current_node.get("type", "core")
                }
            )

        # Форма заданий урока
        lesson_form = LessonTasksForm(lesson=lesson)

        context = self.get_context_data(
            enrollment=enrollment,
            lesson=lesson,
            lesson_tasks=lesson_tasks,
            current_node=current_node,
            path_type=enrollment.learning_path.path_type,
            progress=self._get_progress_data(enrollment.learning_path, current_node),
            lesson_form=lesson_form,
            is_preview=current_node.get("type") == "preview",
            recommended_reason=current_node.get("reason", ""),
        )
        return self.render_to_response(context)

    def post(self, request, pk):
        enrollment = self._get_enrollment(pk)

        lesson, current_node = self._get_current_lesson_and_node(enrollment)

        form = LessonTasksForm(request.POST, request.FILES, lesson=lesson)

        if not form.is_valid():
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': 'Некорректные данные в ответах', 'errors': form.errors}, status=400)
            messages.error(request, "Пожалуйста, заполните все обязательные поля")
            return redirect(request.path)

        form_lesson_id = form.cleaned_data.get("lesson_id")
        if lesson.pk != form_lesson_id:
            logger.error(f"Оцениваемый урок id:{form_lesson_id} не совпадает с current_node: {current_node}, {lesson=} ")
            raise Http404("Ошибка в учебном плане, обратитесь к администратору")

        # Логируем начало оценки урока
        LessonEventService.create_event(
            student=enrollment.student,
            enrollment=enrollment,
            lesson=lesson,
            event_type=LessonEventType.ASSESSMENT_START,
            channel="WEB",
            metadata={
                "node_id": current_node["node_id"],
                "path_type": enrollment.learning_path.path_type,
                "reason": current_node.get("reason", ""),
                "type": current_node.get("type", "core")
            }
        )

        # Сохранение ответов студента (через существующий сервис)
        responses = self._collect_responses(request, lesson.active_tasks)
        self._save_student_responses(enrollment, responses)

        # Запуск оценки (асинхронно через Celery)
        enrollment.lesson_status = LessonStatus.PENDING_ASSESSMENT
        enrollment.save(update_fields=["lesson_status", ])

        assessment_service = LessonAssessmentService()
        job_id = assessment_service.start_assessment(enrollment, lesson.pk)

        if job_id:
            # Уже сохранено в сервисе
            pass
        else:
            # Ошибка запуска — обработать
            return self._handle_error(request, 'Не удалось запустить оценку', 500)

        # # Логирование события завершения
        # LessonEventService.create_event(
        #     student=enrollment.student,
        #     enrollment=enrollment,
        #     lesson=lesson,
        #     event_type=LessonEventType.COMPLETE,
        #     channel="WEB",
        #     metadata={
        #         "node_id": current_node["node_id"],
        #         "tasks_completed": len(responses),
        #         "pending_assessment": True,
        #         "submitted_at": timezone.now().isoformat()
        #     }
        # )

        # Ответ пользователю
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        if is_ajax:
            return JsonResponse({
                'message': 'Ответы отправлены на оценку. Пожалуйста, подождите...',
                'status': 'pending_assessment',
                'check_status_url': reverse('check_lesson_assessment', kwargs={'enrollment_id': enrollment.id})
            })

        messages.info(request, f"Ответы отправлены на оценку. Идёт обработка...")
        return redirect('curriculum:check_lesson_assessment', enrollment_id=enrollment.id)

        # return self._handle_success(request, 'Ответы отправлены. Идёт оценка...',
        #                             reverse('check_lesson_assessment', kwargs={'enrollment_id': enrollment.id}))

    def _get_enrollment(self, pk):
        enrollment = get_object_or_404(Enrollment, pk=pk)
        if enrollment.student != self.request.user.student:
            raise Http404("Это не ваш зачисление")
        return enrollment

    def _get_current_lesson_and_node(self, enrollment):
        if not hasattr(enrollment, 'learning_path') or not enrollment.learning_path.nodes:
            raise Http404("Учебный путь не инициализирован")

        current_node = enrollment.learning_path.current_node

        if not current_node:
            raise Http404("Нет текущего узла в пути")

        try:
            lesson = Lesson.objects.filter(
                id=current_node["lesson_id"],
                is_active=True
            ).prefetch_related(
                Prefetch(
                    'tasks',
                    queryset=Task.objects.filter(is_active=True).order_by('order'),
                    to_attr='active_tasks'
                ),
                "learning_objectives"
            ).get()
        except Lesson.DoesNotExist:
            raise Http404(f"Урок {current_node['lesson_id']} не найден")

        return lesson, current_node

    def _collect_responses(self, request, lesson_tasks):
        """
        Собирает ответы из запроса.

        Принцип:
        - КАЖДОЕ задание попадает в responses
        - Пустой / некорректный ответ → text="" / audio_file=None
        - Оценщик сам решает, как это интерпретировать (neutral)
        """
        responses: dict[int, dict] = {}

        for task in lesson_tasks:
            field_name = f'task_{task.id}'
            audio_field = f'task_{task.id}_audio'

            # === Значение по умолчанию (пустой ответ) ===
            responses[task.id] = {
                'text': '',
                'audio_file': None
            }

            # ===== AUDIO =====
            if task.response_format == 'audio':
                if audio_field in request.FILES:
                    responses[task.id]['audio_file'] = request.FILES[audio_field]
                continue

            # ===== MULTIPLE CHOICE =====
            if task.response_format == 'multiple_choice':
                values = request.POST.getlist(field_name)

                if not values:
                    # пустой ответ → останется нейтральным
                    continue

                options = set(task.content.get('options', []))
                invalid = [v for v in values if v not in options]

                if invalid:
                    logger.warning(
                        "Invalid multiple_choice values",
                        extra={
                            "task_id": task.id,
                            "invalid": invalid,
                            "allowed": list(options),
                        }
                    )
                    # некорректный ответ → нейтральный
                    continue

                responses[task.id]['text'] = json.dumps(values)
                continue

            # ===== TEXT / OTHER =====
            if field_name in request.POST:
                text_value = request.POST.get(field_name, '').strip()
                if text_value:
                    responses[task.id]['text'] = text_value

        return responses

    def _save_student_responses(self, enrollment, responses):

        """
        Сохраняет ответы студента в базу данных с защитой от дубликатов
        """

        student = enrollment.student
        task_ids = list(responses.keys())

        existing_responses = {
            r.task_id: r
            for r in StudentTaskResponse.objects.filter(
                student=student,
                task_id__in=task_ids,
            )
        }

        for task_id, response_data in responses.items():
            response_text = response_data.get("text", "")
            audio_file = response_data.get("audio_file")

            existing_response = existing_responses.get(task_id)
            if existing_response:
                # Обновляем только если разрешено по статусу урока
                if enrollment.lesson_status in ["ACTIVE", "ERROR"]:
                    logger.debug(
                        f"Updating existing response {existing_response.id} for task {task_id}"
                    )

                    existing_response.response_text = response_text or existing_response.response_text
                    if audio_file:
                        existing_response.audio_file = audio_file

                    existing_response.submitted_at = timezone.now()
                    existing_response.save(update_fields=[
                        "response_text",
                        "audio_file",
                        "submitted_at",
                    ])
                else:
                    logger.warning(
                        f"Attempt to modify response for lesson in {enrollment.lesson_status} status"
                    )

            else:
                # Создаём новый ответ
                logger.info(
                    f"Creating new response for task {task_id}, student {student.id}"
                )
                st = StudentTaskResponse.objects.create(
                    enrollment=enrollment,
                    student=student,
                    task_id=task_id,
                    response_text=response_text,
                    audio_file=audio_file,
                )

    def _get_progress_data(self, learning_path, current_node):
        """
        Возвращает словарь с данными для отображения прогресса:
        - progress_percent: общий процент завершения пути
        - progress_details.total_lessons: общее количество уроков (без preview-нод)
        - learning_state.current_lesson.order: порядковый номер текущего урока
        """
        if not learning_path.nodes:
            return {
                "progress_percent": 0,
                "total_lessons": 0,
                "current_lesson": 0
            }

        # Фильтруем только учебные ноды (исключаем preview и служебные)
        lesson_nodes = [
            node for node in learning_path.nodes
        ]

        # 1. Общий прогресс по всем нодам (включая preview)
        completed_count = sum(1 for n in learning_path.nodes if n["status"] == "completed")
        total_nodes = len(learning_path.nodes)
        progress_percent = round((completed_count / total_nodes) * 100, 1) if total_nodes else 0

        # 2. Порядковый номер текущего урока среди учебных материалов
        try:
            current_index = next(
                i for i, node in enumerate(lesson_nodes)
                if node.get("id") == current_node.get("id")
            )
            current_order = current_index + 1  # нумерация с 1
        except StopIteration:
            current_order = 1  # если не найден - считаем первым

        # 3. Общее количество учебных уроков
        total_lessons = len(lesson_nodes)

        return {
            "progress_percent": progress_percent,
            "total_lessons": total_nodes,
            "current_lesson": current_order
        }

    def _handle_error(self, request, error_msg, status_code=400):
        """Единая обработка ошибок для AJAX и обычных запросов"""
        is_ajax = (
                request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
                request.content_type == 'application/json'
        )
        if is_ajax:
            return JsonResponse({'error': error_msg}, status=status_code)
        messages.error(request, error_msg)
        return redirect('curriculum:course_list')  # или назад на форму

    def _handle_success(self, request, success_msg, redirect_url):
        """Единая обработка успеха"""
        is_ajax = (
                request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
                request.content_type == 'application/json'
        )
        if is_ajax:
            return JsonResponse({
                'status': 'success',
                'message': success_msg,
                'redirect_url': redirect_url
            })
        messages.success(request, success_msg)
        return redirect(redirect_url)


class LessonHistoryView(LoginRequiredMixin, ChatContextMixin, DetailView):
    model = Lesson
    template_name = 'curriculum/lesson_history.html'
    queryset = Lesson.objects.prefetch_related("learning_objectives")

    def get_queryset(self):
        return Lesson.objects.select_related("course")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        lesson = self.object

        # 1. Получаем зачисление с предзагрузкой связанных данных
        enrollment = (
            Enrollment.objects
            .select_related("student", "course", "learning_path")
            .filter(
                course=lesson.course,
                student__user=self.request.user,
                is_active=True,
            )
            .first()
        )

        if not enrollment:
            context["enrollment"] = None
            return context

        # 2. Получаем LearningPath для времени занятия
        learning_path = getattr(enrollment, 'learning_path', None)

        # 3. Находим текущий узел для получения времени
        current_node = None
        print(learning_path.nodes)
        if learning_path and learning_path.nodes:
            for node in learning_path.nodes:
                if node.get('lesson_id') == lesson.id and node.get('status') == 'completed':
                    current_node = node
                    break
        if current_node:
            # 4. Получаем ответы студента с оценками одним запросом
            student_responses = (
                StudentTaskResponse.objects
                .filter(enrollment=enrollment, task__lesson=lesson)
                .select_related("assessment", "task")
                .order_by("task__order")
            )

            # 5. Подсчитываем статистику заданий
            total_tasks_count = Task.objects.filter(lesson=lesson, is_active=True).count()

            # Задания считаются выполненными, если есть оценка (is_correct не None)
            completed_tasks_count = sum(
                1 for resp in student_responses
                if resp.assessment and resp.assessment.is_correct is not None
            )

            # 6. Получаем все задания урока с предзагрузкой ответов
            tasks = (
                Task.objects
                .filter(lesson=lesson, is_active=True)
                .order_by("order")
                .prefetch_related(
                    Prefetch(
                        "student_response",
                        queryset=StudentTaskResponse.objects.filter(
                            enrollment=enrollment
                        ).select_related("assessment"),
                        to_attr="student_responses_for_enrollment",
                    )
                )
            )

            # 7. Получаем оценку урока
            lesson_assessment = (
                LessonAssessmentResult.objects
                .filter(enrollment=enrollment, lesson=lesson)
                .first()
            )

            # 8. Рассчитываем время занятия
            duration = None
            if current_node and current_node.get('completed_at'):
                from datetime import datetime
                completed_at = datetime.fromisoformat(current_node['completed_at'].replace('Z', '+00:00'))
                created_at = datetime.fromisoformat(current_node['created_at'].replace('Z', '+00:00'))
                duration = completed_at - created_at

            # ============================================
            # 9. ПОЛУЧАЕМ СНИМКИ НАВЫКОВ
            # ============================================

            skill_labels = [skill.capitalize() for skill in SkillDomain.values]
            # Текущий снимок навыков после урока (с привязкой к уроку)
            current_snapshot = (
                SkillSnapshot.objects
                .filter(
                    enrollment=enrollment,
                    associated_lesson=lesson,
                    snapshot_context="POST_LESSON"
                )
                .order_by('-snapshot_at')
                .first()
            )

            # Предыдущий снимок (до этого урока) для сравнения прогресса
            previous_snapshot = None
            initial_skill_snapshot = {}
            if current_snapshot:
                previous_snapshot = (
                    SkillSnapshot.objects
                    .filter(
                        enrollment=enrollment,
                        snapshot_at__lt=current_snapshot.snapshot_at
                    )
                    .order_by('-snapshot_at')
                    .first()
                )

                initial_skill_snapshot = {
                    "skills": {
                        skill: getattr(previous_snapshot, skill)
                        for skill in SkillDomain.values
                    },
                    'timestamp': previous_snapshot.snapshot_at.isoformat(),
                    'context': previous_snapshot.snapshot_context
                }

            # Формируем данные для чарта — всегда используем последний снимок
            if current_snapshot:
                skill_snapshot = {
                    "skills": {
                        skill: getattr(current_snapshot, skill)
                        for skill in SkillDomain.values
                    },
                    'timestamp': current_snapshot.snapshot_at.isoformat(),
                    'context': current_snapshot.snapshot_context
                }
            else:
                # Теоретически недостижимо при корректной работе сигналов
                # Но оставляем защиту на случай ошибок
                skill_snapshot = {
                    'skills': {skill: 0.5 for skill in list(SkillDomain.values)},
                    'timestamp': None,
                    'context': 'fallback'
                }

            # Сравнение прогресса от первого пред уроком к снимку завершения урока
            skill_comparisons = []
            if current_snapshot and previous_snapshot and current_snapshot.id != previous_snapshot.id:

                for skill_name in list(SkillDomain.values):
                    current = getattr(current_snapshot, skill_name, 0.0)
                    initial = getattr(previous_snapshot, skill_name, 0.0)

                    # Защита от некорректных значений (должны быть в диапазоне 0.0–1.0)
                    current = max(0.0, min(1.0, current))
                    initial = max(0.0, min(1.0, initial))

                    delta = current - initial
                    skill_comparisons.append({
                        'name': skill_name.capitalize(),
                        'current': current,
                        'initial': initial,
                        'delta': delta,
                        'delta_positive': delta > 0,
                        'delta_formatted': f"{delta:+.2f}"
                    })
                    context.update({
                        "lesson": lesson,
                        "enrollment": enrollment,
                        "tasks": tasks,
                        "lesson_assessment": lesson_assessment,
                        "completed_tasks_count": completed_tasks_count,
                        "total_tasks_count": total_tasks_count,
                        "lesson_duration": duration,
                        "current_node": current_node,
                        # Снимки навыков
                        "skill_snapshot": skill_snapshot,
                        "initial_skill_snapshot": initial_skill_snapshot,
                        "skill_comparisons": skill_comparisons,
                        "skill_labels": skill_labels,
                    })

        context.update({
            "lesson": lesson,
            "enrollment": enrollment,
        })

        return context


class CourseHistoryView(LoginRequiredMixin, ChatContextMixin, DetailView):
    model = Course
    template_name = 'curriculum/course_history.html'
    context_object_name = 'course'

    def get_queryset(self):
        return Course.objects.prefetch_related("professional_tags", )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        course = self.object
        user = self.request.user

        # Получаем зачисление пользователя на курс
        enrollment = (
            Enrollment.objects
            .select_related("student")
            .filter(
                course=course,
                student__user=user,
                is_active=True
            )
            .first()
        )

        if not enrollment:
            context["enrollment"] = None
            context["learning_path"] = None
            context["progress"] = None
            context["nodes"] = []
            return context

        # Получаем учебный путь
        learning_path = getattr(enrollment, 'learning_path', None)

        if not learning_path or not learning_path.nodes:
            context["enrollment"] = enrollment
            context["learning_path"] = None
            context["progress"] = None
            context["nodes"] = []
            return context

        progress_data = LearningPathProgressService.get_core_progress(learning_path)
        progress_data['percentage'] = round(
            (progress_data['completed_lessons'] / progress_data['total_lessons'] * 100)
            if progress_data['total_lessons'] > 0 else 0
        )

        # Статистика по типам узлов
        nodes = learning_path.nodes

        core_nodes = [n for n in nodes if n.get('type') == 'core']
        remedial_nodes = [n for n in nodes if n.get('type') == 'remedial']
        diagnostic_nodes = [n for n in nodes if n.get('type') == 'diagnostic']

        core_stats = {
            'total': len(core_nodes),
            'completed': len([n for n in core_nodes if n.get('status') == 'completed'])
        }

        remedial_stats = {
            'total': len(remedial_nodes),
            'completed': len([n for n in remedial_nodes if n.get('status') == 'completed'])
        }

        diagnostic_stats = {
            'total': len(diagnostic_nodes),
            'completed': len([n for n in diagnostic_nodes if n.get('status') == 'completed'])
        }

        completed_lesson_ids = [
            node['lesson_id']
            for node in nodes
            if node.get('status') == 'completed' and node.get('lesson_id')
        ]

        all_lesson_ids = [
            node['lesson_id']
            for node in nodes
            if node.get('lesson_id')
        ]

        # Получаем ВСЕ оценки одним запросом
        assessment_map = {}
        if completed_lesson_ids:
            assessments = LessonAssessmentResult.objects.filter(
                enrollment=enrollment,
                lesson_id__in=completed_lesson_ids
            ).select_related('lesson')
            assessment_map = {ass.lesson_id: ass for ass in assessments}

        # Получаем ВСЕ уроки одним запросом
        lesson_map = {}
        if all_lesson_ids:
            lessons = Lesson.objects.filter(
                id__in=all_lesson_ids
            ).prefetch_related(
                'learning_objectives',
            )

            lesson_map = {lesson.id: lesson for lesson in lessons}

        # Обогащаем узлы
        enriched_nodes = []
        for node in nodes:
            enriched_node = node.copy()

            # Добавляем оценку (если есть)
            lesson_id = node.get('lesson_id')
            if lesson_id:
                enriched_node['assessment_result'] = assessment_map.get(lesson_id)
                enriched_node['lesson'] = lesson_map.get(lesson_id)

            enriched_nodes.append(enriched_node)

        # ДОБАВЛЯЕМ СНИМКИ НАВЫКОВ ДЛЯ РАДАР-ЧАРТА

        skill_labels = [skill.capitalize() for skill in SkillDomain.values]
        # Последний снимок (текущий уровень) — ВСЕГДА существует благодаря сигналу
        latest_snapshot = (
            SkillSnapshot.objects
            .filter(enrollment=enrollment)
            .order_by('-snapshot_at')
            .first()
        )

        # Начальный снимок (тот же самый при первом зачислении, или первый в истории)
        initial_snapshot = (
            SkillSnapshot.objects
            .filter(enrollment=enrollment)
            .order_by('snapshot_at')
            .first()
        )
        if initial_snapshot:
            initial_skill_snapshot = {
                "skills": {
                    skill: getattr(initial_snapshot, skill)
                    for skill in SkillDomain.values
                },
                'timestamp': initial_snapshot.snapshot_at.isoformat(),
                'context': initial_snapshot.snapshot_context
            }

        else:
            # Теоретически недостижимо при корректной работе сигналов
            # Но оставляем защиту на случай ошибок
            initial_skill_snapshot = {
                'skills': {skill: 0.5 for skill in list(SkillDomain.values)},
                'timestamp': None,
                'context': 'fallback'
            }

        # Формируем данные для чарта — всегда используем последний снимок
        if latest_snapshot:
            skill_snapshot = {
                "skills": {
                    skill: getattr(latest_snapshot, skill)
                    for skill in SkillDomain.values
                },
                'timestamp': latest_snapshot.snapshot_at.isoformat(),
                'context': latest_snapshot.snapshot_context
            }
        else:
            # Теоретически недостижимо при корректной работе сигналов
            # Но оставляем защиту на случай ошибок
            skill_snapshot = {
                'skills': {skill: 0.5 for skill in list(SkillDomain.values)},
                'timestamp': None,
                'context': 'fallback'
            }

        # Сравнение прогресса от первого к последнему снимку
        skill_comparisons = []
        if latest_snapshot and initial_snapshot and latest_snapshot.id != initial_snapshot.id:

            for skill_name in list(SkillDomain.values):
                current = getattr(latest_snapshot, skill_name, 0.0)
                initial = getattr(initial_snapshot, skill_name, 0.0)

                # Защита от некорректных значений (должны быть в диапазоне 0.0–1.0)
                current = max(0.0, min(1.0, current))
                initial = max(0.0, min(1.0, initial))

                delta = current - initial
                skill_comparisons.append({
                    'name': skill_name.capitalize(),
                    'current': current,
                    'initial': initial,
                    'delta': delta,
                    'delta_positive': delta > 0,
                    'delta_formatted': f"{delta:+.2f}"
                })

        context.update({
            "enrollment": enrollment,
            "learning_path": learning_path,
            "progress": progress_data,
            "nodes": enriched_nodes,
            "core_stats": core_stats,
            "remedial_stats": remedial_stats,
            "diagnostic_stats": diagnostic_stats,
            "current_node": learning_path.current_node,
            "skill_snapshot": skill_snapshot,
            "initial_skill_snapshot": initial_skill_snapshot,
            "skill_comparisons": skill_comparisons,
            "skill_labels": skill_labels,
        })

        return context


class CheckLessonAssessmentView(LoginRequiredMixin, ChatContextMixin, View):
    """
    Проверяет статус оценки урока.
    Поддерживает как AJAX (JSON), так и обычные GET-запросы с рендерингом.
    """
    learning_path_progress_service = LearningPathProgressService

    def get(self, request, enrollment_id):
        """Обработка GET-запросов для проверки статуса оценки"""
        try:
            enrollment = Enrollment.objects.select_related(
                'student', 'course', 'current_lesson'
            ).get(
                id=enrollment_id,
                student=request.user.student,
                is_active=True
            )
        except Enrollment.DoesNotExist:
            error_msg = 'Зачисление не найдено или доступ запрещен'
            return self._handle_error(request, error_msg, 403)

        # Определяем тип ответа
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        # Если урок не на оценке, перенаправляем на основную страницу урока
        if enrollment.lesson_status != 'PENDING_ASSESSMENT':
            if is_ajax:
                return JsonResponse({
                    'status': 'REDIRECT',
                    'redirect_url': reverse('curriculum:learning_session', kwargs={'pk': enrollment_id})
                })
            return redirect('curriculum:learning_session', pk=enrollment_id)

        # Получаем статус оценки
        assessment_status = self._get_assessment_status(enrollment)

        # Для AJAX возвращаем JSON
        if is_ajax:
            return JsonResponse(assessment_status)

        current_node_index = enrollment.learning_path.current_node_index
        current_node = enrollment.learning_path.nodes[current_node_index]
        current_lesson = Lesson.objects.get(id=current_node.get("lesson_id"))

        l_service = self.learning_path_progress_service
        course_progress = l_service.get_core_progress(enrollment.learning_path)

        context = super().get_context_data()

        lesson_report_url = reverse_lazy("curriculum:lesson_history", kwargs={"pk": current_lesson.pk})

        context.update({
            'enrollment': enrollment,
            'current_lesson': current_lesson,
            'task_id': enrollment.assessment_job_id,
            'course': enrollment.course,
            'course_progress': course_progress,
            'assessment_status': assessment_status,
            'assessment_started_at': enrollment.assessment_started_at,
            'lesson_report_url': lesson_report_url,
        })

        return render(
            request,
            'curriculum/lesson_pending_assessment.html',
            context
        )

    def _get_assessment_status(self, enrollment):
        """Получает детальный статус оценки"""
        if not enrollment.assessment_job_id:
            return {
                'status': enrollment.lesson_status,
                'can_proceed': enrollment.lesson_status == 'COMPLETED',
                'message': 'Оценка не найдена'
            }

        try:
            job = AsyncResult(enrollment.assessment_job_id)

            if job.ready():
                if job.successful():
                    # Обновляем статус при успешном завершении
                    enrollment.lesson_status = 'COMPLETED'
                    enrollment.save(update_fields=['lesson_status'])

                    return {
                        'status': 'COMPLETED',
                        'message': 'Оценка успешно завершена',
                        'can_proceed': True,
                        'redirect_url': reverse('curriculum:learning_session', kwargs={'pk': enrollment.id})
                    }
                else:
                    # Обработка ошибки задачи
                    error_message = str(job.result) if job.result else "Неизвестная ошибка"
                    return {
                        'status': 'ERROR',
                        'error_message': error_message,
                        'can_proceed': False,
                        'message': 'Произошла ошибка при оценке ваших ответов'
                    }

            # Задача еще выполняется
            progress = job.info or {'current': 0, 'total': 1}  # дефолт 1, чтобы не делить на 0

            # Если есть LearningPath — берём реальное количество заданий в текущем уроке
            if hasattr(enrollment, 'learning_path') and enrollment.learning_path.current_node:
                try:
                    lesson_id = enrollment.learning_path.current_node["lesson_id"]
                    lesson = Lesson.objects.get(id=lesson_id)
                    total_tasks = lesson.tasks.filter(is_active=True).count()
                    progress['total'] = max(1, total_tasks)
                except (Lesson.DoesNotExist, KeyError):
                    pass  # оставляем дефолт 1

            current = progress.get('current', 0)
            total = progress.get('total', 1)

            elapsed_min = ((timezone.now() - enrollment.assessment_started_at).total_seconds()
                           / 60) if enrollment.assessment_started_at else 0
            remaining = max(0, total - elapsed_min)  # 1 мин на задание — пример

            return {
                'status': 'PENDING_ASSESSMENT',
                'progress': min(99, int(current / total * 100)) if total > 0 else 0,
                'current': current,
                'total': total,
                'estimated_remaining': round(remaining, 1),
                'can_proceed': False,
                'message': f'Оценка идёт... Осталось ~{round(remaining, 1)} мин'
            }

        except Exception as e:
            logger.error(f"Error checking assessment status: {str(e)}", exc_info=True)
            return {
                'status': 'ERROR',
                'error_message': 'Ошибка при проверке статуса оценки',
                'can_proceed': False,
                'message': 'Произошла техническая ошибка. Пожалуйста, попробуйте позже.'
            }

    def _build_template_context(self, enrollment, assessment_status):
        """Создает контекст для шаблона"""
        return

    def _handle_error(self, request, error_msg, status_code):
        """Единая обработка ошибок для AJAX и обычных запросов"""
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'error': error_msg}, status=status_code)
        else:
            messages.error(request, error_msg)
            return redirect('curriculum:course_list')
