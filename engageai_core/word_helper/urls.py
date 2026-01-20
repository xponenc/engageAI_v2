from django.urls import path
from .views import WordDetailView

urlpatterns = [
    path('api/word/<str:word>/', WordDetailView.as_view(), name='word_detail'),
]