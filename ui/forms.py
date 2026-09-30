"""HTML forms for the UI; they validate input and hand it to crm.services."""

from django import forms
from django.utils import timezone

from crm import rules
from crm.models import Activity


class LeadForm(forms.Form):
    website = forms.CharField(max_length=300, widget=forms.TextInput(attrs={"placeholder": "acme.com"}))
    company_name = forms.CharField(max_length=200, required=False)
    contact_name = forms.CharField(max_length=200)
    contact_email = forms.EmailField()
    message = forms.CharField(
        max_length=5000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "What did they ask for?"}),
    )

    def clean_website(self) -> str:
        domain = rules.normalize_domain(self.cleaned_data["website"])
        if "." not in domain:
            raise forms.ValidationError("Enter a website like acme.com.")
        return domain


class ActivityForm(forms.Form):
    kind = forms.ChoiceField(choices=Activity.Kind.choices)
    body = forms.CharField(
        required=False, max_length=5000, widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Notes"})
    )
    occurred_at = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M"],
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial["occurred_at"] = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
