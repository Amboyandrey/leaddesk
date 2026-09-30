"""CRM domain: companies, their contacts, sales leads, the activity on each lead, and its score history."""

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower


class TimestampedModel(models.Model):
    """Adds created and updated timestamps to every table."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Company(TimestampedModel):
    """An organization identified by its website domain, which is unique and stored lowercase."""

    name = models.CharField(max_length=200)
    domain = models.CharField(max_length=253, unique=True)
    industry = models.CharField(max_length=200, blank=True)
    summary = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "companies"

    def __str__(self) -> str:
        return self.domain

    def save(self, *args, **kwargs) -> None:
        self.domain = self.domain.strip().lower()
        super().save(*args, **kwargs)


class Contact(TimestampedModel):
    """A person at a company; an email address belongs to exactly one contact."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=200)
    email = models.EmailField()

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(Lower("email"), name="contact_email_ci_unique")]

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"


class Lead(TimestampedModel):
    """One sales opportunity: who asked, what they need, how well they fit, and where it stands."""

    class Status(models.TextChoices):
        NEW = "new", "New"
        QUALIFIED = "qualified", "Qualified"
        NEEDS_REVIEW = "needs_review", "Needs review"
        NOT_A_FIT = "not_a_fit", "Not a fit"
        CONTACTED = "contacted", "Contacted"
        WON = "won", "Won"
        LOST = "lost", "Lost"

    class Qualification(models.TextChoices):
        PENDING = "pending", "Pending"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    class Source(models.TextChoices):
        API = "api", "API"
        IMPORT = "import", "Import"
        N8N = "n8n", "n8n"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="leads")
    contact = models.ForeignKey(
        Contact, on_delete=models.SET_NULL, null=True, blank=True, related_name="leads"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="leads"
    )
    message = models.TextField(blank=True)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.API)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    fit_score = models.PositiveSmallIntegerField(null=True, blank=True)
    need = models.TextField(blank=True)
    suggested_reply = models.TextField(blank=True)
    qualification = models.CharField(
        max_length=20, choices=Qualification.choices, default=Qualification.PENDING
    )
    qualification_error = models.CharField(max_length=500, blank=True)
    qualified_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(fit_score__isnull=True) | models.Q(fit_score__lte=100),
                name="lead_fit_score_0_100",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="lead_status_created_idx"),
            models.Index(
                fields=["qualification"],
                name="lead_qualification_pending_idx",
                condition=models.Q(qualification="pending"),
            ),
        ]

    def __str__(self) -> str:
        return f"Lead #{self.pk} ({self.company_id}, {self.status})"


class Activity(models.Model):
    """Something that happened on a lead, such as a call, email, or meeting."""

    class Kind(models.TextChoices):
        NOTE = "note", "Note"
        EMAIL = "email", "Email"
        CALL = "call", "Call"
        MEETING = "meeting", "Meeting"

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="activities")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    body = models.TextField(blank=True)
    occurred_at = models.DateTimeField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        verbose_name_plural = "activities"
        indexes = [models.Index(fields=["lead", "-occurred_at"], name="activity_lead_time_idx")]

    def __str__(self) -> str:
        return f"{self.kind} on lead #{self.lead_id}"


class ScoreEvent(models.Model):
    """One scoring result for a lead, kept as history rather than overwritten."""

    class Source(models.TextChoices):
        N8N_MCP = "n8n_mcp", "n8n MCP"
        N8N_PUSH = "n8n_push", "n8n push"
        IMPORT = "import", "Import"

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="score_events")
    source = models.CharField(max_length=20, choices=Source.choices)
    # The n8n execution id; NULL (not "") when absent so the partial unique constraint skips it
    external_id = models.CharField(max_length=100, null=True, blank=True)  # noqa: DJ001
    fit_score = models.PositiveSmallIntegerField()
    suggested_status = models.CharField(max_length=20, choices=Lead.Status.choices)
    raw = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [("ingest_n8n_results", "Can push n8n scoring results")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(fit_score__lte=100), name="score_event_fit_score_0_100"
            ),
            models.UniqueConstraint(
                fields=["external_id"],
                condition=models.Q(external_id__isnull=False),
                name="score_event_external_id_unique",
            ),
        ]
        indexes = [models.Index(fields=["lead", "-created_at"], name="score_event_lead_time_idx")]

    def __str__(self) -> str:
        return f"{self.fit_score} for lead #{self.lead_id}"
