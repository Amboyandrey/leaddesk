"""Create the machine account n8n uses to push scoring results, and print its API token once."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token

from crm.permissions import INTEGRATION_GROUP

USERNAME = "n8n-integration"


class Command(BaseCommand):
    help = "Create the n8n integration account (push-only, no password) and print its token."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--rotate", action="store_true", help="Replace the existing token with a new one."
        )

    def handle(self, *args, rotate: bool, **options) -> None:
        group, _ = Group.objects.get_or_create(name=INTEGRATION_GROUP)
        group.permissions.set(
            [Permission.objects.get(codename="ingest_n8n_results", content_type__app_label="crm")]
        )

        user, created = get_user_model().objects.get_or_create(username=USERNAME)
        if created:
            user.set_unusable_password()
            user.save()
        user.groups.add(group)

        if rotate:
            Token.objects.filter(user=user).delete()
        token, _ = Token.objects.get_or_create(user=user)
        self.stdout.write(token.key)
