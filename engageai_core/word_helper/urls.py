from django.urls import path
from .views import WordDetailView

app_name = "word_helper"

urlpatterns = [
    path('word/<str:word>/', WordDetailView.as_view(), name='word_detail'),
]
