"""Write operations for the CRM; views and tasks call these instead of touching models directly."""

from dataclasses import dataclass

from django.contrib.auth.models import AbstractBaseUser
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from crm import rules
from crm.models import Activity, Company, Contact, Lead, ScoreEvent
from crm.n8n import Qualification

RANKING_VERSION_KEY = "ranking:version"


def bump_ranking_version() -> None:
    """Invalidate every cached ranking page by moving to a new cache key version."""
    try:
        cache.incr(RANKING_VERSION_KEY)
    except ValueError:
        cache.set(RANKING_VERSION_KEY, 1, timeout=None)


@dataclass(frozen=True)
class LeadIntake:
    """Validated input for a new inbound lead."""

    website: str
    contact_name: str
    contact_email: str
    message: str
    company_name: str = ""
    source: str = Lead.Source.API


def create_lead(intake: LeadIntake, *, owner: AbstractBaseUser | None = None, enqueue: bool = True) -> Lead:
    """Create a lead, reusing the company by domain and the contact by email, then queue scoring."""
    from crm.tasks import qualify_lead_task

    domain = rules.normalize_domain(intake.website)
    with transaction.atomic():
        company, _ = Company.objects.get_or_create(
            domain=domain, defaults={"name": intake.company_name or domain}
        )
        contact = Contact.objects.filter(email__iexact=intake.contact_email).first()
        if contact is None:
            contact = Contact.objects.create(
                company=company, name=intake.contact_name, email=intake.contact_email
            )
        lead = Lead.objects.create(
            company=company,
            contact=contact,
            owner=owner,
            message=intake.message,
            source=intake.source,
        )
        bump_ranking_version()
        if enqueue:
            transaction.on_commit(lambda: qualify_lead_task.delay(lead.pk))
    return lead


def request_requalification(lead: Lead) -> Lead:
    """Put a lead back in the scoring queue."""
    from crm.tasks import qualify_lead_task

    with transaction.atomic():
        lead.qualification = Lead.Qualification.PENDING
        lead.qualification_error = ""
        lead.save(update_fields=["qualification", "qualification_error", "updated_at"])
        transaction.on_commit(lambda: qualify_lead_task.delay(lead.pk))
    return lead


def apply_qualification(
    lead_id: int, result: Qualification, *, source: str = ScoreEvent.Source.N8N_MCP
) -> Lead:
    """Record a scoring result, update the lead, and apply the status rules; a repeated run id is a no-op."""
    score = rules.normalize_score(result.fit_score)
    suggested = rules.status_for_score(score)
    with transaction.atomic():
        lead = Lead.objects.select_for_update().select_related("company").get(pk=lead_id)
        if result.external_id and ScoreEvent.objects.filter(external_id=result.external_id).exists():
            return lead
        try:
            with transaction.atomic():
                ScoreEvent.objects.create(
                    lead=lead,
                    source=source,
                    external_id=result.external_id,
                    fit_score=score,
                    suggested_status=suggested,
                    raw=result.raw,
                )
        except IntegrityError:
            # The same run was recorded concurrently on another lead row; keep the first copy
            return lead
        company = lead.company
        company.industry = result.industry or company.industry
        company.summary = result.company_summary or company.summary
        company.save(update_fields=["industry", "summary", "updated_at"])

        lead.fit_score = score
        lead.need = result.need
        lead.suggested_reply = result.suggested_reply
        lead.qualification = Lead.Qualification.DONE
        lead.qualification_error = ""
        lead.qualified_at = timezone.now()
        if lead.status in rules.AI_MAY_SET_STATUS_FROM:
            lead.status = suggested
        lead.save()
        bump_ranking_version()
    return lead


def ingest_n8n_result(
    intake: LeadIntake, result: Qualification, *, score_source: str = ScoreEvent.Source.N8N_PUSH
) -> Lead:
    """Record an n8n result, attaching it to the contact's latest active lead or creating one."""
    domain = rules.normalize_domain(intake.website)
    with transaction.atomic():
        company, _ = Company.objects.get_or_create(domain=domain, defaults={"name": domain})
        contact = Contact.objects.filter(email__iexact=intake.contact_email).first()
        if contact is None:
            contact = Contact.objects.create(
                company=company, name=intake.contact_name or intake.contact_email, email=intake.contact_email
            )
        lead = (
            Lead.objects.select_for_update()
            .filter(company=company, contact=contact)
            .exclude(status__in=[Lead.Status.WON, Lead.Status.LOST])
            .order_by("-created_at")
            .first()
        )
        if lead is None:
            lead = Lead.objects.create(
                company=company, contact=contact, message=intake.message, source=intake.source
            )
        return apply_qualification(lead.pk, result, source=score_source)


def mark_qualification_failed(lead_id: int, error: str) -> None:
    """Record that scoring gave up, so the lead can be retried from the API."""
    Lead.objects.filter(pk=lead_id).update(
        qualification=Lead.Qualification.FAILED, qualification_error=error[:500], updated_at=timezone.now()
    )


def change_status(lead: Lead, target: str, *, user: AbstractBaseUser | None = None) -> Lead:
    """Move a lead to a new status if the rules allow it, logging the change as a note."""
    with transaction.atomic():
        lead = Lead.objects.select_for_update().get(pk=lead.pk)
        rules.ensure_transition(lead.status, target)
        previous = lead.status
        lead.status = target
        lead.save(update_fields=["status", "updated_at"])
        Activity.objects.create(
            lead=lead,
            kind=Activity.Kind.NOTE,
            body=f"Status changed from {previous} to {target}.",
            occurred_at=timezone.now(),
            created_by=user,
        )
        bump_ranking_version()
    return lead


def log_activity(lead: Lead, *, kind: str, body: str, occurred_at, user: AbstractBaseUser | None) -> Activity:
    """Add an activity to a lead and move its last-touch time forward if this one is newer."""
    with transaction.atomic():
        activity = Activity.objects.create(
            lead=lead, kind=kind, body=body, occurred_at=occurred_at, created_by=user
        )
        Lead.objects.filter(pk=lead.pk).exclude(last_activity_at__gte=occurred_at).update(
            last_activity_at=occurred_at, updated_at=timezone.now()
        )
        bump_ranking_version()
    return activity
