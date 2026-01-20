import json
import logging
import math
from pprint import pprint

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
from django.views.generic import DetailView
from django.http import JsonResponse, Http404

from chat.views import ChatContextMixin
# from curriculum.config.dependency_factory import CurriculumServiceFactory
from curriculum.models.content.task import ResponseFormat
from curriculum.models.student.enrollment import Enrollment
from ..forms import LessonTasksForm

from curriculum.tasks import assess_lesson_tasks, launch_full_assessment
from ..models.learning_process.lesson_event_log import LessonEventType

logger = logging.getLogger(__name__)

#
# class LearningSessionView(LoginRequiredMixin, ChatContextMixin, DetailView):
#     """
#     Представление для сессии обучения.
#     Обрабатывает как отображение урока (GET), так и отправку ответов (POST).
#     """
#     model = Enrollment
#     template_name = 'curriculum/learning_session.html'
#     context_object_name = 'enrollment'
#
#     def __init__(self, **kwargs):
#         super().__init__(**kwargs)
#         self.learning_service = CurriculumServiceFactory().create_learning_service()
#         self.enrollment_service = self.learning_service.enrollment_service
#         self.curriculum_query = self.learning_service.curriculum_query
#
#     def get_queryset(self):
#         """Фильтруем только активные зачисления текущего студента"""
#         return Enrollment.objects.filter(
#             student=self.request.user.student,
#             is_active=True
#         ).select_related(
#             'course',
#             'current_lesson'
#         ).prefetch_related(
#             'current_lesson__tasks'
#         )
#
#     def get_object(self, queryset=None):
#         obj = super().get_object(queryset)
#         # Проверяем, что зачисление принадлежит текущему студенту
#         if obj.student != self.request.user.student:
#             raise PermissionDenied("Вы не можете получить доступ к этой учебной сессии")
#         return obj
#
#     def get(self, request, *args, **kwargs):
#         """Обработка GET-запроса - отображение урока и заданий"""
#         self.object = self.get_object()
#         context = self.get_context_data(object=self.object)
#         return self.render_to_response(context)
#
#     def post(self, request, *args, **kwargs):
#         """Обработка POST-запроса - отправка ответов на задания урока"""
#         self.object = self.get_object()
#         enrollment = self.object
#
#         # Проверяем, не находится ли урок уже в процессе оценки
#         if enrollment.lesson_status == 'PENDING_ASSESSMENT':
#             error_msg = 'Этот урок уже находится на оценке. Пожалуйста, подождите завершения.'
#             messages.error(request, error_msg)
#             return redirect('curriculum:learning_session', pk=enrollment.id)
#
#         if not enrollment.current_lesson:
#             error_msg = 'У зачисления нет текущего урока'
#             messages.error(request, error_msg)
#             return redirect('curriculum:course_list')
#
#         lesson_tasks = Task.objects.filter(
#             lesson=enrollment.current_lesson,
#             is_active=True
#         )
#
#         if not lesson_tasks.exists():
#             error_msg = 'В уроке нет активных заданий'
#             messages.error(request, error_msg)
#             return redirect('curriculum:learning_session', pk=enrollment.id)
#
#         # Создаем и валидируем форму
#         form = LessonTasksForm(
#             request.POST,
#             request.FILES,
#             lesson=enrollment.current_lesson,
#             completed_task_ids=set()
#         )
#
#         if not form.is_valid():
#             # При ошибке валидации возвращаем ту же страницу с сообщениями об ошибках
#             print(form.errors)
#             context = self.get_context_data(object=enrollment)
#             context['lesson_form'] = form  # Передаем форму с ошибками
#
#             # Дополнительно передаем ошибки валидации для отображения
#             messages.error(request, 'Пожалуйста, ответьте на все задания')
#             return self.render_to_response(context)
#
#         # Если форма валидна, собираем ответы
#         responses = self._collect_responses(request, lesson_tasks)
#
#         try:
#             # 1. Сохраняем ответы
#             self._save_student_responses(enrollment, responses)
#
#             # 2. Обновляем статус урока
#             enrollment.lesson_status = 'PENDING_ASSESSMENT'
#             enrollment.assessment_started_at = timezone.now()
#             enrollment.save(update_fields=['lesson_status', 'assessment_started_at'])
#
#             # 3. Запускаем фоновую оценку
#             assessment_job_id = self._start_assessment(enrollment, responses)
#             if assessment_job_id:
#                 enrollment.assessment_job_id = assessment_job_id
#                 enrollment.save(update_fields=['assessment_job_id'])
#
#             # 4. PRG паттерн: перенаправляем на страницу проверки статуса оценки
#             redirect_url = reverse('curriculum:check_lesson_assessment', kwargs={'enrollment_id': enrollment.id})
#             messages.success(request, 'Ваши ответы успешно сохранены и отправлены на оценку.')
#             return redirect(redirect_url)
#
#         except Exception as e:
#             logger.error(f"Error processing lesson responses: {str(e)}", exc_info=True)
#             enrollment.lesson_status = 'ACTIVE'  # Возвращаем в активный статус при ошибке
#             enrollment.save(update_fields=['lesson_status'])
#
#             # При ошибке сохранения возвращаем ту же страницу с сообщением об ошибке
#             context = self.get_context_data(object=enrollment)
#             messages.error(request, f'Ошибка сохранения ответов: {str(e)}')
#             return self.render_to_response(context)
#
#     def get_context_data(self, **kwargs):
#         context = super().get_context_data(**kwargs)
#         context.update(self.get_chat_context(self.request))
#         enrollment = self.object
#
#         # Блокируем доступ к уроку если он находится на оценке
#         if enrollment.lesson_status == 'PENDING_ASSESSMENT':
#             context['lesson_blocked'] = True
#             context['block_message'] = ('Этот урок находится на оценке. Пожалуйста, '
#                                         'подождите завершения или проверьте статус.')
#             context['assessment_started_at'] = enrollment.assessment_started_at
#             context['estimated_completion_time'] = max(1, enrollment.current_lesson.tasks.count())
#
#             return context
#
#         # Если нет текущего урока - получаем первый урок курса
#         if not enrollment.current_lesson:
#             first_lesson = self.learning_service.curriculum_query.get_current_lesson(enrollment)
#             if first_lesson:
#                 enrollment.current_lesson = first_lesson
#                 enrollment.save(update_fields=['current_lesson'])
#
#         # Получаем текущее состояние обучения
#         context['learning_state'] = self.learning_service.get_current_state(enrollment.id)
#
#         # Получаем ВСЕ задания текущего урока
#         student_responses_qs = StudentTaskResponse.objects.filter(
#             student=enrollment.student
#         )
#
#         context['lesson_tasks'] = (
#             enrollment.current_lesson.tasks
#             .filter(is_active=True)
#             .prefetch_related(
#                 Prefetch(
#                     'student_response',  # related_name в модели Task
#                     queryset=student_responses_qs,
#                     to_attr='student_answers'
#                 )
#             )
#         )
#
#         for task in context['lesson_tasks']:
#             task.student_answer = task.student_answers[0] if task.student_answers else None
#
#         # Получаем историю ответов по уроку
#         context['completed_tasks'] = self._get_completed_tasks(enrollment)
#
#         # Рассчитываем прогресс по уроку
#         context['lesson_progress'] = self._calculate_lesson_progress(
#             enrollment,
#             context['lesson_tasks'],
#             context['completed_tasks']
#         )
#
#         # Получаем теорию урока
#         context['lesson_theory'] = enrollment.current_lesson.theory_content
#
#         # Получаем детальную информацию о прогрессе по курсу
#         context['progress_details'] = self.enrollment_service.get_course_progress(enrollment)
#
#         # Создаем форму для заданий (если не передана из POST-обработчика)
#         if 'lesson_form' not in context:
#             context['lesson_form'] = LessonTasksForm(
#                 lesson=enrollment.current_lesson,
#                 completed_task_ids=set(context['completed_tasks'])
#             )
#
#         return context
#
#     def _collect_responses(self, request, lesson_tasks):
#         """
#         Собирает ответы из запроса.
#
#         Принцип:
#         - КАЖДОЕ задание попадает в responses
#         - Пустой / некорректный ответ → text="" / audio_file=None
#         - Оценщик сам решает, как это интерпретировать (neutral)
#         """
#         responses: dict[int, dict] = {}
#
#         for task in lesson_tasks:
#             field_name = f'task_{task.id}'
#             audio_field = f'task_{task.id}_audio'
#
#             # === Значение по умолчанию (пустой ответ) ===
#             responses[task.id] = {
#                 'text': '',
#                 'audio_file': None
#             }
#
#             # ===== AUDIO =====
#             if task.response_format == 'audio':
#                 if audio_field in request.FILES:
#                     responses[task.id]['audio_file'] = request.FILES[audio_field]
#                 continue
#
#             # ===== MULTIPLE CHOICE =====
#             if task.response_format == 'multiple_choice':
#                 values = request.POST.getlist(field_name)
#
#                 if not values:
#                     # пустой ответ → останется нейтральным
#                     continue
#
#                 options = set(task.content.get('options', []))
#                 invalid = [v for v in values if v not in options]
#
#                 if invalid:
#                     logger.warning(
#                         "Invalid multiple_choice values",
#                         extra={
#                             "task_id": task.id,
#                             "invalid": invalid,
#                             "allowed": list(options),
#                         }
#                     )
#                     # некорректный ответ → нейтральный
#                     continue
#
#                 responses[task.id]['text'] = json.dumps(values)
#                 continue
#
#             # ===== TEXT / OTHER =====
#             if field_name in request.POST:
#                 text_value = request.POST.get(field_name, '').strip()
#                 if text_value:
#                     responses[task.id]['text'] = text_value
#
#         return responses
#
#     def _validate_responses(self, responses, lesson_tasks):
#         """Валидация собранных ответов"""
#         total_tasks = lesson_tasks.count()
#         completed_count = len(responses)
#
#         # Минимум 30% заданий должно быть выполнено (вместо жестких 50%)
#         min_required = max(1, int(total_tasks * 0.3))
#
#         if completed_count < min_required:
#             return {
#                 'is_valid': False,
#                 'error': f'Заполните хотя бы {min_required} из {total_tasks} заданий урока'
#             }
#
#         return {
#             'is_valid': True,
#             'completed_count': completed_count,
#             'total_count': total_tasks
#         }
#
#     def _save_student_responses(self, enrollment, responses):
#         """
#         Сохраняет ответы студента в базу данных с защитой от дубликатов
#         """
#         from curriculum.models.assessment.student_response import StudentTaskResponse
#
#         student = enrollment.student
#         task_ids = list(responses.keys())
#
#         existing_responses = {
#             r.task_id: r
#             for r in StudentTaskResponse.objects.filter(
#                 student=student,
#                 task_id__in=task_ids,
#             )
#         }
#
#         for task_id, response_data in responses.items():
#             response_text = response_data.get("text", "")
#             audio_file = response_data.get("audio_file")
#
#             existing_response = existing_responses.get(task_id)
#
#             if existing_response:
#                 # Обновляем только если разрешено по статусу урока
#                 if enrollment.lesson_status in ["ACTIVE", "ERROR"]:
#                     logger.info(
#                         f"Updating existing response {existing_response.id} for task {task_id}"
#                     )
#
#                     existing_response.response_text = response_text or existing_response.response_text
#                     if audio_file:
#                         existing_response.audio_file = audio_file
#
#                     existing_response.submitted_at = timezone.now()
#                     existing_response.save(update_fields=[
#                         "response_text",
#                         "audio_file",
#                         "submitted_at",
#                     ])
#                 else:
#                     logger.warning(
#                         f"Attempt to modify response for lesson in {enrollment.lesson_status} status"
#                     )
#
#             else:
#                 # Создаём новый ответ
#                 logger.info(
#                     f"Creating new response for task {task_id}, student {student.id}"
#                 )
#                 st = StudentTaskResponse.objects.create(
#                     student=student,
#                     task_id=task_id,
#                     response_text=response_text,
#                     audio_file=audio_file,
#                 )
#
#     def _start_assessment(self, enrollment, responses):
#         """
#         Запускает фоновый оркестратор с транскрипцией + оценкой заданий
#
#         Args:
#             enrollment: Enrollment объект
#             responses: Словарь с ответами студента
#
#         Returns:
#             str: ID задачи Celery или None при ошибке
#         """
#         try:
#             job = launch_full_assessment.delay(enrollment.id)
#             if job:
#                 logger.info(f"Started full assessment chain {job.id} for enrollment {enrollment.id}")
#                 return job.id
#             else:
#                 return None
#         except Exception as e:
#             logger.error(f"Failed to start full assessment: {str(e)}")
#             return None
#
#     def _get_completed_tasks(self, enrollment):
#         """Получает ID выполненных заданий в текущем уроке"""
#         return StudentTaskResponse.objects.filter(
#             student=enrollment.student,
#             task__lesson=enrollment.current_lesson
#         ).values_list('task_id', flat=True)
#
#     def _calculate_lesson_progress(self, enrollment, all_tasks, completed_task_ids):
#         """Рассчитывает прогресс по уроку в процентах"""
#         total_tasks = len(all_tasks)
#         completed_count = len([task for task in all_tasks if task.id in completed_task_ids])
#
#         if total_tasks == 0:
#             return 0
#
#         return round((completed_count / total_tasks) * 100, 1)


class LearningSessionView(LoginRequiredMixin, View):
    """
    Class-Based View для отображения и завершения текущего урока.
    GET — показывает урок
    POST — обрабатывает отправку ответов, оценку и завершение урока
    """

    def get(self, request, pk):
        enrollment = self._get_enrollment(pk)
        lesson, current_node = self._get_current_lesson_and_node(enrollment)

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
        form = LessonTasksForm(lesson=lesson)

        context = {
            'enrollment': enrollment,
            'lesson': lesson,
            'current_node': current_node,
            'next_node': enrollment.learning_path.next_node,
            'path_type': enrollment.learning_path.path_type,
            'progress_percent': self._calculate_path_progress(enrollment.learning_path),
            'form': form,
            'is_preview': current_node.get("type") == "preview",
            'recommended_reason': current_node.get("reason", "")
        }

        return render(request, 'curriculum/learning_session.html', context)

    def post(self, request, pk):
        enrollment = self._get_enrollment(pk)
        lesson, current_node = self._get_current_lesson_and_node(enrollment)

        # Проверяем, что это текущий урок
        if current_node["lesson_id"] != lesson.id:
            return JsonResponse({'error': 'Это не текущий урок в вашем пути'}, status=400)

        # 1. Валидация ответов через форму
        form = LessonTasksForm(request.POST, request.FILES, lesson=lesson)

        if not form.is_valid():
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': 'Некорректные данные в ответах', 'errors': form.errors}, status=400)
            messages.error(request, "Пожалуйста, заполните все обязательные поля")
            return redirect(request.path)

        # 2. Сохранение ответов студента (через существующий сервис)
        lesson_tasks = Task.objects.filter(
                        lesson=enrollment.current_lesson,
                        is_active=True
                    )
        responses = self._collect_responses(request, lesson_tasks)
        self._save_student_responses(enrollment, responses)

        # 3. Запуск оценки (асинхронно через Celery)
        assessment_service = LessonAssessmentService()
        assessment_service.assess_lesson_async(enrollment, lesson, responses)

        # 4. Обновление статуса узла в LearningPath
        path = enrollment.learning_path
        current_index = path.current_node_index
        path.nodes[current_index]["status"] = "completed"
        path.nodes[current_index]["completed_at"] = timezone.now().isoformat()
        path.save()

        # 5. Логирование события завершения
        LessonEventService.create_event(
            student=enrollment.student,
            enrollment=enrollment,
            lesson=lesson,
            event_type=LessonEventType.COMPLETE,
            channel="WEB",
            metadata={
                "node_id": current_node["node_id"],
                "score_estimate": 0.85,  # Будет обновлено после оценки
                "tasks_completed": len(responses)
            }
        )

        # 6. Переход к следующему узлу (если есть)
        if path.next_node:
            path.current_node_index += 1
            path.save()

        # 7. Ответ пользователю
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        if is_ajax:
            return JsonResponse({
                'message': 'Ответы отправлены на оценку. Урок завершён!',
                'status': 'completed',
                'next_lesson_url': f'/curriculum/session/{enrollment.id}/'  # Перезагрузка покажет следующий
            })

        messages.success(request, f"Урок «{lesson.title}» успешно завершён! Переходим дальше.")
        return redirect('curriculum:learning_session', pk=enrollment.id)

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
            lesson = Lesson.objects.get(id=current_node["lesson_id"], is_active=True)
        except Lesson.DoesNotExist:
            raise Http404(f"Урок {current_node['lesson_id']} не найден")

        return lesson, current_node

    def _collect_and_save_responses(self, request, lesson, student):
        """Собирает и сохраняет ответы студента (примерная реализация)"""
        responses = {}
        for task in lesson.tasks.filter(is_active=True):
            field_name = f'task_{task.id}'
            if field_name in request.POST:
                responses[task.id] = request.POST[field_name]
            elif f'{field_name}_audio' in request.FILES:
                responses[task.id] = request.FILES[f'{field_name}_audio']
        # Здесь вызов сервиса сохранения ответов (StudentTaskResponse)
        # ...
        return responses

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
        from curriculum.models.assessment.student_response import StudentTaskResponse

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
                    logger.info(
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
                    student=student,
                    task_id=task_id,
                    response_text=response_text,
                    audio_file=audio_file,
                )

    def _calculate_path_progress(self, learning_path):
        if not learning_path.nodes:
            return 0
        completed = sum(1 for n in learning_path.nodes if n["status"] == "completed")
        return round((completed / len(learning_path.nodes)) * 100, 1)

class LessonHistoryView(LoginRequiredMixin, ChatContextMixin, DetailView):
    """
    Представление для просмотра истории выполнения заданий в уроке.
    Показывает детальную статистику и позволяет анализировать прогресс.

    URL: /curriculum/session/<enrollment_id>/lesson/<lesson_id>/history/
    """
    model = Enrollment
    template_name = 'curriculum/lesson_history.html'
    context_object_name = 'enrollment'
    pk_url_kwarg = 'enrollment_id'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.learning_service = CurriculumServiceFactory().create_learning_service()
        self.enrollment_service = self.learning_service.enrollment_service
        self.curriculum_query = self.learning_service.curriculum_query

    def get_queryset(self):
        return Enrollment.objects.filter(
            student=self.request.user.student,
            is_active=True
        ).select_related('course')

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if obj.student != self.request.user.student:
            raise PermissionDenied("Вы не можете получить доступ к этой истории урока")
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.get_chat_context(self.request))

        enrollment = self.object
        lesson_id = self.kwargs.get('lesson_id')

        try:
            # Получаем детальную информацию по уроку
            lesson = Lesson.objects.get(id=lesson_id, course=enrollment.course)

            # Получаем полную историю урока
            lesson_history = self.curriculum_query.get_lesson_history(enrollment, lesson)

            context.update({
                'current_lesson': lesson,
                'lesson_history': lesson_history,
                'lesson_number': lesson.order,
                'is_current_lesson': enrollment.current_lesson_id == lesson.id if enrollment.current_lesson else False
            })

        except Lesson.DoesNotExist:
            context['error'] = f"Урок {lesson_id} не найден или недоступен для просмотра"
            logger.warning(f"Lesson {lesson_id} not found for enrollment {enrollment.id}")
        except Exception as e:
            logger.error(f"Error loading lesson history: {str(e)}", exc_info=True)
            context['error'] = "Произошла ошибка при загрузке истории урока. Пожалуйста, попробуйте позже."

        return context


class CourseHistoryView(LoginRequiredMixin, ChatContextMixin, DetailView):
    """
    Представление для просмотра истории пройденных уроков в курсе.
    URL: /curriculum/session/<enrollment_id>/history/
    """
    model = Enrollment
    template_name = 'curriculum/course_history_v1.html'
    context_object_name = 'enrollment'
    pk_url_kwarg = 'enrollment_id'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        factory = CurriculumServiceFactory()
        self.learning_service = factory.create_learning_service()
        self.enrollment_service = self.learning_service.enrollment_service

    def get_queryset(self):
        return Enrollment.objects.filter(
            student=self.request.user.student,
            is_active=True
        ).select_related('course', 'current_lesson')

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if obj.student != self.request.user.student:
            raise PermissionDenied("Вы не можете получить доступ к истории этого курса")
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.get_chat_context(request=self.request))
        enrollment = self.object
        course = enrollment.course
        context['course'] = course

        try:
            # Получаем прогресс по курсу
            progress_details = self.enrollment_service.get_course_progress(enrollment)
            context['progress_details'] = progress_details
            context['overall_progress'] = progress_details.get('progress_percent', 0)
            context['completed_lessons_count'] = progress_details.get('completed_lessons', 0)
            context['total_lessons_count'] = progress_details.get('total_lessons', 0)
            context['is_course_completed'] = progress_details.get('is_course_completed', False)

            # Получаем детальную статистику по каждому уроку
            context['all_lessons'] = self._get_lesson_details(enrollment, course)

            # Считаем статистику по задачам
            context['total_completed_tasks'] = StudentTaskResponse.objects.filter(
                student=enrollment.student,
                task__lesson__course=course,
                task__is_active=True
            ).count()

            # Получаем снимки навыков для визуализации прогресса
            context['skill_snapshots'] = SkillSnapshot.objects.filter(
                student=enrollment.student
            ).order_by('-snapshot_at')[:5]

            # Рассчитываем среднее время на урок
            completed_lessons = Lesson.objects.filter(
                course=course,
                is_active=True,
                order__lt=enrollment.current_lesson.order + 1 if enrollment.current_lesson else 1
            ).prefetch_related('tasks')

            total_time_spent = 0
            completed_lessons_count = 0
            for lesson in completed_lessons:
                total_tasks = lesson.tasks.filter(is_active=True).count()
                completed_tasks = StudentTaskResponse.objects.filter(
                    student=enrollment.student,
                    task__lesson=lesson,
                    task__is_active=True
                ).count()

                if completed_tasks == total_tasks:
                    completed_lessons_count += 1
                    # Оценка времени: 2 минуты на задание
                    total_time_spent += lesson.tasks.filter(is_active=True).count() * 2

            context['average_time_per_lesson'] = round(total_time_spent / completed_lessons_count,
                                                       1) if completed_lessons_count > 0 else 0
            context['total_time_spent'] = total_time_spent

        except Exception as e:
            logger.error(f"Error loading course history for enrollment {enrollment.id}: {str(e)}", exc_info=True)
            context['error'] = f"Ошибка при загрузке истории курса: {str(e)}"
        pprint(context)
        return context

    def _get_lesson_details(self, enrollment, course):
        """
        Возвращает детальную информацию по всем урокам курса:
        - прогресс по каждому уроку
        - статистика по заданиям
        - ссылки на историю урока
        """
        lessons = Lesson.objects.filter(
            course=course,
            is_active=True
        ).order_by('order').prefetch_related('tasks', 'learning_objectives')

        lesson_details = []
        current_lesson_order = enrollment.current_lesson.order if enrollment.current_lesson else 0

        for lesson in lessons:
            # Статистика по заданиям урока
            total_tasks = lesson.tasks.filter(is_active=True).count()
            completed_tasks = StudentTaskResponse.objects.filter(
                student=enrollment.student,
                task__lesson=lesson,
                task__is_active=True
            ).count()

            # Прогресс по уроку
            completion_percent = round((completed_tasks / total_tasks) * 100, 1) if total_tasks > 0 else 0

            # Флаг завершенности урока (простая эвристика - 80% заданий)
            is_completed = completion_percent >= 80

            # Дата последнего ответа
            last_response = StudentTaskResponse.objects.filter(
                student=enrollment.student,
                task__lesson=lesson
            ).order_by('-submitted_at').first()

            # Основные навыки урока
            skill_focus = lesson.skill_focus if hasattr(lesson, 'skill_focus') else []

            responses = StudentTaskResponse.objects.filter(
                student=enrollment.student,
                task__lesson=lesson,
                task__is_active=True
            ).select_related('assessment')

            # Средний балл по уроку (если есть оценки)
            total_score = 0.0
            score_count = 0

            for response in responses:
                assessment = getattr(response, "assessment", None)
                if not assessment:
                    continue

                feedback = getattr(assessment, "structured_feedback", None)
                if not feedback:
                    continue

                skill_eval = feedback.get("skill_evaluation", {})
                if not isinstance(skill_eval, dict):
                    continue

                for skill, data in skill_eval.items():
                    score = data.get("score")
                    if isinstance(score, (int, float)):
                        total_score += score
                        score_count += 1

            avg_score = round(total_score / score_count, 2) if score_count > 0 else 0.0

            lesson_details.append({
                'lesson': lesson,
                'order': lesson.order,
                'total_tasks': total_tasks,
                'completed_tasks': completed_tasks,
                'completion_percent': completion_percent,
                'is_completed': is_completed,
                'is_current': lesson.order == current_lesson_order,
                'last_response_date': last_response.submitted_at if last_response else None,
                'skill_focus': skill_focus,
                'average_score': avg_score,
                'objectives': lesson.learning_objectives.all()
            })

        return lesson_details

#
# class SubmitLessonResponseView(LoginRequiredMixin, ChatContextMixin, View):
#     """
#     Class-based view для обработки ответов на все задания урока.
#     Поддерживает как AJAX (JSON), так и обычные POST-запросы.
#     """
#
#     def post(self, request, enrollment_id):
#         try:
#             enrollment = Enrollment.objects.get(
#                 id=enrollment_id,
#                 student=request.user.student,
#                 is_active=True
#             )
#         except Enrollment.DoesNotExist:
#             error_msg = 'Зачисление не найдено или доступ запрещен'
#             return self._handle_error(request, error_msg, 403)
#
#         if not enrollment.current_lesson:
#             error_msg = 'У зачисления нет текущего урока'
#             return self._handle_error(request, error_msg, 400)
#
#         # Проверяем, не находится ли урок уже в процессе оценки
#         if enrollment.lesson_status == 'PENDING_ASSESSMENT':
#             error_msg = 'Этот урок уже находится на оценке. Пожалуйста, подождите завершения.'
#             return self._handle_error(request, error_msg, 400)
#
#         form = LessonTasksForm(
#             request.POST,
#             request.FILES,
#             lesson=enrollment.current_lesson,
#             completed_task_ids=set()
#         )
#
#         if not form.is_valid():
#             # Для AJAX возвращаем ошибку
#             if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
#                 return JsonResponse({
#                     'error': 'Пожалуйста, дайте ответы на все задания'
#                 }, status=400)
#
#             # Для обычного запроса - перенаправляем с сообщением
#             messages.error(request, 'Пожалуйста, дайте ответы на все задания')
#             return redirect('curriculum:learning_session', pk=enrollment_id)
#
#         lesson_tasks = Task.objects.filter(
#             lesson=enrollment.current_lesson,
#             is_active=True
#         )
#
#         if not lesson_tasks.exists():
#             error_msg = 'В уроке нет активных заданий'
#             return self._handle_error(request, error_msg, 400)
#
#         responses = self._collect_responses(request, lesson_tasks)
#         print(responses)
#
#         # validation_result = self._validate_responses(responses, lesson_tasks)
#         # if not validation_result['is_valid']:
#         #     return self._handle_error(request, validation_result['error'], 400)
#
#         try:
#             # 1. Сохраняем ответы
#             self._save_student_responses(enrollment, responses)
#
#             # 2. Обновляем статус урока
#             enrollment.lesson_status = 'PENDING_ASSESSMENT'
#             enrollment.assessment_started_at = timezone.now()
#             enrollment.save(update_fields=['lesson_status', 'assessment_started_at'])
#
#             # 3. Запускаем фоновую оценку
#             assessment_job_id = self._start_assessment(enrollment, responses)
#             if assessment_job_id:
#                 enrollment.assessment_job_id = assessment_job_id
#                 enrollment.save(update_fields=['assessment_job_id'])
#
#             # 4. PRG паттерн: всегда редиректим на CheckLessonAssessmentView
#             redirect_url = reverse('curriculum:check_lesson_assessment', kwargs={'enrollment_id': enrollment_id})
#
#             if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
#                 return JsonResponse({
#                     'status': 'REDIRECT',
#                     'redirect_url': redirect_url,
#                     'message': 'Ответы успешно отправлены на оценку'
#                 })
#             else:
#                 messages.success(request, 'Ваши ответы успешно сохранены и отправлены на оценку.')
#                 return redirect(redirect_url)
#
#         except Exception as e:
#             logger.error(f"Error processing lesson responses: {str(e)}", exc_info=True)
#             enrollment.lesson_status = 'ACTIVE'  # Возвращаем в активный статус при ошибке
#             enrollment.save(update_fields=['lesson_status'])
#             return self._handle_error(request, f'Ошибка сохранения ответов: {str(e)}', 500)
#
#     def _save_student_responses(self, enrollment, responses):
#         """
#         Сохраняет ответы студента в базу данных с защитой от дубликатов
#         """
#         from curriculum.models.assessment.student_response import StudentTaskResponse
#
#         student = enrollment.student
#         task_ids = list(responses.keys())
#
#         existing_responses = {
#             r.task_id: r
#             for r in StudentTaskResponse.objects.filter(
#                 student=student,
#                 task_id__in=task_ids,
#             )
#         }
#
#         for task_id, response_data in responses.items():
#             response_text = response_data.get("text", "")
#             audio_file = response_data.get("audio_file")
#
#             existing_response = existing_responses.get(task_id)
#
#             if existing_response:
#                 # Обновляем только если разрешено по статусу урока
#                 if enrollment.lesson_status in ["ACTIVE", "ERROR"]:
#                     logger.info(
#                         f"Updating existing response {existing_response.id} for task {task_id}"
#                     )
#
#                     existing_response.response_text = response_text or existing_response.response_text
#                     if audio_file:
#                         existing_response.audio_file = audio_file
#
#                     existing_response.submitted_at = timezone.now()
#                     existing_response.save(update_fields=[
#                         "response_text",
#                         "audio_file",
#                         "submitted_at",
#                     ])
#                 else:
#                     logger.warning(
#                         f"Attempt to modify response for lesson in {enrollment.lesson_status} status"
#                     )
#
#             else:
#                 # Создаём новый ответ
#                 logger.info(
#                     f"Creating new response for task {task_id}, student {student.id}"
#                 )
#                 st = StudentTaskResponse.objects.create(
#                     student=student,
#                     task_id=task_id,
#                     response_text=response_text,
#                     audio_file=audio_file,
#                 )
#
#     def _start_assessment(self, enrollment, responses):
#         """
#         Запускает фоновую оценку заданий через Celery
#
#         Args:
#             enrollment: Enrollment объект
#             responses: Словарь с ответами студента
#
#         Returns:
#             str: ID задачи Celery или None при ошибке
#         """
#         try:
#             # Запускаем асинхронную задачу
#             job = assess_lesson_tasks.delay(enrollment.id)
#             logger.info(f"Started assessment task {job.id} for enrollment {enrollment.id}")
#             return job.id
#         except Exception as e:
#             logger.error(f"Failed to start assessment task: {str(e)}")
#             return None
#
#     def _collect_responses(self, request, lesson_tasks):
#         """
#         Собирает ответы из запроса.
#
#         Принцип:
#         - КАЖДОЕ задание попадает в responses
#         - Пустой / некорректный ответ → text="" / audio_file=None
#         - Оценщик сам решает, как это интерпретировать (neutral)
#         """
#         responses: dict[int, dict] = {}
#
#         for task in lesson_tasks:
#             field_name = f'task_{task.id}'
#             audio_field = f'task_{task.id}_audio'
#
#             # === Значение по умолчанию (пустой ответ) ===
#             responses[task.id] = {
#                 'text': '',
#                 'audio_file': None
#             }
#
#             # ===== AUDIO =====
#             if task.response_format == 'audio':
#                 if audio_field in request.FILES:
#                     responses[task.id]['audio_file'] = request.FILES[audio_field]
#                 continue
#
#             # ===== MULTIPLE CHOICE =====
#             if task.response_format == 'multiple_choice':
#                 values = request.POST.getlist(field_name)
#
#                 if not values:
#                     # пустой ответ → останется нейтральным
#                     continue
#
#                 options = set(task.content.get('options', []))
#                 invalid = [v for v in values if v not in options]
#
#                 if invalid:
#                     logger.warning(
#                         "Invalid multiple_choice values",
#                         extra={
#                             "task_id": task.id,
#                             "invalid": invalid,
#                             "allowed": list(options),
#                         }
#                     )
#                     # некорректный ответ → нейтральный
#                     continue
#
#                 responses[task.id]['text'] = json.dumps(values)
#                 continue
#
#             # ===== TEXT / OTHER =====
#             if field_name in request.POST:
#                 text_value = request.POST.get(field_name, '').strip()
#                 if text_value:
#                     responses[task.id]['text'] = text_value
#
#         return responses
#
#     def _validate_responses(self, responses, lesson_tasks):
#         """Валидация собранных ответов"""
#         total_tasks = lesson_tasks.count()
#         completed_count = len(responses)
#
#         # Минимум 30% заданий должно быть выполнено (вместо жестких 50%)
#         min_required = max(1, int(total_tasks * 0.3))
#
#         if completed_count < min_required:
#             return {
#                 'is_valid': False,
#                 'error': f'Заполните хотя бы {min_required} из {total_tasks} заданий урока'
#             }
#
#         return {
#             'is_valid': True,
#             'completed_count': completed_count,
#             'total_count': total_tasks
#         }
#
#     def _handle_error(self, request, error_msg, status_code):
#         """Единая обработка ошибок для AJAX и обычных запросов"""
#         if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
#             return JsonResponse({'error': error_msg}, status=status_code)
#         else:
#             messages.error(request, error_msg)
#             return redirect('curriculum:course_list')


class CheckLessonAssessmentView(LoginRequiredMixin, ChatContextMixin, View):
    """
    Проверяет статус оценки урока.
    Поддерживает как AJAX (JSON), так и обычные GET-запросы с рендерингом.
    """

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

        # Для обычных запросов рендерим шаблон
        context = self._build_template_context(enrollment, assessment_status)
        context.update(self.get_chat_context(request))

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
            progress = job.info or {'current': 0, 'total': max(1, enrollment.current_lesson.tasks.count())}
            current = progress.get('current', 0)
            total = progress.get('total', 1)

            # Оцениваем оставшееся время
            elapsed_minutes = (timezone.now() - enrollment.assessment_started_at).total_seconds() / 60
            estimated_total_minutes = total * 1  # 1 минута на задание
            remaining_minutes = max(0, estimated_total_minutes - elapsed_minutes)

            return {
                'status': 'PENDING_ASSESSMENT',
                'progress': min(99, (current / total) * 100) if total > 0 else 0,
                'current': current,
                'total': total,
                'estimated_remaining_time': round(remaining_minutes, 1),
                'can_proceed': False,
                'message': f'Оценка выполняется. Осталось примерно {round(remaining_minutes, 1)} минут'
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
        return {
            'enrollment': enrollment,
            'course': enrollment.course,
            'current_lesson': enrollment.current_lesson,
            'assessment_status': assessment_status,
            'assessment_started_at': enrollment.assessment_started_at,
            'estimated_completion_time': assessment_status.get('estimated_remaining_time', 1),
            'progress': assessment_status.get('progress', 0),
            'current_task': assessment_status.get('current', 0),
            'total_tasks': assessment_status.get('total', 1),
            'status_message': assessment_status.get('message', 'Оценка выполняется')
        }

    def _handle_error(self, request, error_msg, status_code):
        """Единая обработка ошибок для AJAX и обычных запросов"""
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'error': error_msg}, status=status_code)
        else:
            messages.error(request, error_msg)
            return redirect('curriculum:course_list')
