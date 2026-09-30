"""Real-time push from n8n: upserts, one record per n8n run, and a push-only machine account."""

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from crm import n8n, services
from crm.models import Lead, ScoreEvent

pytestmark = pytest.mark.django_db

URL = "/api/integrations/n8n/lead-scored/"
PUSH = {
    "execution_id": "501",
    "website": "n8n.io",
    "contact_name": "Maria Santos",
    "contact_email": "maria@example.com",
    "message": "Docs chatbot",
    "fit_score": 90,
    "industry": "Automation",
    "company_summary": "Workflow tool.",
    "need": "AI assistant",
    "suggested_reply": "Hi Maria",
}


@pytest.fixture
def integration(capsys) -> APIClient:
    call_command("create_n8n_integration_user")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {capsys.readouterr().out.strip()}")
    return client


def test_push_creates_a_scored_lead(integration) -> None:
    response = integration.post(URL, PUSH, format="json")
    assert response.status_code == 200
    lead = Lead.objects.get(pk=response.data["lead_id"])
    assert (lead.source, lead.status, lead.fit_score, lead.qualification) == ("n8n", "qualified", 90, "done")
    assert lead.score_events.get().external_id == "501"


def test_the_same_run_pushed_twice_is_stored_once(integration) -> None:
    integration.post(URL, PUSH, format="json")
    integration.post(URL, PUSH, format="json")
    assert Lead.objects.count() == 1
    assert ScoreEvent.objects.count() == 1


def test_a_new_run_for_the_same_contact_updates_their_open_lead(integration) -> None:
    integration.post(URL, PUSH, format="json")
    integration.post(URL, {**PUSH, "execution_id": "502", "fit_score": 30}, format="json")
    lead = Lead.objects.get()
    assert (lead.fit_score, lead.status) == (30, "not_a_fit")
    assert lead.score_events.count() == 2


def test_mcp_reply_and_push_for_one_run_do_not_double_count(integration) -> None:
    """LeadDesk scores its own lead; n8n also pushes that same run. One lead, one score event."""
    lead = services.create_lead(
        services.LeadIntake(
            website="n8n.io", contact_name="Maria Santos", contact_email="maria@example.com", message="hi"
        ),
        enqueue=False,
    )
    integration.post(URL, PUSH, format="json")
    reply = n8n.parse_result('[{"fit_score": 90, "execution_id": "501"}]')
    services.apply_qualification(lead.pk, reply)
    assert Lead.objects.count() == 1
    assert ScoreEvent.objects.filter(lead=lead).count() == 1


def test_a_closed_lead_is_not_reopened_by_a_push(integration) -> None:
    integration.post(URL, PUSH, format="json")
    Lead.objects.update(status=Lead.Status.WON)
    integration.post(URL, {**PUSH, "execution_id": "503"}, format="json")
    assert Lead.objects.filter(status=Lead.Status.WON).count() == 1
    assert Lead.objects.count() == 2


def test_people_cannot_push_and_the_integration_cannot_read(api, integration) -> None:
    assert api.post(URL, PUSH, format="json").status_code == 403
    assert integration.get("/api/leads/").status_code == 403


def test_rotating_the_token_replaces_it(capsys) -> None:
    call_command("create_n8n_integration_user")
    first = capsys.readouterr().out.strip()
    call_command("create_n8n_integration_user", "--rotate")
    second = capsys.readouterr().out.strip()
    assert first != second
    assert Token.objects.get(user=User.objects.get(username="n8n-integration")).key == second
