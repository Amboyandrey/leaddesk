"""Backfill leads from a CSV export of the n8n `leads` data table, keeping their existing AI scores."""

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from crm import rules, services
from crm.models import Lead, ScoreEvent
from crm.n8n import Qualification

REQUIRED_COLUMNS = {"id", "website", "contact_name", "contact_email", "message", "fit_score"}


class Command(BaseCommand):
    help = "Backfill leads from an n8n data table CSV; rows attach to existing leads and repeats are skipped."

    def add_arguments(self, parser) -> None:
        parser.add_argument("csv_path", type=Path)

    def handle(self, *args, csv_path: Path, **options) -> None:
        if not csv_path.is_file():
            raise CommandError(f"File not found: {csv_path}")
        with csv_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise CommandError(f"CSV is missing columns: {', '.join(sorted(missing))}")
            imported = skipped = 0
            for row in reader:
                if self._import_row(row):
                    imported += 1
                else:
                    skipped += 1
        self.stdout.write(self.style.SUCCESS(f"Imported {imported} leads, skipped {skipped}."))

    def _import_row(self, row: dict[str, str]) -> bool:
        """Record one scored row on the contact's open lead (or a new one); False if invalid or done."""
        domain = rules.normalize_domain(row.get("website") or "")
        email = (row.get("contact_email") or "").strip()
        row_id = (row.get("id") or "").strip()
        if "." not in domain or not email or not row_id or not (row.get("fit_score") or "").strip():
            return False
        external_id = f"n8n-table:{row_id}"
        if ScoreEvent.objects.filter(external_id=external_id).exists():
            return False

        services.ingest_n8n_result(
            services.LeadIntake(
                website=domain,
                contact_name=(row.get("contact_name") or "").strip() or email,
                contact_email=email,
                message=(row.get("message") or "").strip(),
                source=Lead.Source.IMPORT,
            ),
            Qualification(
                fit_score=row["fit_score"],
                industry=(row.get("industry") or "")[:200],
                company_summary=row.get("company_summary") or "",
                need=row.get("need") or "",
                suggested_reply=row.get("suggested_reply") or "",
                raw={key: value for key, value in row.items() if key},
                external_id=external_id,
            ),
            score_source=ScoreEvent.Source.IMPORT,
        )
        return True
