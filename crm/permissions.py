"""Who may call what: people use the CRM API, integration accounts may only push results."""

from rest_framework.permissions import BasePermission
from rest_framework.request import Request

INTEGRATION_GROUP = "integrations"


def is_integration_account(user) -> bool:
    """Report whether the user is a machine account, caching the answer on the user for this request."""
    if not hasattr(user, "_is_integration"):
        user._is_integration = user.groups.filter(name=INTEGRATION_GROUP).exists()
    return user._is_integration


class IsTeamMember(BasePermission):
    """Signed-in people; integration accounts are refused so a leaked push token can't read the CRM."""

    def has_permission(self, request: Request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and not is_integration_account(user))


class CanIngestN8nResults(BasePermission):
    """Only accounts granted the ingest permission may push n8n scoring results."""

    def has_permission(self, request: Request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.has_perm("crm.ingest_n8n_results"))
