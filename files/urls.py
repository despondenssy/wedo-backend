from django.urls import path
from .views import FileUploadView, FileDetailView

urlpatterns = [
    path('files', FileUploadView.as_view()),
    path('files/<int:file_id>', FileDetailView.as_view()),
]
