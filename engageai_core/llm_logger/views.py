from django.db.models import Count, Sum, Avg, Q, F, FloatField, ExpressionWrapper
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth, TruncHour
from django.utils import timezone
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from datetime import timedelta
from django.core.cache import cache

from llm_logger.models import LLMRequestType, LogLLMRequest


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
        totals = cache.get(cache_key)

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
        return self.request.user.is_staff

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_id = self.kwargs.get('user_id')

        # Оптимизированный queryset с аннотациями
        user_logs = LogLLMRequest.objects.filter(
            user_id=user_id
        ).select_related(
            'course', 'lesson', 'task'
        ).annotate(
            day=TruncDate('request_time')
        ).values(
            'day', 'request_type', 'model_name', 'status'
        ).annotate(
            requests=Count('id'),
            cost=Sum('cost_total'),
            avg_duration=Avg('duration_sec'),
        ).order_by('-day')

        # Статистика по типам запросов
        type_breakdown = LogLLMRequest.objects.filter(
            user_id=user_id
        ).values('request_type').annotate(
            count=Count('id'),
            cost=Sum('cost_total'),
            avg_cost=Avg('cost_total'),
        ).order_by('-count')

        context['user_logs'] = user_logs
        context['type_breakdown'] = type_breakdown
        context['user_id'] = user_id

        return context


class LLMCostAnalysisView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    """Глубокий анализ стоимости"""
    template_name = 'llm_logger/llm_cost_analysis.html'

    def test_func(self):
        return self.request.user.is_staff

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Анализ стоимости по модулям
        module_costs = LogLLMRequest.objects.values('request_type').annotate(
            total_cost=Sum('cost_total'),
            avg_cost=Avg('cost_total'),
            requests=Count('id'),
            cost_per_request=Sum('cost_total') / Count('id'),
        ).order_by('-total_cost')

        # Анализ стоимости по моделям
        model_costs = LogLLMRequest.objects.values('model_name').annotate(
            total_cost=Sum('cost_total'),
            avg_cost=Avg('cost_total'),
            requests=Count('id'),
            tokens_in=Sum('tokens_in'),
            tokens_out=Sum('tokens_out'),
            cost_per_1k_tokens=ExpressionWrapper(
                Sum('cost_total') * 1000 / (Sum('tokens_in') + Sum('tokens_out')),
                output_field=FloatField()
            )
        ).order_by('-total_cost')

        # Прогноз расходов на месяц
        last_7_days = LogLLMRequest.objects.filter(
            request_time__gte=timezone.now() - timedelta(days=7)
        ).aggregate(
            weekly_cost=Sum('cost_total')
        )

        monthly_projection = (last_7_days['weekly_cost'] or 0) * 4.3

        context['module_costs'] = list(module_costs)
        context['model_costs'] = list(model_costs)
        context['monthly_projection'] = round(monthly_projection, 2)

        return context