"""Shared fixtures: an authenticated API client, in-memory cache, eager Celery, and a fake n8n scorer."""

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APIClient

from config.celery import app as celery_app
from crm import n8n


@pytest.fixture(autouse=True)
def _isolated_cache_and_eager_celery(settings):
    """Use a per-test in-memory cache, plain static files (no collectstatic), and run Celery tasks inline."""
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    cache.clear()
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
    assert celery_app.conf.task_always_eager, "Celery must read the overridden Django settings"
    yield
    cache.clear()


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="andrey", password="not-used-in-tests-123")


@pytest.fixture
def api(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def fake_n8n(monkeypatch):
    """Replace the n8n call with a scorer that returns a fixed score and records each call."""

    class FakeScorer:
        def __init__(self) -> None:
            self.score: object = 85
            self.calls: list[dict[str, str]] = []

        def __call__(self, **arguments: str) -> n8n.Qualification:
            self.calls.append(arguments)
            return n8n.Qualification(
                fit_score=self.score,
                industry="Software",
                company_summary="Builds automation tools.",
                need="An AI support assistant.",
                suggested_reply="Hi, thanks for reaching out.",
                raw={"fit_score": self.score},
            )

    scorer = FakeScorer()
    monkeypatch.setattr(n8n, "qualify", scorer)
    return scorer
