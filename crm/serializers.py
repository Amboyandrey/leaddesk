"""Request and response shapes for the CRM API."""

from rest_framework import serializers

from crm import rules
from crm.models import Activity, Company, Contact, Lead, ScoreEvent


class CompanySerializer(serializers.ModelSerializer):
    lead_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Company
        fields = ["id", "name", "domain", "industry", "summary", "lead_count", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def validate_domain(self, value: str) -> str:
        domain = rules.normalize_domain(value)
        if "." not in domain:
            raise serializers.ValidationError("Enter a domain like acme.com.")
        return domain


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = ["id", "company", "name", "email", "created_at"]
        read_only_fields = ["created_at"]


class CompanyBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ["id", "name", "domain", "industry"]


class ContactBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = ["id", "name", "email"]


class LeadListSerializer(serializers.ModelSerializer):
    company = CompanyBriefSerializer(read_only=True)
    contact = ContactBriefSerializer(read_only=True)
    owner = serializers.SlugRelatedField(slug_field="username", read_only=True)

    class Meta:
        model = Lead
        fields = [
            "id",
            "company",
            "contact",
            "owner",
            "status",
            "fit_score",
            "qualification",
            "source",
            "created_at",
            "last_activity_at",
        ]


class LeadDetailSerializer(LeadListSerializer):
    class Meta(LeadListSerializer.Meta):
        fields = [
            *LeadListSerializer.Meta.fields,
            "message",
            "need",
            "suggested_reply",
            "qualification_error",
            "qualified_at",
            "updated_at",
        ]


class RankedLeadSerializer(LeadListSerializer):
    priority = serializers.FloatField(read_only=True)
    recent_activity_count = serializers.IntegerField(read_only=True)

    class Meta(LeadListSerializer.Meta):
        fields = [*LeadListSerializer.Meta.fields, "priority", "recent_activity_count"]


class LeadIntakeSerializer(serializers.Serializer):
    """An inbound lead: the company website, the person, and what they asked for."""

    website = serializers.CharField(max_length=300)
    company_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    contact_name = serializers.CharField(max_length=200)
    contact_email = serializers.EmailField()
    message = serializers.CharField(max_length=5000, allow_blank=True)

    def validate_website(self, value: str) -> str:
        domain = rules.normalize_domain(value)
        if "." not in domain:
            raise serializers.ValidationError("Enter a website like acme.com.")
        return domain


class LeadUpdateSerializer(serializers.ModelSerializer):
    """Fields a user may edit directly; status changes go through the status action instead."""

    class Meta:
        model = Lead
        fields = ["owner", "message"]


class StatusChangeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Lead.Status.choices)


class ActivitySerializer(serializers.ModelSerializer):
    created_by = serializers.SlugRelatedField(slug_field="username", read_only=True)

    class Meta:
        model = Activity
        fields = ["id", "kind", "body", "occurred_at", "created_by", "created_at"]
        read_only_fields = ["created_by", "created_at"]


class ScoreEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScoreEvent
        fields = ["id", "source", "external_id", "fit_score", "suggested_status", "raw", "created_at"]


class N8nResultSerializer(serializers.Serializer):
    """One scoring result pushed by the n8n Qualify Lead workflow."""

    execution_id = serializers.CharField(max_length=100)
    website = serializers.CharField(max_length=300)
    contact_name = serializers.CharField(max_length=200, allow_blank=True, default="")
    contact_email = serializers.EmailField()
    message = serializers.CharField(max_length=5000, allow_blank=True, default="")
    fit_score = serializers.FloatField()
    industry = serializers.CharField(allow_blank=True, default="")
    company_summary = serializers.CharField(allow_blank=True, default="")
    need = serializers.CharField(allow_blank=True, default="")
    suggested_reply = serializers.CharField(allow_blank=True, default="")

    def validate_website(self, value: str) -> str:
        domain = rules.normalize_domain(value)
        if "." not in domain:
            raise serializers.ValidationError("Enter a website like acme.com.")
        return domain
