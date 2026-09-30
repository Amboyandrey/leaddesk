"""Inbound integration endpoints, used by machine accounts rather than people."""

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from crm import services
from crm.models import Lead
from crm.n8n import Qualification
from crm.permissions import CanIngestN8nResults
from crm.serializers import N8nResultSerializer


class N8nLeadScoredView(APIView):
    """n8n calls this after every Qualify Lead run, so leads scored anywhere show up here in real time."""

    permission_classes = [CanIngestN8nResults]

    @extend_schema(
        request=N8nResultSerializer,
        responses=inline_serializer(
            "N8nLeadScoredResponse",
            {
                "lead_id": serializers.IntegerField(),
                "status": serializers.CharField(),
                "fit_score": serializers.IntegerField(),
            },
        ),
    )
    def post(self, request: Request) -> Response:
        serializer = N8nResultSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        lead = services.ingest_n8n_result(
            services.LeadIntake(
                website=data["website"],
                contact_name=data["contact_name"],
                contact_email=data["contact_email"],
                message=data["message"],
                source=Lead.Source.N8N,
            ),
            Qualification(
                fit_score=data["fit_score"],
                industry=data["industry"][:200],
                company_summary=data["company_summary"],
                need=data["need"],
                suggested_reply=data["suggested_reply"],
                raw=dict(request.data),
                external_id=data["execution_id"],
            ),
        )
        return Response({"lead_id": lead.pk, "status": lead.status, "fit_score": lead.fit_score})
