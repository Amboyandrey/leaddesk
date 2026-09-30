"""Server-rendered pages; HTMX requests get partial templates so pages update without a reload."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from crm import rules, services
from crm.models import Company, Lead
from crm.permissions import is_integration_account
from crm.ranking import ranked_open_leads
from ui.forms import ActivityForm, LeadForm

PAGE_SIZE = 25


def team_member_required(view):
    """Signed-in people only; machine accounts such as the n8n integration are refused."""

    @login_required
    @wraps(view)
    def wrapper(request: HttpRequest, *args, **kwargs):
        if is_integration_account(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def _is_htmx(request: HttpRequest) -> bool:
    return request.headers.get("HX-Request") == "true"


def _lead_or_404(pk: int) -> Lead:
    return get_object_or_404(Lead.objects.select_related("company", "contact", "owner"), pk=pk)


@require_GET
@team_member_required
def board(request: HttpRequest) -> HttpResponse:
    """Priority view ranks open leads; the All view filters and searches every lead."""
    view = request.GET.get("view", "priority")
    status = request.GET.get("status", "")
    query = request.GET.get("q", "").strip()

    if view == "priority":
        leads = ranked_open_leads()
    else:
        view = "all"
        leads = Lead.objects.select_related("company", "contact", "owner")
        if status in Lead.Status.values:
            leads = leads.filter(status=status)
    if query:
        leads = leads.filter(
            Q(company__domain__icontains=query)
            | Q(company__name__icontains=query)
            | Q(contact__name__icontains=query)
            | Q(contact__email__icontains=query)
        )

    page = Paginator(leads, PAGE_SIZE).get_page(request.GET.get("page"))
    context = {"page": page, "view": view, "status": status, "query": query, "statuses": Lead.Status.choices}
    template = "ui/partials/lead_rows.html" if _is_htmx(request) else "ui/board.html"
    return render(request, template, context)


@team_member_required
def lead_new(request: HttpRequest) -> HttpResponse:
    form = LeadForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        lead = services.create_lead(services.LeadIntake(**form.cleaned_data), owner=request.user)
        return redirect("ui:lead", pk=lead.pk)
    return render(request, "ui/lead_new.html", {"form": form})


@require_GET
@team_member_required
def lead_detail(request: HttpRequest, pk: int) -> HttpResponse:
    lead = _lead_or_404(pk)
    context = {
        **_header_context(lead),
        **_ai_context(lead),
        **_activity_context(lead, ActivityForm()),
    }
    return render(request, "ui/lead_detail.html", context)


def _header_context(lead: Lead, error: str = "") -> dict:
    """The lead's status and only the moves the pipeline rules allow from it."""
    allowed = [(value, Lead.Status(value).label) for value in sorted(rules.TRANSITIONS[lead.status])]
    return {"lead": lead, "allowed_statuses": allowed, "status_error": error}


def _ai_context(lead: Lead) -> dict:
    return {"lead": lead, "score_events": lead.score_events.all()[:10]}


def _activity_context(lead: Lead, form: ActivityForm) -> dict:
    return {
        "lead": lead,
        "activities": lead.activities.select_related("created_by")[:50],
        "activity_form": form,
    }


@require_POST
@team_member_required
def lead_status(request: HttpRequest, pk: int) -> HttpResponse:
    """Apply a status change; on success the timeline is told to refresh because a note was added."""
    lead = _lead_or_404(pk)
    error = ""
    try:
        lead = services.change_status(lead, request.POST.get("status", ""), user=request.user)
        lead = _lead_or_404(pk)
    except rules.InvalidTransition as exc:
        error = str(exc)
    if not _is_htmx(request):
        return redirect("ui:lead", pk=pk)
    response = render(request, "ui/partials/lead_header.html", _header_context(lead, error))
    if not error:
        response["HX-Trigger"] = "activity-changed"
    return response


@require_GET
@team_member_required
def lead_ai(request: HttpRequest, pk: int) -> HttpResponse:
    """The AI panel alone; it polls itself while scoring is pending."""
    lead = _lead_or_404(pk)
    response = render(request, "ui/partials/ai_panel.html", _ai_context(lead))
    if lead.qualification != Lead.Qualification.PENDING:
        # Status may have been set by the scoring rules, so the header refreshes once scoring finishes
        response["HX-Trigger"] = "lead-scored"
    return response


@require_GET
@team_member_required
def lead_header(request: HttpRequest, pk: int) -> HttpResponse:
    return render(request, "ui/partials/lead_header.html", _header_context(_lead_or_404(pk)))


@require_GET
@team_member_required
def lead_details(request: HttpRequest, pk: int) -> HttpResponse:
    return render(request, "ui/partials/lead_details.html", {"lead": _lead_or_404(pk)})


@require_POST
@team_member_required
def lead_requalify(request: HttpRequest, pk: int) -> HttpResponse:
    lead = services.request_requalification(_lead_or_404(pk))
    if not _is_htmx(request):
        return redirect("ui:lead", pk=pk)
    return render(request, "ui/partials/ai_panel.html", _ai_context(lead))


@team_member_required
def lead_activities(request: HttpRequest, pk: int) -> HttpResponse:
    """GET returns the timeline; POST logs an activity and returns the refreshed timeline."""
    lead = _lead_or_404(pk)
    form = ActivityForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            services.log_activity(lead, user=request.user, **form.cleaned_data)
            form = ActivityForm()
        if not _is_htmx(request):
            return redirect("ui:lead", pk=pk)
    return render(request, "ui/partials/activities.html", _activity_context(lead, form))


@require_GET
@team_member_required
def companies(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "").strip()
    rows = Company.objects.annotate(lead_count=Count("leads")).order_by("name")
    if query:
        rows = rows.filter(Q(name__icontains=query) | Q(domain__icontains=query))
    page = Paginator(rows, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "ui/companies.html", {"page": page, "query": query})
