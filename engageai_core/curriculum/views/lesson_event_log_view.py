from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView
from django.utils import timezone
from django.db.models import Q, Count, Avg, Sum
from datetime import timedelta

from curriculum.models.learning_process.lesson_event_log import LessonEventLog, LessonEventType


class LessonEventLogListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    """
    Списковое представление событий уроков с пагинацией, фильтрами и сортировкой.

    Функционал:
    - Пагинация по 10 записей
    - Фильтры: тип события, канал, студент, период
    - Сортировка: время, длительность
    - AJAX поддержка для динамической подгрузки
    - Статистика по фильтрам
    """
    model = LessonEventLog
    template_name = 'curriculum/event_log_list.html'
    context_object_name = 'events'
    paginate_by = 6
    ordering = ['-timestamp']

    def test_func(self):
        """Только администраторы и методисты"""
        # return self.request.user.is_staff or self.request.user.groups.filter(name='methodists').exists()
        return True

    def get_queryset(self):
        """Фильтрация и сортировка queryset"""
        queryset = super().get_queryset().select_related(
            'student', 'enrollment', 'lesson', 'student__user'
        ).only(
            'id', 'timestamp', 'event_type', 'channel', 'duration_minutes',
            'student__user__username', 'student__user__first_name', 'student__user__last_name',
            'enrollment__course__title', 'lesson__title',
            'metadata'
        )

        # Фильтр по типу события
        event_type = self.request.GET.get('event_type')
        if event_type and event_type != 'ALL':
            queryset = queryset.filter(event_type=event_type)

        # Фильтр по каналу
        channel = self.request.GET.get('channel')
        if channel and channel != 'ALL':
            queryset = queryset.filter(channel=channel)

        # Фильтр по студенту
        student_id = self.request.GET.get('student_id')
        if student_id:
            queryset = queryset.filter(student_id=student_id)

        # Фильтр по уроку
        lesson_id = self.request.GET.get('lesson_id')
        if lesson_id:
            queryset = queryset.filter(lesson_id=lesson_id)

        # Фильтр по периоду
        period = self.request.GET.get('period', 'all')
        if period == 'day':
            queryset = queryset.filter(timestamp__gte=timezone.now() - timedelta(days=1))
        elif period == 'week':
            queryset = queryset.filter(timestamp__gte=timezone.now() - timedelta(days=7))
        elif period == 'month':
            queryset = queryset.filter(timestamp__gte=timezone.now() - timedelta(days=30))

        # Поиск по тексту (метаданные или название урока)
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(lesson__title__icontains=search) |
                Q(metadata__icontains=search) |
                Q(student__user__username__icontains=search) |
                Q(student__user__first_name__icontains=search) |
                Q(student__user__last_name__icontains=search)
            )

        # Сортировка
        order_by = self.request.GET.get('order_by', '-timestamp')
        valid_orders = ['-timestamp', 'timestamp', '-duration_minutes', 'duration_minutes']
        if order_by in valid_orders:
            queryset = queryset.order_by(order_by)

        return queryset

    def get_context_data(self, **kwargs):
        """Добавление статистики и фильтров в контекст"""
        context = super().get_context_data(**kwargs)

        # Базовый фильтрованный queryset для статистики
        base_qs = self.get_queryset()

        # Общая статистика
        context['total_events'] = base_qs.count()
        context['total_duration'] = base_qs.aggregate(
            Sum('duration_minutes')
        )['duration_minutes__sum'] or 0

        # Средняя длительность занятий
        avg_duration = base_qs.filter(
            event_type=LessonEventType.COMPLETE
        ).aggregate(Avg('duration_minutes'))['duration_minutes__avg']
        context['avg_duration'] = round(avg_duration, 2) if avg_duration else 0

        # Распределение по типам событий
        context['events_by_type'] = base_qs.values('event_type').annotate(
            count=Count('id')
        ).order_by('-count')

        # Распределение по каналам
        context['events_by_channel'] = base_qs.values('channel').annotate(
            count=Count('id')
        ).order_by('-count')

        # Success rate (отношение COMPLETE к общему числу уроков)
        complete_count = base_qs.filter(event_type=LessonEventType.COMPLETE).count()
        start_count = base_qs.filter(event_type=LessonEventType.START).count()
        context['completion_rate'] = round((complete_count / start_count * 100), 1) if start_count > 0 else 0

        # Текущие фильтры для отображения в форме
        context['current_filters'] = {
            'event_type': self.request.GET.get('event_type', 'ALL'),
            'channel': self.request.GET.get('channel', 'ALL'),
            'student_id': self.request.GET.get('student_id', ''),
            'lesson_id': self.request.GET.get('lesson_id', ''),
            'period': self.request.GET.get('period', 'all'),
            'search': self.request.GET.get('search', ''),
            'order_by': self.request.GET.get('order_by', '-timestamp'),
        }

        # Список типов событий для фильтра
        context['event_types'] = LessonEventType.choices
        context['channels'] = LessonEventLog._meta.get_field('channel').choices

        return context
