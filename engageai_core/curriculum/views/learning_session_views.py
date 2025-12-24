import logging
from pprint import pprint

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse_lazy, reverse, NoReverseMatch
from django.views import View
from django.views.generic import DetailView
from django.http import JsonResponse

from curriculum.config.dependency_factory import CurriculumServiceFactory
from curriculum.models import Task, Lesson
from curriculum.models.content.task import ResponseFormat
from curriculum.models.student.enrollment import Enrollment

logger = logging.getLogger(__name__)


class LearningSessionView(LoginRequiredMixin, DetailView):
    """
    Представление для сессии обучения.
    Отображает текущее задание и обрабатывает ответы студента.
    """
    model = Enrollment
    template_name = 'curriculum/learning_session.html'
    context_object_name = 'enrollment'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        super().__init__(**kwargs)
        self.learning_service = CurriculumServiceFactory().create_learning_service()
        self.enrollment_service = self.learning_service.enrollment_service
        self.curriculum_query = self.learning_service.curriculum_query

    def get_queryset(self):
        """Фильтруем только активные зачисления текущего студента"""
        return Enrollment.objects.filter(
            student=self.request.user.student,
            is_active=True
        ).select_related(
            'course',
            'current_lesson'
        ).prefetch_related(
            'current_lesson__tasks'
        )

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        # Проверяем, что зачисление принадлежит текущему студенту
        if obj.student != self.request.user.student:
            raise PermissionDenied("Вы не можете получить доступ к этой учебной сессии")
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        enrollment = self.object

        # Получаем текущее состояние обучения через LearningService
        context['learning_state'] = self.learning_service.get_current_state(enrollment.id)

        # Получаем следующее задание через LearningService
        context['next_task'] = self.curriculum_query.get_next_task(enrollment)

        # Рассчитываем прогресс по курсу через EnrollmentService (ИСПРАВЛЕНО)
        # context['progress_percent'] = self.enrollment_service.calculate_progress(enrollment)

        # Получаем детальную информацию о прогрессе (опционально)
        context['progress_details'] = self.enrollment_service.get_course_progress(enrollment)
        pprint(context)
        return context


class LearningSessionTaskView(LoginRequiredMixin, DetailView):
    """
    Представление для отображения конкретного задания в сессии обучения.

    URL: /curriculum/session/<enrollment_id>/task/<task_id>/
    """
    model = Enrollment
    template_name = 'curriculum/learning_session_task.html'
    context_object_name = 'enrollment'
    pk_url_kwarg = 'enrollment_id'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        factory = CurriculumServiceFactory()
        self.learning_service = factory.create_learning_service()
        self.enrollment_service = self.learning_service.enrollment_service
        self.curriculum_query = self.learning_service.curriculum_query

    def get_queryset(self):
        return Enrollment.objects.filter(
            student=self.request.user.student,
            is_active=True
        ).select_related('course', 'current_lesson')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        enrollment = self.object
        task_id = self.kwargs.get('task_id')

        try:
            # Получаем конкретное задание
            context['current_task'] = Task.objects.get(
                id=task_id,
                lesson=enrollment.current_lesson,
                is_active=True
            )

            # Получаем текущее состояние
            context['learning_state'] = self.learning_service.get_current_state(enrollment.id)

            # Рассчитываем прогресс
            context['progress_details'] = self.enrollment_service.get_course_progress(enrollment)

        except Task.DoesNotExist:
            context['error'] = f"Задание {task_id} не найдено или не принадлежит текущему уроку"

        return context


class LessonHistoryView(LoginRequiredMixin, DetailView):
    """
    Представление для просмотра истории выполнения заданий в уроке.

    URL: /curriculum/session/<enrollment_id>/lesson/<lesson_id>/history/
    """
    model = Enrollment
    template_name = 'curriculum/lesson_history.html'
    context_object_name = 'enrollment'
    pk_url_kwarg = 'enrollment_id'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        factory = CurriculumServiceFactory()
        self.learning_service = factory.create_learning_service()
        self.curriculum_query = self.learning_service.curriculum_query

    def get_queryset(self):
        return Enrollment.objects.filter(
            student=self.request.user.student,
            is_active=True
        ).select_related('course')

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if obj.student != self.request.user.student:
            raise PermissionDenied("You cannot access this lesson history")
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        enrollment = self.object
        lesson_id = self.kwargs.get('lesson_id')

        try:
            # Получаем историю урока
            history_data = self.curriculum_query.get_lesson_history(enrollment.id, lesson_id)
            context.update(history_data)

            # Добавляем дополнительную информацию для шаблона
            context['current_lesson_id'] = enrollment.current_lesson.id if enrollment.current_lesson else None
            context['can_return_to_lesson'] = (
                    enrollment.current_lesson and
                    enrollment.current_lesson.id == int(lesson_id)
            )

        except Lesson.DoesNotExist:
            context['error'] = f"Lesson {lesson_id} not found or not accessible"

        return context


class CourseHistoryView(LoginRequiredMixin, DetailView):
    """
    Представление для просмотра истории пройденных уроков в курсе.

    URL: /curriculum/session/<enrollment_id>/history/
    """
    model = Enrollment
    template_name = 'curriculum/course_history.html'
    context_object_name = 'enrollment'
    pk_url_kwarg = 'enrollment_id'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        factory = CurriculumServiceFactory()
        self.learning_service = factory.create_learning_service()

    def get_queryset(self):
        return Enrollment.objects.filter(
            student=self.request.user.student,
            is_active=True
        ).select_related('course')

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if obj.student != self.request.user.student:
            raise PermissionDenied("You cannot access this course history")
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        enrollment = self.object

        try:
            # Получаем историю курса
            history_data = self.learning_service.get_course_history(enrollment.id)
            context.update(history_data)

        except Exception as e:
            context['error'] = f"Error loading course history: {str(e)}"

        return context


# @login_required
# def submit_task_response(request, enrollment_id):
#     """
#     Обрабатывает ответ студента на задание.
#     Поддерживает как HTML-форму, так и AJAX-запросы.
#     """
#     # Проверяем права доступа к enrollment
#     try:
#         enrollment = Enrollment.objects.get(
#             id=enrollment_id,
#             student=request.user.student,
#             is_active=True
#         )
#     except Enrollment.DoesNotExist:
#         error_msg = 'Зачисление не найдено или доступ запрещен'
#         if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accepts('application/json'):
#             return JsonResponse({'error': error_msg}, status=403)
#         messages.error(request, error_msg)
#         return redirect('curriculum:course_list')
#
#     if request.method != 'POST':
#         error_msg = 'Метод не разрешен'
#         if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accepts('application/json'):
#             return JsonResponse({'error': error_msg}, status=405)
#         messages.error(request, error_msg)
#         return redirect('curriculum:learning_session', pk=enrollment_id)
#
#     # Пытаемся получить task_id из запроса
#     try:
#         task_id = int(request.POST.get('task_id'))
#     except (TypeError, ValueError):
#         error_msg = 'Неверный ID задания'
#         if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accepts('application/json'):
#             return JsonResponse({'error': error_msg}, status=400)
#         messages.error(request, error_msg)
#         return redirect('curriculum:learning_session', pk=enrollment_id)
#
#     # Пытаемся получить задание
#     try:
#         task = Task.objects.get(id=task_id, is_active=True)
#     except Task.DoesNotExist:
#         error_msg = f'Задание {task_id} не найдено'
#         if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accepts('application/json'):
#             return JsonResponse({'error': error_msg}, status=404)
#         messages.error(request, error_msg)
#         return redirect('curriculum:learning_session', pk=enrollment_id)
#
#     # Валидация данных ответа
#     try:
#         text_response = request.POST.get('text', '').strip()
#         audio_file = request.FILES.get('audio_file')
#
#         if task.response_format == ResponseFormat.AUDIO and not audio_file:
#             error_msg = 'Для задания на устную речь требуется аудиофайл'
#             if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accepts('application/json'):
#                 return JsonResponse({'error': error_msg}, status=400)
#             messages.error(request, error_msg)
#             return redirect('curriculum:learning_session_task', enrollment_id=enrollment_id, task_id=task_id)
#
#         if task.response_format in [ResponseFormat.SINGLE_CHOICE, ResponseFormat.MULTIPLE_CHOICE,
#                                     ResponseFormat.SHORT_TEXT] and not text_response:
#             error_msg = 'Требуется текстовый ответ'
#             if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accepts('application/json'):
#                 return JsonResponse({'error': error_msg}, status=400)
#             messages.error(request, error_msg)
#             return redirect('curriculum:learning_session_task', enrollment_id=enrollment_id, task_id=task_id)
#
#         response_data = {
#             'text': text_response,
#             'audio_file': audio_file
#         }
#
#     except Exception as e:
#         error_msg = f'Ошибка при обработке данных: {str(e)}'
#         logger.error(error_msg, exc_info=True)
#         if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accepts('application/json'):
#             return JsonResponse({'error': error_msg}, status=400)
#         messages.error(request, error_msg)
#         return redirect('curriculum:learning_session_task', enrollment_id=enrollment_id, task_id=task_id)
#
#     # Основная логика обработки
#     try:
#         factory = CurriculumServiceFactory()
#         learning_service = factory.create_learning_service()
#         print("ОБРАБОТКА ОТВЕТА 1. отправка в learning_service: ", response_data)
#         result = learning_service.submit_task_response(
#             enrollment_id=enrollment_id,
#             task_id=task_id,
#             response_payload=response_data
#         )
#
#         pprint(result)
#
#         # Определяем тип ответа
#         if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accepts('application/json'):
#             return JsonResponse(result)
#         else:
#             next_action = result.get('next_action')
#
#             if next_action == 'NEXT_TASK' and result.get('next_task_id'):
#                 messages.success(request, 'Ответ сохранен. Переходим к следующему заданию.')
#                 return redirect('curriculum:learning_session_task',
#                                 enrollment_id=enrollment_id,
#                                 task_id=result['next_task_id'])
#
#             elif next_action in ['ADVANCE_LESSON', 'COMPLETE_COURSE']:
#                 messages.success(request, 'Урок завершен! Переходим к следующему уроку.')
#                 return redirect('curriculum:learning_session', pk=enrollment_id)
#
#             else:  # RETRY_TASK или неизвестное действие
#                 messages.warning(request, 'Попробуйте выполнить задание еще раз.')
#                 return redirect('curriculum:learning_session_task',
#                                 enrollment_id=enrollment_id,
#                                 task_id=task_id)
#
#     except Exception as e:
#         logger.error(f"Error in submit_task_response: {str(e)}", exc_info=True)
#         error_msg = 'Произошла ошибка при обработке ответа. Попробуйте еще раз.'
#
#         if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accepts('application/json'):
#             return JsonResponse({
#                 'error': str(e),
#                 'message': error_msg
#             }, status=500)
#         else:
#             messages.error(request, f'{error_msg}: {str(e)}')
#             return redirect('curriculum:learning_session_task', enrollment_id=enrollment_id, task_id=task_id)


class SubmitTaskResponseView(LoginRequiredMixin, View):
    """
    Class-based view для обработки ответа студента на задание.
    Поддерживает как HTML-формы, так и AJAX-запросы через fetch.
    """

    def post(self, request, enrollment_id):
        """
        Обрабатывает POST запросы с ответами студентов.
        """
        try:
            enrollment = Enrollment.objects.get(
                id=enrollment_id,
                student=request.user.student,
                is_active=True
            )
        except Enrollment.DoesNotExist:
            error_msg = 'Зачисление не найдено или доступ запрещен'
            return self._handle_error(request, error_msg, 403, 'curriculum:course_list')

        try:
            task_id = int(request.POST.get('task_id'))
        except (TypeError, ValueError):
            error_msg = 'Неверный ID задания'
            return self._handle_error(request, error_msg, 400, 'curriculum:learning_session', enrollment_id)

        try:
            task = Task.objects.get(id=task_id, is_active=True)
        except Task.DoesNotExist:
            error_msg = f'Задание {task_id} не найдено'
            return self._handle_error(request, error_msg, 404, 'curriculum:learning_session', enrollment_id)

        # Валидация данных ответа
        try:
            text_response = request.POST.get('text', '').strip()
            audio_file = request.FILES.get('audio_file')

            if task.response_format == ResponseFormat.AUDIO and not audio_file:
                error_msg = 'Для задания на устную речь требуется аудиофайл'
                return self._handle_error(
                    request, error_msg, 400,
                    'curriculum:learning_session_task',
                    enrollment_id, task_id
                )

            if task.response_format in [
                ResponseFormat.SINGLE_CHOICE,
                ResponseFormat.MULTIPLE_CHOICE,
                ResponseFormat.SHORT_TEXT
            ] and not text_response:
                error_msg = 'Требуется текстовый ответ'
                return self._handle_error(
                    request, error_msg, 400,
                    'curriculum:learning_session_task',
                    enrollment_id, task_id
                )

            response_data = {
                'text': text_response,
                'audio_file': audio_file
            }
        except Exception as e:
            error_msg = f'Ошибка при обработке данных: {str(e)}'
            logger.error(error_msg, exc_info=True)
            return self._handle_error(
                request, error_msg, 400,
                'curriculum:learning_session_task',
                enrollment_id, task_id
            )

        # Основная логика обработки
        try:
            factory = CurriculumServiceFactory()
            learning_service = factory.create_learning_service()

            result = learning_service.submit_task_response(
                enrollment_id=enrollment_id,
                task_id=task_id,
                response_payload=response_data
            )

            pprint(result)

            # 5. Формируем ответ в формате, ожидаемом фронтендом
            formatted_result = self._format_result_for_frontend(
                result, enrollment_id, enrollment.course.pk, enrollment.current_lesson.pk, task_id
            )

            pprint(formatted_result)

            # 6. Возвращаем результат
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse(formatted_result)
            else:
                return self._handle_redirect(request, formatted_result, enrollment_id)

        except Exception as e:
            logger.error(f"Error in submit_task_response: {str(e)}", exc_info=True)
            error_msg = 'Произошла ошибка при обработке ответа. Попробуйте еще раз.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'error': str(e),
                    'message': error_msg
                }, status=500)
            else:
                messages.error(request, f'{error_msg}: {str(e)}')
                return redirect(
                    'curriculum:learning_session_task',
                    enrollment_id=enrollment_id,
                    task_id=task_id
                )

    def _handle_error(self, request, error_msg, status_code, redirect_url, *args, **kwargs):
        """
        Единая точка обработки ошибок для AJAX и обычных запросов.
        """
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'error': error_msg}, status=status_code)
        else:
            messages.error(request, error_msg)
            return redirect(redirect_url, *args, **kwargs)

    def _format_result_for_frontend(self, result, enrollment_id, course_id, lesson_id, task_id):
        """
        Форматирует результат из LearningService в формат, ожидаемый фронтендом.
        """
        """Форматирует результат из LearningService в формат, ожидаемый фронтендом"""
        formatted = {
            'decision': result.get('decision', 'UNKNOWN'),
            'next_action': result.get('next_action', 'UNKNOWN'),
            'next_task_id': result.get('next_task_id'),
            'enrollment_id': enrollment_id,
            'task_id': task_id,
            'assessment_id': result.get('assessment_id'),
            'transition_id': result.get('transition_id')
        }

        # Генерируем готовый URL для редиректа
        next_action = result.get('next_action', 'UNKNOWN')
        course_id = result.get('course_id', 0)  # ID курса нужно передавать в result
        lesson_id = result.get('lesson_id', 0)  # ID урока нужно передавать в result

        formatted['redirect_url'] = self._generate_redirect_url(
            action=next_action,
            enrollment_id=enrollment_id,
            course_id=course_id,
            lesson_id=lesson_id,
            next_task_id=result.get('next_task_id')
        )

        # Форматируем feedback для фронтенда
        feedback = result.get('feedback', {})

        # Извлекаем сообщение из структурированной обратной связи
        if isinstance(feedback, dict):
            # Для auto-scq-v1 и других автоматических оценок
            structured = feedback.get('structured_feedback', {})
            if structured and isinstance(structured, dict):
                # Ищем текст обратной связи
                if 'suggestions' in structured and structured['suggestions']:
                    feedback_message = structured['suggestions'][0]
                elif 'strengths' in structured and structured['strengths']:
                    feedback_message = f"Отлично! {structured['strengths'][0]}"
                else:
                    feedback_message = "Хорошая работа!"

                # Ищем объяснение
                explanation = ""
                if 'metadata' in structured and isinstance(structured['metadata'], dict):
                    if 'is_correct' in structured['metadata']:
                        if structured['metadata']['is_correct']:
                            explanation = "Правильный ответ! Вы отлично справились с этим заданием."
                        else:
                            explanation = "Попробуйте ещё раз. Обратите внимание на детали в задании."
                else:
                    explanation = "Задание выполнено. Продолжайте в том же духе!"
            else:
                # Для других типов оценки
                feedback_message = feedback.get('message', 'Отличная работа!')
                explanation = feedback.get('explanation', 'Хороший прогресс!')
        else:
            feedback_message = str(feedback)
            explanation = ""

        formatted.update({
            'feedback': {
                'message': feedback_message
            },
            'explanation': explanation,
            'success': result.get('decision') != 'REPEAT_TASK'
        })

        return formatted

    def _generate_redirect_url(self, action, enrollment_id, course_id, lesson_id, next_task_id=None):
        """
        Генерирует готовый URL для редиректа по указанному действию.
        """
        url_map = {
            'NEXT_TASK': (
                'curriculum:learning_session_task', {'enrollment_id': enrollment_id, 'task_id': next_task_id}),
            'ADVANCE_LESSON': ('curriculum:learning_session', {'pk': enrollment_id}),
            'COMPLETE_LESSON': ('curriculum:learning_session', {'pk': enrollment_id}),
            'CURRENT_SESSION': ('curriculum:learning_session', {'pk': enrollment_id}),
            'COURSE_LIST': ('curriculum:course_list', {}),
            'COURSE_DETAIL': ('curriculum:course_detail', {'pk': course_id}),
            'LESSON_HISTORY': ('curriculum:lesson_history', {'enrollment_id': enrollment_id, 'lesson_id': lesson_id}),
            'COURSE_HISTORY': ('curriculum:course_history', {'enrollment_id': enrollment_id})
        }

        # Получаем конфигурацию URL для действия
        url_config = url_map.get(action, url_map['COURSE_DETAIL'])
        view_name, kwargs = url_config

        try:
            return reverse(view_name, kwargs=kwargs)
        except NoReverseMatch as e:
            logger.error(f"URL generation error for action {action}: {str(e)}")
            # Возвращаем безопасный URL по умолчанию
            return reverse('curriculum:course_detail', kwargs={'pk': course_id})

    def _handle_redirect(self, request, result, enrollment_id):
        """
        Обрабатывает редирект для обычных (не-AJAX) запросов.
        """
        next_action = result.get('next_action')
        next_task_id = result.get('next_task_id')

        if next_action == 'NEXT_TASK' and next_task_id:
            messages.success(request, 'Ответ сохранен. Переходим к следующему заданию.')
            return redirect(
                'curriculum:learning_session_task',
                enrollment_id=enrollment_id,
                task_id=next_task_id
            )

        elif next_action in ['ADVANCE_LESSON', 'COMPLETE_COURSE']:
            messages.success(request, 'Урок завершен! Переходим к следующему уроку.')
            return redirect('curriculum:learning_session', pk=enrollment_id)

        else:  # RETRY_TASK или неизвестное действие
            messages.warning(request, 'Попробуйте выполнить задание еще раз.')
            return redirect(
                'curriculum:learning_session_task',
                enrollment_id=enrollment_id,
                task_id=result.get('task_id', 0)
            )
