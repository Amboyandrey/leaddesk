"""Celery app, configured from Django settings keys that start with CELERY_."""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("leaddesk")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
