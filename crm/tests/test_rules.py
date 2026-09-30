"""Pure decision rules: transitions, score normalization, thresholds, and domain cleanup."""

import pytest

from crm import rules
from crm.models import Lead

S = Lead.Status


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        (S.NEW, S.CONTACTED, True),
        (S.QUALIFIED, S.CONTACTED, True),
        (S.CONTACTED, S.WON, True),
        (S.NOT_A_FIT, S.NEEDS_REVIEW, True),
        (S.NEW, S.WON, False),
        (S.WON, S.LOST, False),
        (S.LOST, S.CONTACTED, False),
        (S.NOT_A_FIT, S.CONTACTED, False),
    ],
)
def test_transitions(current: str, target: str, allowed: bool) -> None:
    assert rules.can_transition(current, target) is allowed


def test_invalid_transition_explains_what_is_allowed() -> None:
    with pytest.raises(rules.InvalidTransition, match="final status"):
        rules.ensure_transition(S.WON, S.LOST)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(85, 85), ("72", 72), (0.85, 85), (1, 100), (150, 100), (-5, 0), ("junk", 0), (None, 0), (69.6, 70)],
)
def test_normalize_score(raw: object, expected: int) -> None:
    assert rules.normalize_score(raw) == expected


@pytest.mark.parametrize(
    ("score", "status"),
    [(100, S.QUALIFIED), (70, S.QUALIFIED), (69, S.NEEDS_REVIEW), (40, S.NEEDS_REVIEW), (39, S.NOT_A_FIT)],
)
def test_status_for_score_thresholds(score: int, status: str) -> None:
    assert rules.status_for_score(score) == status


@pytest.mark.parametrize(
    ("value", "domain"),
    [
        ("https://www.Acme.com/pricing?x=1", "acme.com"),
        ("acme.com", "acme.com"),
        ("  HTTP://shop.acme.co.uk:8080/ ", "shop.acme.co.uk"),
    ],
)
def test_normalize_domain(value: str, domain: str) -> None:
    assert rules.normalize_domain(value) == domain
