from django.contrib import admin

from apps.permissions.models import UserModulePermission


@admin.register(UserModulePermission)
class UserModulePermissionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "module_name",
        "can_soft_delete",
        "can_hard_delete",
        "granted_by",
        "granted_at",
    )
    list_filter = ("module_name", "can_soft_delete", "can_hard_delete")
    search_fields = ("user__username", "module_name")
