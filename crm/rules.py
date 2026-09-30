"""Decision rules for leads: which status changes are allowed, and how a fit score maps to a status."""

import re

from crm.models import Lead

Status = Lead.Status

QUALIFIED_MIN_SCORE = 70
REVIEW_MIN_SCORE = 40

# Allowed manual transitions; won and lost are final
TRANSITIONS: dict[str, frozenset[str]] = {
    Status.NEW: frozenset({Status.QUALIFIED, Status.NEEDS_REVIEW, Status.NOT_A_FIT, Status.CONTACTED}),
    Status.QUALIFIED: frozenset({Status.CONTACTED, Status.NOT_A_FIT, Status.LOST}),
    Status.NEEDS_REVIEW: frozenset({Status.QUALIFIED, Status.NOT_A_FIT, Status.CONTACTED}),
    Status.NOT_A_FIT: frozenset({Status.NEEDS_REVIEW}),
    Status.CONTACTED: frozenset({Status.WON, Status.LOST}),
    Status.WON: frozenset(),
    Status.LOST: frozenset(),
}

# Once a person has contacted the lead, a new AI score updates the numbers but never overrides the status
AI_MAY_SET_STATUS_FROM = frozenset({Status.NEW, Status.QUALIFIED, Status.NEEDS_REVIEW, Status.NOT_A_FIT})

OPEN_STATUSES = frozenset({Status.NEW, Status.QUALIFIED, Status.NEEDS_REVIEW, Status.CONTACTED})


class InvalidTransition(ValueError):
    """Raised when a status change is not allowed from the lead's current status."""


def can_transition(current: str, target: str) -> bool:
    """Report whether a lead may move from one status to another."""
    return target in TRANSITIONS.get(current, frozenset())


def ensure_transition(current: str, target: str) -> None:
    """Raise InvalidTransition unless the change is allowed."""
    if not can_transition(current, target):
        allowed = ", ".join(sorted(TRANSITIONS.get(current, ()))) or "none (final status)"
        raise InvalidTransition(f"Cannot move a lead from '{current}' to '{target}'. Allowed: {allowed}.")


def normalize_score(raw: object) -> int:
    """Turn a model's score into an integer from 0 to 100, reading 0-1 values as fractions."""
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    if 0 < value <= 1:
        value *= 100
    return max(0, min(100, round(value)))


def status_for_score(score: int) -> str:
    """Map a 0-100 fit score to the status the scoring rules assign."""
    if score >= QUALIFIED_MIN_SCORE:
        return Status.QUALIFIED
    if score >= REVIEW_MIN_SCORE:
        return Status.NEEDS_REVIEW
    return Status.NOT_A_FIT


_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://")


def normalize_domain(value: str) -> str:
    """Reduce a URL or domain to a bare lowercase host, e.g. 'https://Www.Acme.com/x' -> 'acme.com'."""
    host = _SCHEME.sub("", value.strip().lower()).split("/", 1)[0].split("?", 1)[0].split(":", 1)[0]
    return host.removeprefix("www.")
