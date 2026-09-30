"""HTTP endpoints for companies, contacts, and leads; business logic lives in services, rules, and ranking."""

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from crm import rules, services
from crm.models import Company, Contact, Lead
from crm.ranking import ranked_open_leads
from crm.serializers import (
    ActivitySerializer,
    CompanySerializer,
    ContactSerializer,
    LeadDetailSerializer,
    LeadIntakeSerializer,
    LeadListSerializer,
    LeadUpdateSerializer,
    RankedLeadSerializer,
    ScoreEventSerializer,
    StatusChangeSerializer,
)


class CompanyViewSet(viewsets.ModelViewSet):
    serializer_class = CompanySerializer
    queryset = Company.objects.annotate(lead_count=Count("leads"))
    search_fields = ["name", "domain", "industry"]
    ordering_fields = ["name", "created_at", "lead_count"]


class ContactViewSet(viewsets.ModelViewSet):
    serializer_class = ContactSerializer
    queryset = Contact.objects.all()
    filterset_fields = ["company"]
    search_fields = ["name", "email"]


class LeadViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Leads: create from an inbound request, list and filter, rank, change status, and log activity."""

    queryset = Lead.objects.select_related("company", "contact", "owner")
    filterset_fields = ["status", "qualification", "source", "company", "owner"]
    search_fields = ["company__name", "company__domain", "contact__email", "contact__name", "message"]
    ordering_fields = ["created_at", "fit_score", "last_activity_at"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_serializer_class(self):
        match self.action:
            case "list":
                return LeadListSerializer
            case "create":
                return LeadIntakeSerializer
            case "partial_update":
                return LeadUpdateSerializer
            case "ranked":
                return RankedLeadSerializer
            case "change_status":
                return StatusChangeSerializer
            case "activities":
                return ActivitySerializer
            case "scores":
                return ScoreEventSerializer
            case _:
                return LeadDetailSerializer

    @extend_schema(request=LeadIntakeSerializer, responses={201: LeadDetailSerializer})
    def create(self, request: Request, *args, **kwargs) -> Response:
        intake = LeadIntakeSerializer(data=request.data)
        intake.is_valid(raise_exception=True)
        lead = services.create_lead(services.LeadIntake(**intake.validated_data), owner=request.user)
        lead = self.get_queryset().get(pk=lead.pk)
        return Response(LeadDetailSerializer(lead).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=LeadUpdateSerializer, responses=LeadDetailSerializer)
    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        lead = self.get_object()
        serializer = LeadUpdateSerializer(lead, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        services.bump_ranking_version()
        return Response(LeadDetailSerializer(self.get_queryset().get(pk=lead.pk)).data)

    @extend_schema(responses=RankedLeadSerializer(many=True))
    @action(detail=False, methods=["get"], filterset_fields=[], search_fields=[], ordering_fields=[])
    def ranked(self, request: Request) -> Response:
        """Open leads sorted by priority; each page is cached until any lead or activity changes."""
        version = cache.get(services.RANKING_VERSION_KEY, 0)
        cache_key = f"ranking:v{version}:{request.get_full_path()}"
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        page = self.paginate_queryset(ranked_open_leads())
        data = self.get_paginated_response(RankedLeadSerializer(page, many=True).data).data
        cache.set(cache_key, data, timeout=settings.RANKING_CACHE_SECONDS)
        return Response(data)

    @extend_schema(request=StatusChangeSerializer, responses=LeadDetailSerializer)
    @action(detail=True, methods=["post"], url_path="status")
    def change_status(self, request: Request, pk: str | None = None) -> Response:
        """Move the lead to a new status; only transitions allowed by the rules succeed."""
        serializer = StatusChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.change_status(self.get_object(), serializer.validated_data["status"], user=request.user)
        except rules.InvalidTransition as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(LeadDetailSerializer(self.get_queryset().get(pk=pk)).data)

    @extend_schema(request=None, responses={202: LeadDetailSerializer})
    @action(detail=True, methods=["post"])
    def requalify(self, request: Request, pk: str | None = None) -> Response:
        """Queue the lead for scoring again through n8n."""
        lead = services.request_requalification(self.get_object())
        return Response(LeadDetailSerializer(lead).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(methods=["get"], responses=ActivitySerializer(many=True))
    @extend_schema(methods=["post"], request=ActivitySerializer, responses={201: ActivitySerializer})
    @action(detail=True, methods=["get", "post"], filterset_fields=[], search_fields=[], ordering_fields=[])
    def activities(self, request: Request, pk: str | None = None) -> Response:
        """List the lead's activity timeline, or log a call, email, meeting, or note."""
        lead = self.get_object()
        if request.method == "POST":
            serializer = ActivitySerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            activity = services.log_activity(lead, user=request.user, **serializer.validated_data)
            return Response(ActivitySerializer(activity).data, status=status.HTTP_201_CREATED)
        page = self.paginate_queryset(lead.activities.select_related("created_by"))
        return self.get_paginated_response(ActivitySerializer(page, many=True).data)

    @action(detail=True, methods=["get"], filterset_fields=[], search_fields=[], ordering_fields=[])
    def scores(self, request: Request, pk: str | None = None) -> Response:
        """The lead's scoring history, newest first."""
        page = self.paginate_queryset(self.get_object().score_events.all())
        return self.get_paginated_response(ScoreEventSerializer(page, many=True).data)
