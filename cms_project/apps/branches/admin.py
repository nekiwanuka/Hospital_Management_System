from django.contrib import admin

from apps.branches.models import Branch


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = (
        "branch_name",
        "branch_code",
        "city",
        "country",
        "shift_variance_threshold",
        "phone",
        "email",
        "status",
        "created_at",
    )
    search_fields = ("branch_name", "branch_code", "city", "country", "email")
    list_filter = ("status", "country", "city", "shift_variance_threshold")
    ordering = ("branch_name",)
