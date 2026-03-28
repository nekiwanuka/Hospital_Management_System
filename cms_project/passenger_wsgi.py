import sys
import os

# Path to your Django root (where manage.py is)
project_home = "/home/jbeiqmqv/repositories/Hospital_Management_System/cms_project"

if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Django settings module (IMPORTANT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
