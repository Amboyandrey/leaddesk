"""Priority ranking for open leads, computed in PostgreSQL so the database sorts and paginates it.

priority = fit x 0.5 ^ (days since last touch / HALF_LIFE_DAYS)
           + ACTIVITY_POINTS x min(recent activities, ACTIVITY_CAP)

A strong lead goes cold if nobody touches it, and recent calls or emails keep it near the top. Unscored
leads count as NEUTRAL_FIT so a fresh inbound lead is not buried while it waits for scoring.
"""

from datetime import timedelta

from django.db.models import Count, DurationField, ExpressionWrapper, F, FloatField, Func, Q, QuerySet, Value
from django.db.models.functions import Cast, Coalesce, Least, Now, Power, Round
from django.utils import timezone

from crm.models import Lead
from crm.rules import OPEN_STATUSES

HALF_LIFE_DAYS = 14.0
NEUTRAL_FIT = 50.0
ACTIVITY_WINDOW_DAYS = 14
ACTIVITY_POINTS = 4.0
ACTIVITY_CAP = 5


class EpochSeconds(Func):
    """EXTRACT(EPOCH FROM <interval>) as a float number of seconds."""

    template = "EXTRACT(EPOCH FROM %(expressions)s)"
    output_field = FloatField()


def ranked_open_leads() -> QuerySet[Lead]:
    """Open leads annotated with `priority` and sorted by it, highest first, with related rows preloaded."""
    last_touch = Coalesce(F("last_activity_at"), F("created_at"))
    age_days = EpochSeconds(ExpressionWrapper(Now() - last_touch, output_field=DurationField())) / Value(
        86400.0
    )
    fit = Coalesce(Cast("fit_score", FloatField()), Value(NEUTRAL_FIT))
    recent = Count(
        "activities",
        filter=Q(activities__occurred_at__gte=timezone.now() - timedelta(days=ACTIVITY_WINDOW_DAYS)),
    )
    decay = Power(Value(0.5), age_days / Value(HALF_LIFE_DAYS))
    activity_bonus = Cast(Least(recent, Value(ACTIVITY_CAP)), FloatField()) * Value(ACTIVITY_POINTS)

    return (
        Lead.objects.filter(status__in=OPEN_STATUSES)
        .select_related("company", "contact", "owner")
        .annotate(recent_activity_count=recent)
        .annotate(priority=Round(fit * decay + activity_bonus, 2))
        .order_by("-priority", "-created_at")
    )
