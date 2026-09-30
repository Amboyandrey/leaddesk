from django.contrib.auth import views as auth_views
from django.urls import path

from ui import views

app_name = "ui"

urlpatterns = [
    path("", views.board, name="board"),
    path("login/", auth_views.LoginView.as_view(template_name="ui/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("leads/new/", views.lead_new, name="lead_new"),
    path("leads/<int:pk>/", views.lead_detail, name="lead"),
    path("leads/<int:pk>/header/", views.lead_header, name="lead_header"),
    path("leads/<int:pk>/details/", views.lead_details, name="lead_details"),
    path("leads/<int:pk>/status/", views.lead_status, name="lead_status"),
    path("leads/<int:pk>/ai/", views.lead_ai, name="lead_ai"),
    path("leads/<int:pk>/requalify/", views.lead_requalify, name="lead_requalify"),
    path("leads/<int:pk>/activities/", views.lead_activities, name="lead_activities"),
    path("companies/", views.companies, name="companies"),
]
