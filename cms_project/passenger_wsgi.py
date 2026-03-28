"""
Phusion Passenger entry point for cPanel Python hosting.
cPanel looks for `passenger_wsgi.py` in the application root.
"""

import os
import sys

# ── Point to your project directory ──
# Adjust this path to match where cPanel places your project.
# Typically:  /home/<cpanel_user>/HMS/cms_project
APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)

# ── If using a virtualenv created via cPanel's "Setup Python App" ──
# cPanel auto-activates it, but if you need to force it:
# VENV = os.path.join(os.path.dirname(APP_DIR), '.venv')
# VENV_ACTIVATE = os.path.join(VENV, 'bin', 'activate_this.py')
# if os.path.isfile(VENV_ACTIVATE):
#     exec(open(VENV_ACTIVATE).read(), {'__file__': VENV_ACTIVATE})

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
