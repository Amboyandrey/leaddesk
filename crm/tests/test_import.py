"""Importing the n8n leads CSV keeps existing scores and is safe to run twice."""

import pytest
from django.core.management import call_command

from crm import services
from crm.models import Lead, ScoreEvent

CSV = (
    "id,website,contact_name,contact_email,message,fit_score,status,industry,company_summary,need,suggested_reply\n"
    "1,n8n.io,Maria Santos,maria@example.com,Docs chatbot,90,qualified,Automation,Workflow tool,AI,Hi Maria\n"
    "2,wikipedia.org,Tom Reyes,tom@example.com,Printer ink?,5,not_a_fit,Non-profit,Encyclopedia,None,Hi Tom\n"
    "3,,No Site,nosite@example.com,Missing website,50,needs_review,,,,\n"
)


@pytest.mark.django_db
def test_import_keeps_scores_and_skips_repeats(tmp_path, capsys) -> None:
    path = tmp_path / "leads.csv"
    path.write_text(CSV)

    call_command("import_n8n_leads", str(path))
    call_command("import_n8n_leads", str(path))

    leads = {lead.company.domain: lead for lead in Lead.objects.select_related("company")}
    assert set(leads) == {"n8n.io", "wikipedia.org"}
    assert (leads["n8n.io"].fit_score, leads["n8n.io"].status) == (90, Lead.Status.QUALIFIED)
    assert leads["wikipedia.org"].status == Lead.Status.NOT_A_FIT
    assert ScoreEvent.objects.filter(source=ScoreEvent.Source.IMPORT).count() == 2
    assert "Imported 0 leads, skipped 3." in capsys.readouterr().out


@pytest.mark.django_db
def test_import_attaches_to_a_contacts_existing_lead(tmp_path) -> None:
    existing = services.create_lead(
        services.LeadIntake(
            website="n8n.io", contact_name="Maria Santos", contact_email="maria@example.com", message="hi"
        ),
        enqueue=False,
    )
    path = tmp_path / "leads.csv"
    path.write_text(CSV)

    call_command("import_n8n_leads", str(path))

    assert Lead.objects.filter(company__domain="n8n.io").count() == 1
    existing.refresh_from_db()
    assert (existing.fit_score, existing.source) == (90, Lead.Source.API)
