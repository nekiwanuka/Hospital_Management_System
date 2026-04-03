from django.contrib import admin

from apps.permissions.models import PermissionAccessRequest, UserModulePermission


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


@admin.register(PermissionAccessRequest)
class PermissionAccessRequestAdmin(admin.ModelAdmin):
    list_display = ("user", "module_name", "status", "created_at", "reviewed_by")
    list_filter = ("status", "module_name")
    search_fields = ("user__username", "module_name")
