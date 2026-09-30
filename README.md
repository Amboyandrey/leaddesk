# LeadDesk

A lead CRM API built with Django and Django REST Framework. New leads are scored by AI through an
n8n workflow exposed as an MCP server, ranked by a priority formula computed in PostgreSQL, and moved
through a pipeline that only allows valid status changes.

## How it works

```
POST /api/leads/ ──► Django (company by domain, contact by email, lead) ──► 201, status "new"
                         │ on commit
                         ▼
                    Celery worker ──MCP──► n8n "qualify_lead" (reads the site, AI scores it)
                         │ retries outages with backoff, gives up after 4 retries
                         ▼
                    ScoreEvent saved, lead scored, status set by fixed thresholds
```

- **Real-time sync from n8n**: after every Qualify Lead run, whoever called it (ReCore, LeadDesk, or
  anything else using the MCP tool), n8n POSTs the result to `/api/integrations/n8n/lead-scored/`.
  LeadDesk updates the contact's open lead or creates one. Each result carries the n8n execution id,
  which is unique per score event, so a run that arrives both as the MCP reply and as the push is
  stored once.
- **Scoring** runs in the background, so the API answers immediately. A failed score never blocks
  the lead; it is marked `failed` and can be retried with `POST /api/leads/{id}/requalify/`.
- **Decision rules** live in `crm/rules.py`: scores of 70 or more are `qualified`, 40 to 69
  `needs_review`, below 40 `not_a_fit`. Once a person has contacted a lead, a new score updates the
  numbers but never overrides the status.
- **Status pipeline**: `new → qualified / needs_review / not_a_fit → contacted → won / lost`. Invalid
  moves return `409` with the allowed options, and every change is logged as an activity.
- **Priority ranking** (`crm/ranking.py`), computed in SQL:
  `fit × 0.5^(days since last touch / 14) + 4 × min(activities in last 14 days, 5)`.
  Strong leads go cold if nobody touches them; recent calls and emails keep them near the top.
- **Caching**: ranked pages are cached in Redis and invalidated on any lead or activity write.

## Data model

`Company` (unique domain) → `Contact` (unique email, case-insensitive) → `Lead` → `Activity` and
`ScoreEvent` (full scoring history). Scores are limited to 0–100 by database check constraints, and
indexes match the real queries: leads by status and date, pending scoring, and each lead's timeline.

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/leads/` | Intake a lead (website, contact name and email, message) |
| `GET /api/leads/` | List with filters (`status`, `qualification`, `source`, `company`, `owner`), search, ordering |
| `GET /api/leads/ranked/` | Open leads by priority |
| `POST /api/leads/{id}/status/` | Change status under the pipeline rules |
| `GET/POST /api/leads/{id}/activities/` | Timeline, or log a call, email, meeting, or note |
| `GET /api/leads/{id}/scores/` | Scoring history |
| `POST /api/leads/{id}/requalify/` | Score again |
| `/api/companies/`, `/api/contacts/` | CRUD |
| `/api/docs/` | Swagger UI |

Authenticate with `Authorization: Token <key>` (`POST /api/auth/token/` with a username and password).

## Run it

Requires Docker and the local n8n stack with the Lead Tools MCP server running (network
`n8n-local_default`). The MCP bearer token is read from `~/.config/n8n-lead-tools/token` and mounted
only into the worker as a Docker secret.

```bash
cp .env.example .env            # then set DJANGO_SECRET_KEY
docker compose up -d --build    # API on http://localhost:8001, docs at /api/docs/
docker compose exec web python manage.py createsuperuser
```

Let n8n push results: create the push-only integration account and save its token to a private file,
then add it in n8n as a Header Auth credential (`Authorization: Token <key>`) on the "Push to
LeadDesk" node. That account can call only the push endpoint; every other route refuses it.

```bash
(umask 077; docker compose exec -T web python manage.py create_n8n_integration_user | tail -n1 \
  > ~/.config/leaddesk/n8n-integration-token)
```

For a one-time backfill of leads scored before the push existed, export the n8n `leads` data table
as CSV (scores are kept, repeats skipped):

```bash
docker compose cp leads.csv web:/tmp/leads.csv
docker compose exec web python manage.py import_n8n_leads /tmp/leads.csv
```

## Tests

```bash
docker compose up -d postgres redis
uv sync && uv run ruff check . && uv run pytest
```

55 tests run against real PostgreSQL with n8n replaced by a fake scorer. They cover the pipeline rules,
score normalization, task retries and failures, ranking order and decay, cache invalidation, the push
endpoint (upserts, one record per n8n run, push-only permissions), the CSV import, and a fixed number
of queries for the list and ranking endpoints (no N+1 queries).
