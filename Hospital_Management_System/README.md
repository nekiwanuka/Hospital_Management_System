# ClinicMS v2

Clinic Management System v2 built with Django templates, Bootstrap 5, minimal JavaScript, and SQLite by default (PostgreSQL-ready via `DATABASE_URL`).

## Requirements

- Python 3.11+
- pip

## Quick Start

1. Create and activate a virtual environment.
2. Install dependencies.
3. Run migrations.
4. Bootstrap role groups and permissions.
5. Seed demo data.
6. Start the server.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py bootstrap_roles
python manage.py seed_demo
python manage.py runserver
```

## First Login

Any seeded user can log in with password `Passw0rd!`.

Suggested initial account:

- Username: `sysadmin`
- Role: `system_admin`

## Role and Permission Bootstrap

Run this anytime after migrations:

```powershell
python manage.py bootstrap_roles
```

This command:

- Creates groups matching role names in the custom User model.
- Assigns app-level model permissions by role profile.
- Synchronizes existing users into groups based on their `role` field.

## Demo Data Seed

Run:

```powershell
python manage.py seed_demo
```

This command seeds:

- Initialized `SystemSettings`
- Main branch (`MAIN`)
- Demo users for all primary roles
- Patients, triage records, consultations, lab requests, invoices, and medicines

## Database Configuration

Default database is SQLite.

For PostgreSQL later, set `DATABASE_URL` in environment:

```text
postgres://USERNAME:PASSWORD@HOST:5432/DBNAME
```

Then run:

```powershell
python manage.py migrate
```

## Implemented Starter Modules

- Patients
- Triage
- Consultation
- Laboratory
- Pharmacy
- Billing

Each starter module now has:

- URL route
- Role-guarded index view
- Branch-scoped query behavior
- Basic template page
