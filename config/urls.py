"""Routes: the CRM API under /api/, token login, OpenAPI docs, and the Django admin."""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import DefaultRouter

from crm.integrations import N8nLeadScoredView
from crm.views import CompanyViewSet, ContactViewSet, LeadViewSet

router = DefaultRouter()
router.register("companies", CompanyViewSet, basename="company")
router.register("contacts", ContactViewSet, basename="contact")
router.register("leads", LeadViewSet, basename="lead")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(router.urls)),
    path("api/auth/token/", obtain_auth_token, name="api-token"),
    path("api-auth/", include("rest_framework.urls")),
    path("api/integrations/n8n/lead-scored/", N8nLeadScoredView.as_view(), name="n8n-lead-scored"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]
