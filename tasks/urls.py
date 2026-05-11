from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import AISuggestView, MeView, ProjectViewSet, RegisterView, TaskViewSet

router = DefaultRouter()
router.register(r'projects', ProjectViewSet, basename='project')
router.register(r'tasks', TaskViewSet, basename='task')

urlpatterns = [
    # Auth
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', TokenObtainPairView.as_view(), name='token_obtain'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/me/', MeView.as_view(), name='me'),
    # AI
    path('tasks/suggest/', AISuggestView.as_view(), name='ai-suggest'),
    # ViewSets (projects + tasks CRUD + task actions)
    path('', include(router.urls)),
]
