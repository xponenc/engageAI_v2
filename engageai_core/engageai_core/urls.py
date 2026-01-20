"""
URL configuration for engageai_core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView, TemplateView

urlpatterns = [
    path('', TemplateView.as_view(template_name="index.html"), name="index"),
    path('admin/', admin.site.urls),
    path('accounts/', include('users.urls')),

    # API версия 1 (единый префикс для всех API)
    path('api/v1/', include([
        path('assessment/', include('assessment.urls_api', namespace='assessment-api')),
        path('chat/', include('chat.urls_api', namespace='chat-api')),
        path('assistant/', include('ai_assistant.urls_api', namespace='assistant-api')),
        # path('curriculum/', include('curriculum.urls_api', namespace='curriculum-api')),
    ])),

    # UI/веб-версия (без api/v1 префикса)
    path('assessment/', include('assessment.urls', namespace='assessment')),
    path('chat/', include('chat.urls', namespace='chat')),
    path('assistant/', include('ai_assistant.urls', namespace='assistant')),
    path('curriculum/', include('curriculum.urls', namespace='curriculum')),
]


if settings.DEBUG:
    from debug_toolbar.toolbar import debug_toolbar_urls

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += debug_toolbar_urls()
