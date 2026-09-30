"""The HTTP API end to end: intake, status rules, activities, ranking, caching, and query counts."""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from crm.models import Company, Contact, Lead

pytestmark = pytest.mark.django_db

INTAKE = {
    "website": "https://www.Acme.com/contact",
    "contact_name": "Jane Doe",
    "contact_email": "jane@acme.com",
    "message": "We want an AI chatbot for our docs.",
}


def _create(api: APIClient, **overrides: str) -> dict:
    response = api.post("/api/leads/", {**INTAKE, **overrides}, format="json")
    assert response.status_code == 201, response.data
    return response.data


def test_requests_without_a_token_are_rejected() -> None:
    assert APIClient().get("/api/leads/").status_code == 401


def test_intake_creates_and_scores_a_lead(api, fake_n8n, django_capture_on_commit_callbacks) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        data = _create(api)
    assert data["company"]["domain"] == "acme.com"
    lead = Lead.objects.get(pk=data["id"])
    assert (lead.status, lead.fit_score, lead.qualification) == (Lead.Status.QUALIFIED, 85, "done")
    assert lead.company.industry == "Software"


def test_intake_reuses_the_company_and_contact(api, fake_n8n) -> None:
    _create(api)
    _create(api, website="acme.com", contact_email="JANE@acme.com", message="Following up")
    assert Company.objects.count() == 1
    assert Contact.objects.count() == 1
    assert Lead.objects.count() == 2


def test_intake_rejects_a_website_without_a_domain(api) -> None:
    response = api.post("/api/leads/", {**INTAKE, "website": "localhost"}, format="json")
    assert response.status_code == 400
    assert "website" in response.data


def test_allowed_status_change_logs_a_note(api) -> None:
    lead_id = _create(api)["id"]
    response = api.post(f"/api/leads/{lead_id}/status/", {"status": "contacted"}, format="json")
    assert response.status_code == 200
    assert response.data["status"] == "contacted"
    notes = api.get(f"/api/leads/{lead_id}/activities/").data["results"]
    assert notes[0]["body"] == "Status changed from new to contacted."


def test_disallowed_status_change_is_a_conflict(api) -> None:
    lead_id = _create(api)["id"]
    response = api.post(f"/api/leads/{lead_id}/status/", {"status": "won"}, format="json")
    assert response.status_code == 409
    assert "Allowed" in response.data["detail"]


def test_logging_activity_moves_last_touch_forward_only(api) -> None:
    lead_id = _create(api)["id"]
    newer, older = timezone.now(), timezone.now() - timedelta(days=3)
    for when in (newer, older):
        api.post(
            f"/api/leads/{lead_id}/activities/",
            {"kind": "call", "body": "Intro call", "occurred_at": when.isoformat()},
            format="json",
        )
    assert Lead.objects.get(pk=lead_id).last_activity_at == newer


def _lead(domain: str, score: int | None, days_old: int, status: str = Lead.Status.QUALIFIED) -> Lead:
    company = Company.objects.create(name=domain, domain=domain)
    lead = Lead.objects.create(company=company, fit_score=score, status=status)
    Lead.objects.filter(pk=lead.pk).update(created_at=timezone.now() - timedelta(days=days_old))
    return lead


def test_ranking_decays_stale_leads_and_hides_closed_ones(api) -> None:
    fresh = _lead("fresh.com", 70, days_old=0)
    stale = _lead("stale.com", 95, days_old=28)
    _lead("won.com", 99, days_old=0, status=Lead.Status.WON)
    results = api.get("/api/leads/ranked/").data["results"]
    assert [row["id"] for row in results] == [fresh.pk, stale.pk]
    assert results[0]["priority"] == pytest.approx(70.0, abs=0.1)
    assert results[1]["priority"] == pytest.approx(95 * 0.25, abs=0.1)


def test_recent_activity_lifts_a_lead(api) -> None:
    quiet = _lead("quiet.com", 60, days_old=0)
    busy = _lead("busy.com", 50, days_old=0)
    for _ in range(3):
        api.post(
            f"/api/leads/{busy.pk}/activities/",
            {"kind": "email", "body": "", "occurred_at": timezone.now().isoformat()},
            format="json",
        )
    results = api.get("/api/leads/ranked/").data["results"]
    assert [row["id"] for row in results] == [busy.pk, quiet.pk]
    assert results[0]["recent_activity_count"] == 3


def test_ranking_is_cached_until_a_lead_changes(api) -> None:
    lead = _lead("acme.com", 80, days_old=0)
    first = api.get("/api/leads/ranked/").data
    Lead.objects.filter(pk=lead.pk).update(fit_score=10)
    assert api.get("/api/leads/ranked/").data == first
    api.post(f"/api/leads/{lead.pk}/status/", {"status": "contacted"}, format="json")
    assert api.get("/api/leads/ranked/").data["results"][0]["status"] == "contacted"


def test_list_and_ranking_use_a_constant_number_of_queries(api, django_assert_max_num_queries) -> None:
    for index in range(20):
        _lead(f"company{index}.com", 50 + index, days_old=index)
    with django_assert_max_num_queries(3):
        assert len(api.get("/api/leads/").data["results"]) == 20
    with django_assert_max_num_queries(3):
        assert len(api.get("/api/leads/ranked/").data["results"]) == 20
