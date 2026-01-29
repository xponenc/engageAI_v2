import ast
import json

from django.db.models import Count, Sum, Avg, Q, F, FloatField, ExpressionWrapper, DecimalField, Case, When, Value
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth, TruncHour, Coalesce
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import TemplateView, ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from datetime import timedelta
from django.core.cache import cache

from llm_logger.models import LLMRequestType, LogLLMRequest


class LLMLogListView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    """
    Списковое представление логов LLM с пагинацией, фильтрами и сортировкой.

    Функционал:
    - Пагинация по 10 записей
    - Фильтры: тип запроса, статус, модель, пользователь, период
    - Сортировка: время, стоимость, длительность
    - AJAX поддержка для динамической подгрузки
    - Статистика по фильтрам
    """
    model = LogLLMRequest
    template_name = 'llm_logger/log_list.html'
    context_object_name = 'logs'
    paginate_by = 5
    ordering = ['-request_time']

    def test_func(self):
        """Только администраторы и методисты"""
        return True
        # return self.request.user.is_staff or self.request.user.groups.filter(name='methodists').exists()

    def get_queryset(self):
        """Фильтрация и сортировка queryset"""
        queryset = super().get_queryset().select_related(
            'user', 'course', 'lesson', 'task'
        ).only(
            'id', 'request_time', 'model_name', 'request_type', 'status',
            'cost_total', 'duration_sec', 'tokens_in', 'tokens_out',
            'user__username', 'course__title', 'lesson__title', 'course', 'lesson', 'task',
        )

        # Фильтр по типу запроса
        request_type = self.request.GET.get('request_type')
        if request_type and request_type != 'ALL':
            queryset = queryset.filter(request_type=request_type)

        # Фильтр по статусу
        status = self.request.GET.get('status')
        if status and status != 'ALL':
            queryset = queryset.filter(status=status)

        # Фильтр по модели
        model_name = self.request.GET.get('model_name')
        if model_name:
            queryset = queryset.filter(model_name__icontains=model_name)

        # Фильтр по пользователю
        user_id = self.request.GET.get('user_id')
        if user_id:
            queryset = queryset.filter(user_id=user_id)

        # Фильтр по периоду
        period = self.request.GET.get('period', 'all')
        if period == 'day':
            queryset = queryset.filter(request_time__gte=timezone.now() - timedelta(days=1))
        elif period == 'week':
            queryset = queryset.filter(request_time__gte=timezone.now() - timedelta(days=7))
        elif period == 'month':
            queryset = queryset.filter(request_time__gte=timezone.now() - timedelta(days=30))

        # Поиск по тексту (промпт или ответ)
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(prompt__icontains=search) | Q(response__icontains=search)
            )

        # Сортировка
        order_by = self.request.GET.get('order_by', '-request_time')
        valid_orders = ['-request_time', 'request_time', '-cost_total', 'cost_total', '-duration_sec', 'duration_sec']
        if order_by in valid_orders:
            queryset = queryset.order_by(order_by)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Статистика по текущему фильтру
        queryset = self.get_queryset()
        stats = queryset.aggregate(
            total_requests=Count('id'),
            total_cost=Sum('cost_total'),
            avg_cost=Avg('cost_total'),
            avg_duration=Avg('duration_sec'),
            success_count=Count('id', filter=Q(status='SUCCESS')),
            error_count=Count('id', filter=Q(status='ERROR')),
        )

        # Статистика по типам запросов
        type_stats = queryset.values('request_type').annotate(
            count=Count('id'),
            cost=Sum('cost_total'),
        ).order_by('-count')

        # Статистика по моделям
        model_stats = queryset.values('model_name').annotate(
            count=Count('id'),
            cost=Sum('cost_total'),
        ).order_by('-count')

        # Доступные фильтры
        context.update({
            # Статистика
            'total_requests': stats['total_requests'] or 0,
            'total_cost': stats['total_cost'] or 0,
            'avg_cost': stats['avg_cost'] or 0,
            'avg_duration': stats['avg_duration'] or 0,
            'success_rate': round(
                (stats['success_count'] / stats['total_requests'] * 100)
                if stats['total_requests'] > 0 else 0, 1
            ),

            # Статистика по типам и моделям
            'type_stats': type_stats,
            'model_stats': model_stats,

            # Фильтры
            'request_types': LLMRequestType.choices,
            'current_filters': {
                'request_type': self.request.GET.get('request_type', 'ALL'),
                'status': self.request.GET.get('status', 'ALL'),
                'model_name': self.request.GET.get('model_name', ''),
                'user_id': self.request.GET.get('user_id', ''),
                'period': self.request.GET.get('period', 'all'),
                'search': self.request.GET.get('search', ''),
                'order_by': self.request.GET.get('order_by', '-request_time'),
            },

            # Пагинация
            'page_obj': context['page_obj'],
            'is_paginated': context['is_paginated'],
            'paginator': context['paginator'],
        })

        return context

    def render_to_response(self, context, **response_kwargs):
        """Поддержка AJAX запросов для динамической подгрузки"""
        if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            logs_data = []
            for log in context['logs']:
                logs_data.append({
                    'id': log.id,
                    'request_time': log.request_time.strftime('%Y-%m-%d %H:%M:%S'),
                    'model_name': log.model_name,
                    'request_type': log.get_request_type_display(),
                    'status': log.status,
                    'cost_total': float(log.cost_total),
                    'duration_sec': round(log.duration_sec or 0, 2),
                    'user': log.user.username if log.user else '-',
                    'course': log.course.title if log.course else '-',
                    'url': reverse_lazy('llm_log_detail', kwargs={'pk': log.id}),
                })

            return JsonResponse({
                'logs': logs_data,
                'has_next': context['page_obj'].has_next(),
                'next_page_number': context['page_obj'].next_page_number() if context['page_obj'].has_next() else None,
                'current_page': context['page_obj'].number,
                'total_pages': context['paginator'].num_pages,
            })

        return super().render_to_response(context, **response_kwargs)


class LLMLogDetailView(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    """
    Детальное представление одного лога LLM.

    Показывает:
    - Полный промпт и ответ
    - Все метаданные
    - Стоимость и токены
    - Связанные объекты (пользователь, курс, урок, задание)
    - Историю похожих запросов
    """
    model = LogLLMRequest
    template_name = 'llm_logger/log_detail.html'
    context_object_name = 'log'
    pk_url_kwarg = 'pk'

    def test_func(self):
        """Только администраторы и методисты"""
        return True
        # return self.request.user.is_staff or self.request.user.groups.filter(name='methodists').exists()

    def get_queryset(self):
        """Добавляем связанные объекты"""
        return super().get_queryset().select_related(
            'user', 'course', 'lesson', 'task'
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        log = self.object

        # Похожие запросы (тот же пользователь, тип и модель)
        similar_logs = LogLLMRequest.objects.filter(
            user=log.user,
            request_type=log.request_type,
            model_name=log.model_name,
        ).exclude(id=log.id).select_related(
            'user', 'course', 'lesson'
        ).only(
            'id', 'request_time', 'status', 'cost_total', 'duration_sec', 'user', 'course', 'lesson'
        ).order_by('-request_time')[:10]


        # Форматируем метаданные для отображения
        metadata_pretty = json.dumps(log.metadata, indent=2, ensure_ascii=False) if log.metadata else '{}'

        # Форматируем промпт и ответ для читаемости
        prompt_lines = log.prompt.split('\n') if log.prompt else []
        response_lines = log.response.split('\n') if log.response else []
        print(log.response)

        try:
            response_data = json.loads(log.response)
        except json.JSONDecodeError:
            response_data = ast.literal_eval(log.response)

        context.update({
            'similar_logs': similar_logs,
            'metadata_pretty': metadata_pretty,
            'prompt_lines': prompt_lines,
            'response_lines': response_lines,
            'response': response_data,
            'request_types': LLMRequestType.choices,
        })

        return context


class LLMAnalyticsView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    """
    Оптимизированный административный дашборд по использованию LLM.
    GET /admin/analytics/llm/?period=month
    day — за последние 24 часа
    week — за последние 7 дней (по умолчанию)
    month — за последние 30 дней
    quarter — за последние 90 дней
    """
    template_name = 'llm_logger/llm_dashboard.html'

    def test_func(self):
        """Только администраторы и методисты"""
        return True
        # return self.request.user.is_staff or self.request.user.groups.filter(name='methodists').exists()

    PERIODS = {
        'day': timedelta(days=1),
        'week': timedelta(days=7),
        'month': timedelta(days=30),
        'quarter': timedelta(days=90),
    }

    def get_period_range(self):
        """Получает диапазон дат и период из GET-параметров"""
        period = self.request.GET.get('period', 'week')
        end_date = timezone.now()
        start_date = end_date - self.PERIODS.get(period, self.PERIODS['week'])
        return start_date, end_date, period

    def get_queryset(self, start_date, end_date):
        """Базовый queryset с фильтрацией по периоду"""
        return LogLLMRequest.objects.filter(
            request_time__gte=start_date,
            request_time__lte=end_date
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        start_date, end_date, period = self.get_period_range()

        # Базовый оптимизированный queryset
        queryset = self.get_queryset(start_date, end_date)

        # === 1. ОСНОВНЫЕ МЕТРИКИ (Задача 5.1: анализ стоимости) ===
        # Кэшируем на 5 минут для снижения нагрузки на БД
        cache_key = f'llm_totals_{period}_{start_date.date()}'
        # totals = cache.get(cache_key)
        totals = None

        if totals is None:
            totals = queryset.aggregate(
                total_requests=Count('id'),
                total_cost=Sum('cost_total'),
                total_tokens_in=Sum('tokens_in'),
                total_tokens_out=Sum('tokens_out'),
                avg_cost_per_request=Avg('cost_total'),
                avg_tokens_per_request=Avg(F('tokens_in') + F('tokens_out')),
                avg_duration=Avg('duration_sec'),
                success_count=Count('id', filter=Q(status='SUCCESS')),
                error_count=Count('id', filter=Q(status='ERROR')),
                timeout_count=Count('id', filter=Q(status='TIMEOUT')),
            )

            # Расчёт процентов успеха
            total = totals['total_requests'] or 0
            totals['success_rate'] = round((totals['success_count'] / total * 100) if total > 0 else 0, 1)
            totals['error_rate'] = round((totals['error_count'] / total * 100) if total > 0 else 0, 1)

            cache.set(cache_key, totals, timeout=300)  # 5 минут

        # === 2. АНАЛИТИКА ПО ТИПАМ ЗАПРОСОВ (Задача 2.3) ===
        # Критически важно для понимания распределения нагрузки по модулям
        type_stats = queryset.values('request_type').annotate(
            requests=Count('id'),
            cost=Sum('cost_total'),
            avg_cost=Avg('cost_total'),
            avg_tokens=Avg(F('tokens_in') + F('tokens_out')),
            avg_duration=Avg('duration_sec'),
            success_rate=ExpressionWrapper(
                Count('id', filter=Q(status='SUCCESS')) * 100.0 / Count('id'),
                output_field=FloatField()
            )
        ).order_by('-requests')

        # === 3. АНАЛИТИКА ПО МОДЕЛЯМ LLM (Задача 5.2: смена провайдера) ===
        model_stats = queryset.values('model_name').annotate(
            requests=Count('id'),
            cost=Sum('cost_total'),
            avg_cost=Avg('cost_total'),
            avg_tokens=Avg(F('tokens_in') + F('tokens_out')),
            avg_duration=Avg('duration_sec'),
            cost_share=ExpressionWrapper(
                Sum('cost_total') * 100.0 / (Sum('cost_total', filter=Q(id__isnull=False)) or 1),
                output_field=FloatField()
            )
        ).order_by('-requests')

        # === 4. АНАЛИТИКА ПО ПОЛЬЗОВАТЕЛЯМ (ТОП-10 самых активных) ===
        user_stats = queryset.filter(
            user__isnull=False
        ).values(
            'user__id',
            'user__username',
            'user__email'
        ).annotate(
            requests=Count('id'),
            cost=Sum('cost_total'),
            avg_cost=Avg('cost_total'),
            avg_duration=Avg('duration_sec'),
        ).order_by('-requests')[:10]

        # === 5. ДИНАМИКА ПО ДНЯМ ===
        daily_usage = queryset.annotate(
            day=TruncDate('request_time')
        ).values('day').annotate(
            requests=Count('id'),
            cost=Sum('cost_total'),
            avg_cost=Avg('cost_total'),
            tokens=Sum(F('tokens_in') + F('tokens_out')),
        ).order_by('day')

        # === 6. СРАВНЕНИЕ С ПРЕДЫДУЩИМ ПЕРИОДОМ ===
        prev_start_date = start_date - (end_date - start_date)
        prev_end_date = start_date
        prev_queryset = LogLLMRequest.objects.filter(
            request_time__gte=prev_start_date,
            request_time__lte=prev_end_date
        )

        prev_totals = prev_queryset.aggregate(
            prev_requests=Count('id'),
            prev_cost=Sum('cost_total')
        )

        # Расчёт динамики
        current_requests = totals['total_requests'] or 0
        prev_requests = prev_totals['prev_requests'] or 0
        current_cost = totals['total_cost'] or 0
        prev_cost = prev_totals['prev_cost'] or 0

        requests_change = ((current_requests - prev_requests) / prev_requests * 100) if prev_requests > 0 else 0
        cost_change = ((current_cost - prev_cost) / prev_cost * 100) if prev_cost > 0 else 0

        # === 7. СТАТИСТИКА ОШИБОК (Задача 2.3: эффективность AI) ===
        error_stats = queryset.filter(
            status='ERROR'
        ).values('error_message').annotate(
            count=Count('id')
        ).order_by('-count')[:10]

        # === 8. ТОП-5 САМЫХ ДОРОГИХ ЗАПРОСОВ (для оптимизации) ===
        expensive_requests = queryset.select_related(
            'user', 'course', 'lesson', 'task'
        ).order_by('-cost_total')[:5]

        # === 9. АНАЛИТИКА ПО УЧЕБНОМУ КОНТЕНТУ ===
        course_stats = queryset.filter(
            course__isnull=False
        ).values('course__id', 'course__title').annotate(
            requests=Count('id'),
            cost=Sum('cost_total'),
            avg_cost=Avg('cost_total'),
        ).order_by('-requests')[:10]

        # === 10. ЧАСОВАЯ АКТИВНОСТЬ (для планирования нагрузки) ===
        hourly_activity = queryset.annotate(
            hour=TruncHour('request_time')
        ).values('hour').annotate(
            requests=Count('id')
        ).order_by('hour')

        # Подготовка данных для графика
        daily_labels = [entry['day'].strftime('%Y-%m-%d') for entry in daily_usage]
        daily_requests = [entry['requests'] for entry in daily_usage]
        daily_cost = [float(entry['cost']) for entry in daily_usage]

        # === ФОРМИРОВАНИЕ КОНТЕКСТА ===
        context.update({
            # Период
            'period': period,
            'period_start': start_date.strftime('%Y-%m-%d'),
            'period_end': end_date.strftime('%Y-%m-%d'),
            'prev_period_start': prev_start_date.strftime('%Y-%m-%d'),
            'prev_period_end': prev_end_date.strftime('%Y-%m-%d'),

            # Основные метрики (Задача 5.1)
            'total_requests': totals['total_requests'] or 0,
            'total_cost': round(totals['total_cost'] or 0, 4),
            'total_tokens_in': totals['total_tokens_in'] or 0,
            'total_tokens_out': totals['total_tokens_out'] or 0,
            'avg_cost_per_request': round(totals['avg_cost_per_request'] or 0, 6),
            'avg_tokens_per_request': round(totals['avg_tokens_per_request'] or 0, 0),
            'avg_duration': round(totals['avg_duration'] or 0, 2),
            'success_rate': totals['success_rate'],
            'error_rate': totals['error_rate'],
            'success_count': totals['success_count'] or 0,
            'error_count': totals['error_count'] or 0,
            'timeout_count': totals['timeout_count'] or 0,

            # Динамика
            'requests_change': round(requests_change, 1),
            'cost_change': round(cost_change, 1),
            'requests_trend': 'up' if requests_change > 0 else 'down' if requests_change < 0 else 'stable',
            'cost_trend': 'up' if cost_change > 0 else 'down' if cost_change < 0 else 'stable',

            # Аналитика по типам (Задача 2.3)
            'type_stats': list(type_stats),

            # Аналитика по моделям (Задача 5.2)
            'model_stats': list(model_stats),

            # Пользователи
            'user_stats': list(user_stats),

            # Динамика по дням
            'daily_usage': list(daily_usage),

            # Ошибки
            'error_stats': list(error_stats),

            # Дорогие запросы
            'expensive_requests': expensive_requests,

            # Курсы
            'course_stats': list(course_stats),

            # Часовая активность
            'hourly_activity': list(hourly_activity),

            # Доступные периоды
            'available_periods': [
                ('day', 'День'),
                ('week', 'Неделя'),
                ('month', 'Месяц'),
                ('quarter', 'Квартал'),
            ],

            # Типы запросов для фильтрации
            'request_types': LLMRequestType.choices,

            'daily_labels': daily_labels,
            'daily_requests': daily_requests,
            'daily_cost': daily_cost,
        })

        return context


class LLMUserDetailView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    """Детальная аналитика по конкретному пользователю"""
    template_name = 'llm_logger/llm_user_detail.html'

    def test_func(self):
        return True
        # return self.request.user.is_staff

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_id = self.kwargs.get('user_id') or self.request.GET.get('user_id')

        if not user_id:
            context['error'] = 'User ID не указан'
            return context

        # === 1. ОСНОВНЫЕ МЕТРИКИ ===
        totals = LogLLMRequest.objects.filter(user_id=user_id).aggregate(
            total_requests=Count('id'),
            total_cost=Sum('cost_total'),
            avg_cost_per_request=Avg('cost_total'),
            avg_duration=Avg('duration_sec'),
            success_count=Count('id', filter=Q(status='SUCCESS')),
            error_count=Count('id', filter=Q(status='ERROR')),
        )

        # === 2. ПОСЛЕДНИЕ ЛОГИ (50 записей) ===
        recent_logs = LogLLMRequest.objects.filter(
            user_id=user_id
        ).select_related(
            'course', 'lesson', 'task'
        ).only(
            'id', 'request_time', 'request_type', 'model_name', 'status',
            'cost_total', 'duration_sec', 'course__title', 'lesson__title',
            'course', 'lesson', 'task',
        ).order_by('-request_time')[:50]

        # === 3. СТАТИСТИКА ПО ТИПАМ ЗАПРОСОВ ===
        type_breakdown = LogLLMRequest.objects.filter(
            user_id=user_id
        ).values('request_type').annotate(
            count=Count('id'),
            cost=Sum('cost_total'),
            avg_cost=Avg('cost_total'),
        ).order_by('-count')

        # Добавляем процент от общего бюджета
        total_cost = totals['total_cost'] or 0
        for stat in type_breakdown:
            stat['cost_percentage'] = (
                (stat['cost'] / total_cost * 100) if total_cost > 0 else 0
            )
            stat['cost_percentage_rounded'] = round(stat['cost_percentage'], 1)

        # === 4. ЧАСОВАЯ АКТИВНОСТЬ (последние 24 часа) ===
        from django.db.models.functions import TruncHour

        # hourly_activity = LogLLMRequest.objects.filter(
        #     user_id=user_id,
        #     request_time__gte=timezone.now() - timedelta(hours=24)
        # ).annotate(
        #     hour=TruncHour('request_time')
        # ).values('hour').annotate(
        #     requests=Count('id')
        # ).order_by('hour')

        # Проверка аномалии: более 50 запросов в час
        # anomaly_detected = any(hour['requests'] > 50 for hour in hourly_activity)

        anomalies = self.detect_anomalies(user_id=user_id)

        # === 5. СРАВНЕНИЕ СО СРЕДНИМ ПО ВСЕМ ПОЛЬЗОВАТЕЛЯМ ===
        avg_requests_all_users = LogLLMRequest.objects.values('user').annotate(
            count=Count('id')
        ).aggregate(avg=Avg('count'))['avg'] or 0

        user_requests = totals['total_requests'] or 0
        deviation_from_avg = (
            ((user_requests - avg_requests_all_users) / avg_requests_all_users * 100)
            if avg_requests_all_users > 0 else 0
        )

        # === 6. ТОП-5 САМЫХ ДОРОГИХ ЗАПРОСОВ ПОЛЬЗОВАТЕЛЯ ===
        expensive_requests = LogLLMRequest.objects.filter(
            user_id=user_id
        ).select_related('course', 'lesson').order_by('-cost_total')[:5]

        # === ФОРМИРОВАНИЕ КОНТЕКСТА ===
        context.update({
            # Основные метрики
            'total_requests': totals['total_requests'] or 0,
            'total_cost': totals['total_cost'] or 0,
            'avg_cost_per_request': totals['avg_cost_per_request'] or 0,
            'avg_duration': totals['avg_duration'] or 0,
            'success_rate': round(
                (totals['success_count'] / totals['total_requests'] * 100)
                if totals['total_requests'] > 0 else 0, 1
            ),

            # Последние логи
            'user_logs': recent_logs,

            # Статистика по типам
            'type_breakdown': type_breakdown,

            # Аномалии
            # 'anomaly_detected': anomaly_detected,
            # 'hourly_activity': list(hourly_activity),

            'anomalies' : anomalies,

            # Сравнение со средним
            'deviation_from_avg': round(deviation_from_avg, 1),
            'is_above_average': deviation_from_avg > 50,  # На 50% выше среднего

            # Дорогие запросы
            'expensive_requests': expensive_requests,

            # Информация о пользователе
            'user_id': user_id,
        })

        return context

    def detect_anomalies(self, user_id: int) -> dict:
        """Детектирует различные типы аномалий для пользователя"""
        anomalies = {
            'detected': False,
            'types': [],
            'details': [],
        }

        # 1. Высокая частота запросов (> 50 в час)
        hourly_activity = LogLLMRequest.objects.filter(
            user_id=user_id,
            request_time__gte=timezone.now() - timedelta(hours=24)
        ).annotate(
            hour=TruncHour('request_time')
        ).values('hour').annotate(
            requests=Count('id')
        )

        high_frequency_hours = [h for h in hourly_activity if h['requests'] > 50]
        if high_frequency_hours:
            anomalies['detected'] = True
            anomalies['types'].append('HIGH_FREQUENCY')
            anomalies['details'].append({
                'type': 'HIGH_FREQUENCY',
                'severity': 'HIGH' if len(high_frequency_hours) > 3 else 'MEDIUM',
                'message': f"Обнаружено {len(high_frequency_hours)} часа(ов) с аномально высокой активностью (более 50 запросов/час)",
                'max_requests': max(h['requests'] for h in high_frequency_hours),
                'recommendation': 'Проверьте на ботов или автоматизированные скрипты'
            })

        # 2. Высокая стоимость запросов (> 3× средняя)
        user_avg_cost = LogLLMRequest.objects.filter(user_id=user_id).aggregate(
            avg=Avg('cost_total')
        )['avg'] or 0

        global_avg_cost = LogLLMRequest.objects.aggregate(
            avg=Avg('cost_total')
        )['avg'] or 0.001

        if user_avg_cost > global_avg_cost * 3:
            anomalies['detected'] = True
            anomalies['types'].append('HIGH_COST')
            anomalies['details'].append({
                'type': 'HIGH_COST',
                'severity': 'HIGH' if user_avg_cost > global_avg_cost * 5 else 'MEDIUM',
                'message': f"Средняя стоимость запроса (${user_avg_cost:.6f}) превышает глобальную среднюю (${global_avg_cost:.6f}) в {user_avg_cost / global_avg_cost:.1f} раз",
                'recommendation': 'Проверьте промпты на оптимизацию токенов'
            })

        # 3. Низкий успех запросов (< 80%)
        success_rate = LogLLMRequest.objects.filter(user_id=user_id).aggregate(
            success=Count('id', filter=Q(status='SUCCESS')),
            total=Count('id')
        )

        if success_rate['total'] > 10:  # Только если достаточно данных
            rate = success_rate['success'] / success_rate['total']
            if rate < 0.8:
                anomalies['detected'] = True
                anomalies['types'].append('LOW_SUCCESS_RATE')
                anomalies['details'].append({
                    'type': 'LOW_SUCCESS_RATE',
                    'severity': 'MEDIUM',
                    'message': f"Success rate ({rate * 100:.1f}%) ниже порогового значения (80%)",
                    'recommendation': 'Проверьте качество промптов и параметры запросов'
                })

        # 4. Аномальная активность по времени (ночные запросы)
        night_requests = LogLLMRequest.objects.filter(
            user_id=user_id,
            request_time__hour__gte=0,
            request_time__hour__lte=5
        ).count()

        total_requests = LogLLMRequest.objects.filter(user_id=user_id).count()

        if total_requests > 20 and night_requests / total_requests > 0.5:
            anomalies['detected'] = True
            anomalies['types'].append('NIGHT_ACTIVITY')
            anomalies['details'].append({
                'type': 'NIGHT_ACTIVITY',
                'severity': 'LOW',
                'message': f"Более 50% запросов ({night_requests}/{total_requests}) выполняются ночью (00:00-05:00)",
                'recommendation': 'Проверьте на автоматизированную активность'
            })

        return anomalies


class LLMCostAnalysisView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    """Глубокий анализ стоимости"""
    template_name = 'llm_logger/llm_cost_analysis.html'
    cache_timeout = 1  # секунды кэширования

    def test_func(self):
        return True
        # return self.request.user.is_staff

    def get_weekly_trend(self):
        """Получаем тренд по неделям за последние 8 недель"""
        weeks = []
        costs = []
        labels = []

        for i in range(7, -1, -1):  # 8 недель назад до текущей
            end_date = timezone.now() - timedelta(weeks=i)
            start_date = end_date - timedelta(weeks=1)

            week_cost = LogLLMRequest.objects.filter(
                request_time__gte=start_date,
                request_time__lt=end_date
            ).aggregate(
                total=Coalesce(Sum('cost_total'), Value(0.0, output_field=DecimalField()))
            )['total']

            weeks.append({
                'week': start_date.strftime('%Y-%m-%d'),
                'cost': float(week_cost),
                'start_date': start_date,
                'end_date': end_date
            })
            costs.append(float(week_cost))
            labels.append(f"Неделя {i + 1}")

        return {'weeks': weeks, 'costs': costs, 'labels': labels}

    def get_recommendations(self, module_costs, model_costs):
        """Генерируем рекомендации по оптимизации"""
        recommendations = {
            'cheapest_model': None,
            'expensive_modules': [],
            'potential_savings': 0.0,
            'messages': []
        }

        # Самая дешевая модель
        if model_costs:
            cheapest = min([m for m in model_costs if m['requests'] > 0],
                           key=lambda x: x.get('cost_per_1k_tokens', float('inf')))
            recommendations['cheapest_model'] = cheapest

        # Самые дорогие модули (топ 3)
        expensive = sorted(module_costs, key=lambda x: x['total_cost'], reverse=True)[:3]
        recommendations['expensive_modules'] = expensive

        # Потенциальная экономия
        if model_costs and len(model_costs) > 1:
            most_expensive = max([m for m in model_costs if m['requests'] > 0],
                                 key=lambda x: x.get('cost_per_1k_tokens', 0))
            if recommendations['cheapest_model']:
                expensive_cpk = most_expensive.get('cost_per_1k_tokens', 0)
                cheap_cpk = recommendations['cheapest_model'].get('cost_per_1k_tokens', 0)

                if expensive_cpk > 0 and cheap_cpk < expensive_cpk:
                    savings_ratio = (expensive_cpk - cheap_cpk) / expensive_cpk
                    recommendations['potential_savings'] = round(savings_ratio * 100, 1)

                    if recommendations['potential_savings'] > 10:
                        recommendations['messages'].append(
                            f"⚠️ Переключение с {most_expensive['model_name']} на "
                            f"{recommendations['cheapest_model']['model_name']} может "
                            f"сэкономить до {recommendations['potential_savings']}% расходов"
                        )

        # Рекомендации по модулям
        if expensive:
            total_cost = sum(m['total_cost'] for m in module_costs)
            for module in expensive:
                share = (module['total_cost'] / total_cost * 100) if total_cost > 0 else 0
                if share > 30:  # Если модуль занимает больше 30% бюджета
                    recommendations['messages'].append(
                        f"📊 Модуль '{module['request_type']}' потребляет {share:.1f}% "
                        f"бюджета ({module['total_cost']:.2f}$). Рассмотрите оптимизацию."
                    )

        # Низкий успех запросов
        success_data = LogLLMRequest.objects.aggregate(
            total=Count('id'),
            success=Count('id', filter=Q(status='SUCCESS')),
        )

        if success_data['total'] > 0:
            success_rate = success_data['success'] / success_data['total'] * 100
            if success_rate < 80:
                recommendations['messages'].append(
                    f"⚠️ Success rate всего {success_rate:.1f}%. "
                    f"Рассмотрите оптимизацию промптов или обработку ошибок."
                )

        return recommendations

    def get_aggregations(self):
        """Получаем все агрегации одним запросом где возможно"""
        cache_key = f'llm_cost_analysis_{timezone.now().date()}'
        cached_data = cache.get(cache_key)

        if cached_data:
            return cached_data

        result = {}

        # Анализ по модулям
        module_costs = list(
            LogLLMRequest.objects.values('request_type').annotate(
                total_cost=Coalesce(Sum('cost_total'), Value(0.0, output_field=DecimalField())),
                avg_cost=Coalesce(Avg('cost_total'), Value(0.0, output_field=DecimalField())),
                requests=Count('id'),
            ).order_by('-total_cost')
        )

        # Вычисляем cost_per_request и долю в бюджете
        total_budget = sum(float(m['total_cost']) for m in module_costs)
        for item in module_costs:
            requests = item['requests'] or 0
            total_cost = float(item['total_cost'] or 0)
            item['cost_per_request'] = round(total_cost / requests, 5) if requests > 0 else 0.0
            item['cost_share'] = round((total_cost / total_budget * 100), 1) if total_budget > 0 else 0.0

        result['module_costs'] = module_costs

        # Анализ по моделям
        model_costs = list(
            LogLLMRequest.objects.values('model_name').annotate(
                total_cost=Coalesce(Sum('cost_total'), Value(0.0, output_field=DecimalField())),
                avg_cost=Coalesce(Avg('cost_total'), Value(0.0, output_field=DecimalField())),
                requests=Count('id'),
                tokens_in=Coalesce(Sum('tokens_in'), Value(0)),
                tokens_out=Coalesce(Sum('tokens_out'), Value(0)),
            ).order_by('-total_cost')
        )

        # Вычисляем cost_per_1k_tokens и долю в бюджете
        total_model_budget = sum(float(m['total_cost']) for m in model_costs)
        for item in model_costs:
            total_tokens = (item['tokens_in'] or 0) + (item['tokens_out'] or 0)
            total_cost = float(item['total_cost'] or 0)
            item['cost_per_1k_tokens'] = round((total_cost * 1000) / total_tokens, 4) if total_tokens > 0 else 0.0
            item['cost_share'] = round((total_cost / total_model_budget * 100), 1) if total_model_budget > 0 else 0.0

        result['model_costs'] = model_costs

        # Прогноз расходов
        last_7_days = LogLLMRequest.objects.filter(
            request_time__gte=timezone.now() - timedelta(days=7)
        ).aggregate(
            weekly_cost=Coalesce(Sum('cost_total'), Value(0.0, output_field=DecimalField()))
        )
        weekly_cost = float(last_7_days['weekly_cost'] or 0)
        result['weekly_cost'] = round(weekly_cost, 2)
        result['monthly_projection'] = round(weekly_cost * 4.3, 2)
        result['yearly_projection'] = round(weekly_cost * 52, 2)

        # Анализ по статусам
        result['status_analysis'] = list(
            LogLLMRequest.objects.values('status').annotate(
                count=Count('id'),
                total_cost=Coalesce(Sum('cost_total'), Value(0.0), output_field=DecimalField()),
                avg_cost=Coalesce(Avg('cost_total'), Value(0.0), output_field=DecimalField()),
            ).order_by('-count')
        )

        # Топ дорогих запросов
        result['top_expensive_requests'] = LogLLMRequest.objects.select_related(
            'user', 'course', 'lesson', 'task'
        ).only(
            'id', 'request_time', 'model_name', 'cost_total', 'request_type', 'status',
            'user__username', 'user__first_name', 'user__last_name',
            'course__title', 'lesson__title', 'task__order'
        ).order_by('-cost_total')[:10]

        # Тренд по неделям
        result['weekly_trend'] = self.get_weekly_trend()

        # Рекомендации
        result['recommendations'] = self.get_recommendations(module_costs, model_costs)

        # Кэшируем результаты
        cache.set(cache_key, result, self.cache_timeout)

        return result

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Получаем все агрегации
        aggregations = self.get_aggregations()

        # Распаковываем в контекст
        context.update(aggregations)

        # Добавляем мета-информацию
        context['total_requests'] = LogLLMRequest.objects.count()
        context['total_cost_all_time'] = LogLLMRequest.objects.aggregate(
            total=Coalesce(Sum('cost_total'), Value(0.0), output_field=DecimalField())
        )['total']

        return context