from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.accounts.models import User, Shift, ShiftSecretCode


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "phone",
        "role",
        "radiology_unit_assignment",
        "branch",
        "is_active",
        "date_joined",
    )
    list_filter = ("role", "branch", "is_active", "is_staff")
    search_fields = ("username", "email", "first_name", "last_name", "phone")

    fieldsets = UserAdmin.fieldsets + (
        (
            "Clinic Access",
            {"fields": ("phone", "role", "radiology_unit_assignment", "branch")},
        ),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "Clinic Access",
            {
                "fields": (
                    "email",
                    "phone",
                    "role",
                    "radiology_unit_assignment",
                    "branch",
                )
            },
        ),
    )


@admin.register(ShiftSecretCode)
class ShiftSecretCodeAdmin(admin.ModelAdmin):
    list_display = ("user", "code", "updated_at")
    search_fields = ("user__username", "user__first_name", "user__last_name")


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("user", "branch", "status", "opened_at", "closed_at")
    list_filter = ("status", "branch")
    search_fields = ("user__username", "user__first_name", "user__last_name")
