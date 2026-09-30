"""Background jobs: scoring a lead through the n8n MCP server, with retries for outages."""

import logging

from celery import shared_task

from crm import n8n, services
from crm.models import Lead

logger = logging.getLogger(__name__)

MAX_RETRIES = 4


@shared_task(bind=True, max_retries=MAX_RETRIES, acks_late=True)
def qualify_lead_task(self, lead_id: int) -> str:
    """Score one pending lead; retries outages with backoff, and marks the lead failed when it gives up."""
    lead = Lead.objects.select_related("company", "contact").filter(pk=lead_id).first()
    if lead is None or lead.qualification != Lead.Qualification.PENDING:
        return "skipped"

    try:
        result = n8n.qualify(
            website=lead.company.domain,
            contact_name=lead.contact.name if lead.contact else "",
            contact_email=lead.contact.email if lead.contact else "",
            message=lead.message,
        )
    except n8n.N8nUnavailable as exc:
        if self.request.retries >= MAX_RETRIES:
            services.mark_qualification_failed(lead_id, str(exc))
            logger.warning("Gave up scoring lead %s: %s", lead_id, exc)
            return "failed"
        raise self.retry(exc=exc, countdown=min(120, 5 * 2**self.request.retries)) from exc
    except n8n.N8nBadResult as exc:
        services.mark_qualification_failed(lead_id, str(exc))
        logger.warning("Could not use scoring result for lead %s: %s", lead_id, exc)
        return "failed"

    services.apply_qualification(lead_id, result)
    return "done"
