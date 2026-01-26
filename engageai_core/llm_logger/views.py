from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.db.models import Sum, Avg, Count
from django.utils import timezone
from datetime import timedelta
from .models import LogLLMRequest


@staff_member_required
def llm_analytics_dashboard(request):
    """Аналитический дашборд по использованию LLM"""

    # Период анализа - последняя неделя
    last_week = timezone.now() - timedelta(days=7)

    # Общая статистика
    total_requests = LogLLMRequest.objects.filter(created_at__gte=last_week).count()
    total_cost = LogLLMRequest.objects.filter(created_at__gte=last_week).aggregate(
        total=Sum('cost_total')
    )['total'] or 0

    # Статистика по моделям
    model_stats = LogLLMRequest.objects.filter(created_at__gte=last_week).values(
        'model_name'
    ).annotate(
        count=Count('id'),
        avg_cost=Avg('cost_total'),
        avg_tokens=Avg('tokens_in') + Avg('tokens_out')
    ).order_by('-count')

    # Статистика по пользователям (топ-10 самых активных)
    user_stats = LogLLMRequest.objects.filter(
        created_at__gte=last_week,
        user__isnull=False
    ).values(
        'user__id', 'user__username'
    ).annotate(
        requests=Count('id'),
        total_cost=Sum('cost_total')
    ).order_by('-requests')[:10]

    # Динамика использования по дням
    daily_usage = LogLLMRequest.objects.filter(
        created_at__gte=last_week
    ).extra(
        select={'day': "date(created_at)"}
    ).values('day').annotate(
        count=Count('id'),
        cost=Sum('cost_total'),
        tokens=Sum('tokens_in') + Sum('tokens_out')
    ).order_by('day')

    context = {
        'total_requests': total_requests,
        'total_cost': round(total_cost, 4),
        'model_stats': model_stats,
        'user_stats': user_stats,
        'daily_usage': list(daily_usage),
        'period_start': last_week.strftime('%Y-%m-%d'),
        'period_end': timezone.now().strftime('%Y-%m-%d'),
    }

    return render(request, 'curriculum/admin/llm_analytics.html', context)