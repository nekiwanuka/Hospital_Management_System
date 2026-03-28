import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# -------------------------------
# 1. Add your project to sys.path
# -------------------------------
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

# -------------------------------
# 2. Load environment variables from .env
# -------------------------------
env_path = project_root / ".env"
load_dotenv(dotenv_path=env_path)

# -------------------------------
# 3. Set the DJANGO_SETTINGS_MODULE
# -------------------------------
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# -------------------------------
# 4. Activate your virtualenv (if needed)
# -------------------------------
# Optional: Only if Passenger does not use your virtualenv by default
# activate_this = "/home/jbeiqmqv/virtualenv/home/jbeiqmqv/repositories/Hospital_Management_System/3.13/bin/activate_this.py"
# exec(open(activate_this).read(), dict(__file__=activate_this))

# -------------------------------
# 5. Import Django WSGI application
# -------------------------------
from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
