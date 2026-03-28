import os
import sys
from pathlib import Path

# ── 1. Project root & virtualenv ──
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

VENV_BASE = "/home/jbeiqmqv/virtualenv/Hospital_Management_System/3.13"
activate_this = os.path.join(VENV_BASE, "bin", "activate_this.py")
if os.path.isfile(activate_this):
    exec(open(activate_this).read(), {"__file__": activate_this})

# ── 2. Load .env (production secrets) ──
from dotenv import load_dotenv  # noqa: E402

load_dotenv(dotenv_path=project_root / ".env")

# ── 3. Django WSGI ──
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
