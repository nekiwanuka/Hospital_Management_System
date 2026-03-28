from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand


ROLE_APP_PERMISSIONS = {
    "director": [
        "branches",
        "patients",
        "triage",
        "consultation",
        "laboratory",
        "radiology",
        "pharmacy",
        "billing",
        "admission",
        "referrals",
        "emergency",
        "inventory",
        "reports",
        "settingsapp",
        "accounts",
        "core",
    ],
    "system_admin": [
        "branches",
        "patients",
        "triage",
        "consultation",
        "laboratory",
        "radiology",
        "pharmacy",
        "billing",
        "admission",
        "referrals",
        "emergency",
        "inventory",
        "reports",
        "settingsapp",
        "accounts",
        "core",
    ],
    "doctor": [
        "patients",
        "consultation",
        "laboratory",
        "radiology",
        "triage",
        "referrals",
        "admission",
    ],
    "radiologist": ["patients", "radiology", "consultation"],
    "radiology_technician": ["patients", "radiology"],
    "nurse": ["patients", "triage", "admission"],
    "triage_officer": ["patients", "triage"],
    "lab_technician": ["patients", "laboratory", "radiology"],
    "pharmacist": ["patients", "pharmacy"],
    "cashier": ["patients", "billing"],
    "receptionist": ["patients"],
}


class Command(BaseCommand):
    help = "Create and update role groups with default permissions."

    def handle(self, *args, **options):
        created_groups = 0

        for role, app_labels in ROLE_APP_PERMISSIONS.items():
            group, created = Group.objects.get_or_create(name=role)
            if created:
                created_groups += 1

            perms = Permission.objects.filter(content_type__app_label__in=app_labels)
            group.permissions.set(perms)
            group.save()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Role group '{role}' synced with {perms.count()} permissions."
                )
            )

        User = get_user_model()
        updated = 0
        for user in User.objects.all():
            group = Group.objects.filter(name=user.role).first()
            if group and not user.groups.filter(id=group.id).exists():
                user.groups.add(group)
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"Created {created_groups} new groups."))
        self.stdout.write(
            self.style.SUCCESS(
                f"Assigned groups to {updated} existing users based on role."
            )
        )
