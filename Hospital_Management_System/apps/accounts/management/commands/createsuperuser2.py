"""
Custom superuser creation that handles the required branch FK.

Usage:
    python manage.py createsuperuser2
"""

import getpass

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.branches.models import Branch


class Command(BaseCommand):
    help = "Create a superuser with automatic branch assignment."

    def add_arguments(self, parser):
        parser.add_argument("--username", dest="username")
        parser.add_argument("--email", dest="email", default="")
        parser.add_argument("--noinput", action="store_true")

    def handle(self, *args, **options):
        branch = Branch.objects.first()
        if branch is None:
            self.stdout.write("No branch exists — creating default Main Branch …")
            branch = Branch.objects.create(
                branch_name="Main Branch",
                branch_code="MAIN",
                address="—",
                city="Kampala",
                country="Uganda",
                phone="—",
                email="admin@hospital.local",
            )
            self.stdout.write(self.style.SUCCESS(f"Created branch: {branch}"))

        username = options.get("username") or input("Username: ")
        email = options.get("email") or input("Email address: ")

        if options.get("noinput"):
            password = username  # only for CI / automated setups
        else:
            password = getpass.getpass("Password: ")
            password2 = getpass.getpass("Password (again): ")
            if password != password2:
                raise CommandError("Passwords didn't match.")

        if User.objects.filter(username=username).exists():
            raise CommandError(f"User '{username}' already exists.")

        user = User(
            username=username,
            email=email,
            branch=branch,
            role="director",
            is_staff=True,
            is_superuser=True,
            is_active=True,
        )
        user.set_password(password)
        # bypass full_clean password-similarity validator
        super(User, user).save()
        user._sync_role_group()

        self.stdout.write(
            self.style.SUCCESS(f"Superuser '{username}' created (branch: {branch}).")
        )
