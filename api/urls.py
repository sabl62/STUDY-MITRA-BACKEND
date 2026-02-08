from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from .views import (
    RegisterView,
    StudyPostViewSet,
    StudySessionViewSet,
    ConversationNoteViewSet,
    UserProfileViewSet,
    ExamPrepView,
)

router = DefaultRouter()
router.register(r'study-posts', StudyPostViewSet, basename='studypost')
router.register(r'sessions', StudySessionViewSet, basename='session')
router.register(r'notes', ConversationNoteViewSet, basename='note')
router.register(r'userprofile', UserProfileViewSet, basename='userprofile')

urlpatterns = [

    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('exam-prep/', ExamPrepView.as_view(), name='exam-prep-base'),
    path('exam-prep/solve/', ExamPrepView.as_view(http_method_names=['post']), name='exam-solve'),
    path('', include(router.urls)),
]