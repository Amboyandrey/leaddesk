"""Parsing the n8n tool output, and the scoring task's retry and failure handling."""

import pytest

from crm import n8n, services
from crm.models import Lead, ScoreEvent
from crm.tasks import MAX_RETRIES, qualify_lead_task


def test_parse_result_accepts_a_one_item_array() -> None:
    result = n8n.parse_result('[{"fit_score": 90, "industry": "SaaS", "need": "chatbot"}]')
    assert result.fit_score == 90
    assert result.industry == "SaaS"


def test_parse_result_accepts_an_object() -> None:
    assert n8n.parse_result('{"fit_score": 12}').fit_score == 12


@pytest.mark.parametrize("text", ["not json", "[]", '{"industry": "SaaS"}'])
def test_parse_result_rejects_unusable_output(text: str) -> None:
    with pytest.raises(n8n.N8nBadResult):
        n8n.parse_result(text)


def _pending_lead() -> Lead:
    return services.create_lead(
        services.LeadIntake(
            website="acme.com", contact_name="Jane", contact_email="jane@acme.com", message="hi"
        ),
        enqueue=False,
    )


@pytest.mark.django_db
def test_task_scores_a_pending_lead(fake_n8n) -> None:
    lead = _pending_lead()
    assert qualify_lead_task.apply(args=[lead.pk]).get() == "done"
    lead.refresh_from_db()
    assert (lead.fit_score, lead.status, lead.qualification) == (85, Lead.Status.QUALIFIED, "done")
    assert fake_n8n.calls[0]["website"] == "acme.com"
    assert ScoreEvent.objects.filter(lead=lead, source=ScoreEvent.Source.N8N_MCP).count() == 1


@pytest.mark.django_db
def test_task_retries_outages_then_marks_the_lead_failed(monkeypatch, settings) -> None:
    # Eager apply() replays each retry itself only when exceptions are not propagated
    settings.CELERY_TASK_EAGER_PROPAGATES = False
    attempts = []

    def unavailable(**_: str) -> n8n.Qualification:
        attempts.append(1)
        raise n8n.N8nUnavailable("connection refused")

    monkeypatch.setattr(n8n, "qualify", unavailable)
    lead = _pending_lead()
    assert qualify_lead_task.apply(args=[lead.pk]).get() == "failed"
    lead.refresh_from_db()
    assert len(attempts) == MAX_RETRIES + 1
    assert lead.qualification == Lead.Qualification.FAILED
    assert "connection refused" in lead.qualification_error


@pytest.mark.django_db
def test_task_does_not_retry_a_bad_result(monkeypatch) -> None:
    attempts = []

    def bad(**_: str) -> n8n.Qualification:
        attempts.append(1)
        raise n8n.N8nBadResult("no fit_score")

    monkeypatch.setattr(n8n, "qualify", bad)
    lead = _pending_lead()
    assert qualify_lead_task.apply(args=[lead.pk]).get() == "failed"
    assert len(attempts) == 1


@pytest.mark.django_db
def test_task_skips_a_lead_that_is_not_pending(fake_n8n) -> None:
    lead = _pending_lead()
    Lead.objects.filter(pk=lead.pk).update(qualification=Lead.Qualification.DONE)
    assert qualify_lead_task.apply(args=[lead.pk]).get() == "skipped"
    assert fake_n8n.calls == []


@pytest.mark.django_db
def test_a_new_score_never_overrides_a_status_a_person_set(fake_n8n) -> None:
    lead = _pending_lead()
    Lead.objects.filter(pk=lead.pk).update(status=Lead.Status.CONTACTED)
    fake_n8n.score = 10
    qualify_lead_task.apply(args=[lead.pk])
    lead.refresh_from_db()
    assert lead.status == Lead.Status.CONTACTED
    assert lead.fit_score == 10
