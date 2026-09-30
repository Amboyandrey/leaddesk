from django.contrib import admin

from crm.models import Activity, Company, Contact, Lead, ScoreEvent


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ["domain", "name", "industry", "created_at"]
    search_fields = ["domain", "name"]


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ["name", "email", "company"]
    list_select_related = ["company"]
    search_fields = ["name", "email"]


class ActivityInline(admin.TabularInline):
    model = Activity
    extra = 0


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ["id", "company", "contact", "status", "fit_score", "qualification", "created_at"]
    list_filter = ["status", "qualification", "source"]
    list_select_related = ["company", "contact"]
    search_fields = ["company__domain", "contact__email"]
    inlines = [ActivityInline]


@admin.register(ScoreEvent)
class ScoreEventAdmin(admin.ModelAdmin):
    list_display = ["lead", "fit_score", "suggested_status", "source", "created_at"]
    list_select_related = ["lead"]
