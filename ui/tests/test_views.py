"""The web UI: sign-in protection, the leads board, lead pages, and the HTMX partials."""

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client

from crm.models import Activity, Company, Lead

pytestmark = pytest.mark.django_db

HTMX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def browser(user) -> Client:
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def lead() -> Lead:
    company = Company.objects.create(name="Acme", domain="acme.com", industry="Retail")
    return Lead.objects.create(
        company=company, fit_score=80, status=Lead.Status.QUALIFIED, qualification="done"
    )


def test_pages_require_sign_in() -> None:
    response = Client().get("/")
    assert response.status_code == 302
    assert response["Location"].startswith("/login/")


def test_the_integration_account_cannot_use_the_ui(capsys) -> None:
    call_command("create_n8n_integration_user")
    client = Client()
    client.force_login(User.objects.get(username="n8n-integration"))
    assert client.get("/").status_code == 403


def test_board_ranks_open_leads(browser, lead) -> None:
    response = browser.get("/")
    assert response.status_code == 200
    assert b"acme.com" in response.content
    assert b"Priority" in response.content


def test_board_search_returns_only_the_rows_for_htmx(browser, lead) -> None:
    response = browser.get("/?view=all&q=acme", **HTMX)
    assert b"acme.com" in response.content
    assert b"<html" not in response.content
    assert b"acme.com" not in browser.get("/?view=all&q=nomatch", **HTMX).content


def test_creating_a_lead_queues_scoring_and_opens_it(
    browser, fake_n8n, django_capture_on_commit_callbacks
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        response = browser.post(
            "/leads/new/",
            {
                "website": "https://www.Notion.so",
                "contact_name": "Liza Tan",
                "contact_email": "liza@example.com",
                "message": "Help center bot",
            },
        )
    lead = Lead.objects.get()
    assert response.status_code == 302 and response["Location"] == f"/leads/{lead.pk}/"
    assert (lead.company.domain, lead.fit_score) == ("notion.so", 85)


def test_invalid_website_shows_an_error(browser) -> None:
    response = browser.post(
        "/leads/new/", {"website": "localhost", "contact_name": "X", "contact_email": "x@example.com"}
    )
    assert b"Enter a website like acme.com." in response.content
    assert not Lead.objects.exists()


def test_detail_offers_only_allowed_status_moves(browser, lead) -> None:
    content = browser.get(f"/leads/{lead.pk}/").content
    assert b"Mark contacted" in content
    assert b"Mark won" not in content


def test_status_change_refreshes_the_timeline(browser, lead) -> None:
    response = browser.post(f"/leads/{lead.pk}/status/", {"status": "contacted"}, **HTMX)
    assert response["HX-Trigger"] == "activity-changed"
    assert b"Mark won" in response.content
    assert Activity.objects.filter(lead=lead, kind="note").exists()


def test_disallowed_status_change_shows_why(browser, lead) -> None:
    response = browser.post(f"/leads/{lead.pk}/status/", {"status": "won"}, **HTMX)
    assert b"Cannot move a lead" in response.content
    assert "HX-Trigger" not in response
    lead.refresh_from_db()
    assert lead.status == Lead.Status.QUALIFIED


def test_ai_panel_polls_while_pending_and_stops_when_scored(browser, lead) -> None:
    Lead.objects.filter(pk=lead.pk).update(qualification="pending")
    pending = browser.get(f"/leads/{lead.pk}/ai/", **HTMX)
    assert b'hx-trigger="every 2s"' in pending.content
    assert "HX-Trigger" not in pending

    Lead.objects.filter(pk=lead.pk).update(qualification="done")
    done = browser.get(f"/leads/{lead.pk}/ai/", **HTMX)
    assert b"every 2s" not in done.content
    assert done["HX-Trigger"] == "lead-scored"


def test_logging_an_activity_updates_the_timeline(browser, lead) -> None:
    response = browser.post(
        f"/leads/{lead.pk}/activities/",
        {"kind": "call", "body": "Intro call", "occurred_at": "2026-09-30T15:00"},
        **HTMX,
    )
    assert b"Intro call" in response.content
    lead.refresh_from_db()
    assert lead.last_activity_at is not None


def test_companies_page_lists_lead_counts(browser, lead) -> None:
    response = browser.get("/companies/?q=acme")
    assert b"acme.com" in response.content


def test_details_partial_shows_industry_after_scoring(browser, lead) -> None:
    response = browser.get(f"/leads/{lead.pk}/details/", **HTMX)
    assert b"Retail" in response.content
    assert b"<html" not in response.content
